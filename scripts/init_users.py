"""初始化 web 账号（spec §2）：app_user 建号 / 改绑；密码走 env 或随机生成打印一次。

最小账号面（README §9.7 拍板重述）：无管理 UI，本脚本即开户界面。
账号 ↔ role / Person 绑定与 permissions.yaml bindings 同源对齐（启动即对账，
见 _check_role_bindings——两处角色/person 映射不一致显式报错，不再手工双份
静默漂移）；李昂双角色（ae / optimizer token 各一枚）在账号面取 AE（org_role 口径）。

用法：
  ADKG_USER_PASSWORD=xxx uv run python scripts/init_users.py              # 统一密码
  uv run python scripts/init_users.py --reset-password                   # 逐号随机重置并打印
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

import psycopg
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

import os  # noqa: E402  （dotenv 之后取值）

from adkg.guards.passwords import hash_password  # noqa: E402

USERS = [
    # username, display_name, role, person
    ("chen", "陈朔", "management", "Person:chen"),
    ("li", "李昂", "ae", "Person:li"),
    ("zhao", "赵岚", "optimizer", "Person:zhao"),
    ("sun", "孙苗", "optimizer", "Person:sun"),
    ("wang", "王雪", "creative", "Person:wang"),
    ("zhou", "周荃", "finance", "Person:zhou"),
    ("gu", "顾佳", "client", "Person:client_a"),
    ("admin", "管理员", "admin", None),      # 运维账号：不绑业务 Person
]


def _check_role_bindings() -> None:
    """账号面 ↔ permissions.yaml bindings 对账（缺陷清单⑦a）：USERS 与 bindings
    是同一套 RBAC 的两张脸（web 账号面 / token 面），手工双份必漂移——建号前
    校验，不一致显式报错退出（先改 yaml 再改本表）：
      ① 账号角色必须仍在 permissions.yaml roles 中；
      ② 账号 person 有 token 绑定的，账号角色须落在该 person 的绑定角色集内
        （李昂双角色账号面取 AE，属合法子集）；
      ③ bindings 绑定的 person 在账号面必须有承接——无同名 person 账号的，
        允许由同角色的无 person 运维账号承接（Person:admin ↔ admin 账号）。
    """
    data = yaml.safe_load((ROOT / "ontology" / "permissions.yaml")
                          .read_text(encoding="utf-8"))
    bound: dict[str, set[str]] = {}
    for b in (data.get("bindings") or {}).values():
        bound.setdefault(str(b["person"]), set()).add(str(b["role"]))
    roles = set(data.get("roles") or {})
    persons = {p for _, _, _, p in USERS if p}
    ops = {r for _, _, r, p in USERS if p is None}    # 无 person 运维账号的角色
    for username, _display, role, person in USERS:
        if role not in roles:
            sys.exit(f"账号 {username} 的角色 {role} 不在 permissions.yaml roles——"
                     "先改 yaml 再改本表（缺陷清单⑦a 对账）")
        if person in bound and role not in bound[person]:
            sys.exit(f"账号 {username}（{person}）角色 {role} 与 bindings 绑定角色 "
                     f"{sorted(bound[person])} 不一致（缺陷清单⑦a 对账）")
    for person, b_roles in bound.items():
        if person not in persons and not b_roles & ops:
            sys.exit(f"bindings 绑定 {person}（角色 {sorted(b_roles)}）在账号面无承接——"
                     "补账号或改绑定（缺陷清单⑦a 对账）")


def main() -> None:
    _check_role_bindings()
    reset = "--reset-password" in sys.argv
    env_pw = os.environ.get("ADKG_USER_PASSWORD")
    printed: list[str] = []
    with psycopg.connect(os.environ["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        for username, display, role, person in USERS:
            existing = cur.execute(
                "SELECT 1 FROM app_user WHERE username = %s", (username,)).fetchone()
            if existing and not reset:
                cur.execute("UPDATE app_user SET display_name=%s, role=%s, person=%s, "
                            "disabled=false WHERE username=%s",
                            (display, role, person, username))
                continue
            pw = env_pw or secrets.token_urlsafe(12)
            cur.execute(
                "INSERT INTO app_user (id, username, password_hash, display_name, role, person)"
                " VALUES (%s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash,"
                " display_name=EXCLUDED.display_name, role=EXCLUDED.role,"
                " person=EXCLUDED.person, disabled=false",
                (f"u_{username}", username, hash_password(pw), display, role, person))
            printed.append(f"{username:<8} {display}  {role:<10} 密码：{pw}")
    print(f"账号就绪：{len(USERS)} 个（改绑生效；未改密的保持原密码）")
    if printed:
        print("新设/重置密码（仅此一次打印，请妥善保存）：")
        for line in printed:
            print(f"  {line}")


if __name__ == "__main__":
    try:
        main()
    except psycopg.OperationalError as e:
        sys.exit(f"连不上 Postgres（先 docker compose up -d + init_db.py）：{e}")
    except psycopg.errors.UndefinedTable as e:
        sys.exit(f"缺表（先跑 uv run python scripts/init_db.py 执行 003_auth.sql）：{e}")
