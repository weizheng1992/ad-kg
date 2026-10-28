"""RBAC 角色门统一收口（spec §18；夜检挂账「角色门散抄」一并清账）。

- ACTIONS：按钮/操作权限词表（单一来源，前后端共享语义）
- GATES：端点级角色门 → 所需 action 的映射；系统角色的初始 action 集自
  permissions.yaml 语义播种（SYSTEM_ROLE_ACTIONS），DB 可调（app_role_action）
- 自定义角色：数据面等同基角色（http.resolve_identity 已映射）；菜单与按钮
  权限独立配置——role_allows 对自定义角色查 DB（无记录时继承基角色的门行为）
"""
from __future__ import annotations

import psycopg

from adkg.store import pg_pool
from psycopg.rows import dict_row

# 按钮权限词表（前端按钮显隐同一份语义）
ACTIONS: dict[str, str] = {
    "creator_write": "达人录入 / 导入",
    "creator_export": "达人导出",
    "case_stage_change": "案例阶段变更",
    "settlement_view": "财务结算查看",
    "review_resolve": "人审处置",
    "account_manage": "人员管理写操作",
    "menu_manage": "菜单管理写操作",
    "admin_view": "管理后台（审计 / 人审 / 权限查看）",
    "dashboard_view": "数据看板",
}

# 端点门 → action
GATES: dict[str, str] = {
    "dashboard": "dashboard_view",
    "settlement": "settlement_view",
    "creator_write": "creator_write",
    "case_stage": "case_stage_change",
    "review_resolve": "review_resolve",
    "account_write": "account_manage",
    "menu_write": "menu_manage",
    "admin_view": "admin_view",
}

# 系统角色初始 action 播种（= 既有散抄集合的语义；permissions.yaml 的数据面
# actions——update_stage/create_case 等——不在此列，仍由 yaml 把数据面写门）
SYSTEM_ROLE_ACTIONS: dict[str, list[str]] = {
    "management": ["dashboard_view", "creator_write", "creator_export",
                   "admin_view", "settlement_view", "case_stage_change"],
    "ae": ["dashboard_view", "creator_write", "creator_export", "case_stage_change"],
    "optimizer": ["dashboard_view", "creator_export"],
    "finance": ["dashboard_view", "settlement_view"],
    "client": ["dashboard_view"],
    "creative": [],
    # 运维：管理与操作类动作全量；业务视图（看板/结算）不放开——与旧散抄集合语义一致
    "admin": ["creator_write", "creator_export", "case_stage_change", "review_resolve",
              "account_manage", "menu_manage", "admin_view"],
}


def ensure_seed(env: dict[str, str], yaml_roles: list[str]) -> None:
    """幂等播种：系统角色行 + 系统 action 集（DB 无记录时才插，不覆盖已调配置）。"""
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        for name in yaml_roles:
            cur.execute(
                "INSERT INTO app_role (name, label, source, base_role, description)"
                " VALUES (%s, %s, 'system', %s, %s) ON CONFLICT (name) DO NOTHING",
                (name, name, name, "系统角色（permissions.yaml）"))
        for name, acts in SYSTEM_ROLE_ACTIONS.items():
            if name not in yaml_roles:
                continue
            cur.execute("SELECT count(*) FROM app_role_action WHERE role = %s", (name,))
            if cur.fetchone()[0]:
                continue
            cur.executemany("INSERT INTO app_role_action (role, action) VALUES (%s, %s)"
                            " ON CONFLICT DO NOTHING", [(name, a) for a in acts])


def roles_of(env: dict[str, str]) -> dict[str, dict]:
    """name → {label, source, base_role, description, actions[]}（含播种）。"""
    yaml_roles = _yaml_role_names()
    ensure_seed(env, yaml_roles)
    with pg_pool.connect(env["ADKG_PG_DSN"], row_factory=dict_row) as c, c.cursor() as cur:
        cur.execute("SELECT name, label, source, base_role, description FROM app_role"
                    " ORDER BY source DESC, name")          # system 在前
        roles = {r["name"]: {**r, "actions": []} for r in cur.fetchall()}
        cur.execute("SELECT role, action FROM app_role_action")
        for r in cur.fetchall():
            roles[r["role"]]["actions"].append(r["action"])
    return roles


def custom_base(env: dict[str, str], role: str) -> str | None:
    """自定义角色 → 基角色（数据面映射用）；系统/未知角色返回 None。"""
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("SELECT base_role FROM app_role WHERE name = %s AND source = 'custom'",
                    (role,))
        row = cur.fetchone()
    return row[0] if row else None


def _yaml_role_names() -> list[str]:
    import yaml as _yaml
    from pathlib import Path
    base = Path(__file__).resolve().parents[2] / "ontology" / "permissions.yaml"
    return list(_yaml.safe_load(base.read_text(encoding="utf-8"))["roles"])


_seeded: set[int] = set()      # 进程内按 env 缓存（幂等播种，避免每请求读 yaml）


def _maybe_seed(env: dict[str, str]) -> None:
    if id(env) in _seeded:
        return
    ensure_seed(env, _yaml_role_names())
    _seeded.add(id(env))


def effective_actions(env: dict[str, str], role: str) -> set[str]:
    """角色有效 action 集（role_allows 与按钮条显隐共同实现，单一来源）：
    自身 app_role_action 记录；自定义角色**零记录**时整体回落基角色（§18 字面
    「无记录回落」= 角色级，非逐 action——逐 action 回落使权限树取消勾选收不回
    权，2026-10-26 夜检修复）。"""
    _maybe_seed(env)
    with pg_pool.connect(env["ADKG_PG_DSN"], row_factory=dict_row) as c, c.cursor() as cur:
        cur.execute("SELECT action FROM app_role_action WHERE role = %s", (role,))
        own = {r["action"] for r in cur.fetchall()}
        if own:
            return own
        base = custom_base(env, role)
        if base and base != role:
            cur.execute("SELECT action FROM app_role_action WHERE role = %s", (base,))
            return {r["action"] for r in cur.fetchall()}
    return own


def role_allows(env: dict[str, str], role: str, gate: str) -> bool:
    """统一角色门：gate ∈ GATES（端点门）或直接是 action 词表键（按钮条，
    spec §18.5——action_key 即 gate）。系统角色按 DB 配置（默认=播种集）；
    自定义角色按 effective_actions（零记录回落基角色）。"""
    return GATES.get(gate, gate) in effective_actions(env, role)


def display_role(request, authorization, role: str | None, user: str | None) -> str:
    """原始角色（含自定义）：菜单/按钮权限按它判——数据面映射前的账号角色。"""
    from adkg.guards.http import resolve_identity
    from adkg.guards.sessions import SESSION_COOKIE, resolve_session
    sess = resolve_session(request.app.state.env,
                           request.cookies.get(SESSION_COOKIE))
    if sess:
        return str(sess["role"])
    r, _u, _p = resolve_identity(request, authorization, role=role, user=user)
    return r


def require(request, authorization, *, gate: str, role: str | None = None,
            user: str | None = None, message: str | None = None) -> str:
    """端点动作门统一入口（读/写同一实现）：以**原始角色**（display_role，含
    自定义）判 role_allows，不过抛 403，通过返回 display_role 供审计落账。

    必须用 display_role 而非 resolve_identity 返回的 role——后者是数据面映射
    后的基角色，直接拿它判门会让 base=admin 的自定义角色绕过自身 action 配置
    获得全部写权（2026-10-26 夜检，require_admin_view 注释自认的坑在此收口）。
    """
    from fastapi import HTTPException
    shown = display_role(request, authorization, role, user)
    if not role_allows(request.app.state.env, shown, gate):
        raise HTTPException(403, message or
                            f"当前角色无「{ACTIONS.get(gate, gate)}」权限（spec §18 角色门）")
    return shown


def require_system_admin(request, authorization, *, role: str | None = None,
                         user: str | None = None) -> str:
    """角色配置写门（§18「写仅 admin」/§19「写权 admin 独占不变」）：系统 admin
    本尊独占——按 display_role 判，自定义角色即便 base=admin 也不得管理角色
    （映射后 role_=='admin' 的旧判法是绕过通道，2026-10-26 夜检修复）。"""
    from fastapi import HTTPException
    shown = display_role(request, authorization, role, user)
    if shown != "admin":
        raise HTTPException(403, "角色配置写操作仅 admin 可用（spec §18/§19）")
    return shown


def require_admin_view(request, authorization, role: str | None,
                       user: str | None = None) -> None:
    """管理区读门（spec §19 收口）：role_allows('admin_view') 统一门——初始语义
    等价 management/admin 可读，自定义角色授 admin_view 后同读。唯一实现委托
    require（display_role 门判）；require 的收口注释同样适用本门。"""
    require(request, authorization, gate="admin_view", role=role, user=user,
            message="无管理后台查看权限（spec §19 admin_view 门）")


# 案例生成 = 内部操作角色（/ingest/case-*、/creative/* 与 agent 工具共用）
CASEGEN_ROLES = {"admin", "management", "optimizer", "ae"}


def can_commit_case(planner, role: str) -> bool:
    """案例提交判定（单一来源）：CASEGEN_ROLES 角色门 + actions 含 create_case
    动作门（§12.4 fail-closed）——/ingest/case-commit 写门与 /agent/chat 下发
    can_commit_case 共用此处，别两处抄（2026-10-27 收口：曾只查角色门，
    optimizer 无 create_case 动作也能 commit；2026-10-28 自 ingest.py 下沉至此
    ——rbac 本就是按钮/数据两套词表的会合点）。"""
    return role in CASEGEN_ROLES and "create_case" in \
        planner.perms["roles"].get(role, {}).get("actions", [])
