"""初始化 web 账号（spec §2）：app_user 建号 / 改绑；密码走 env 或随机生成打印一次。

最小账号面（README §9.7 拍板重述）：无管理 UI，本脚本即开户界面。
账号 ↔ role / Person 绑定与 permissions.yaml bindings 同源对齐；李昂双角色
（ae / optimizer token 各一枚）在账号面取 AE（org_role 口径）。

用法：
  ADKG_USER_PASSWORD=xxx uv run python scripts/init_users.py              # 统一密码
  uv run python scripts/init_users.py --reset-password                   # 逐号随机重置并打印
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

import psycopg
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


def main() -> None:
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
