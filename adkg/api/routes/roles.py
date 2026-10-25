"""RBAC 角色管理（spec §18）：创建/配置/删除自定义角色，人员的角色分配。

- 系统角色自 permissions.yaml 播种（source=system）：不可删、base 不可改；
  菜单可见性与按钮权限可调（写 app_menu.roles / app_role_action）。
- 自定义角色：数据面继承基角色（http.resolve_identity 映射），菜单/按钮独立配。
- 人员分配角色：POST /admin/accounts/{uid}/set-role（角色 ∈ app_role 全集）。
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.http import resolve_identity
from adkg.guards.rbac import ACTIONS, ensure_seed, roles_of

router = APIRouter()


def _require(env, role: str, gate: str) -> None:
    from adkg.guards.rbac import role_allows
    if not role_allows(env, role, gate):
        raise HTTPException(403, "当前角色无此管理权限（spec §18）")


def _require_admin_view(role: str) -> None:
    if role not in {"management", "admin"}:
        raise HTTPException(403, "管理后台仅 management / admin 可用（spec §7）")


@router.get("/admin/roles")
def list_roles(request: Request,
               role: str | None = None, user: str | None = None,
               authorization: str | None = Header(default=None)) -> dict:
    """角色全集（系统 + 自定义）+ 各自按钮权限 + 占用账号数。"""
    role_, user_, _planner = resolve_identity(request, authorization, role=role, user=user)
    _require_admin_view(role_)
    env = request.app.state.env
    roles = roles_of(env)
    with psycopg.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("SELECT role, count(*) FROM app_user WHERE NOT disabled"
                    " GROUP BY role")
        used = dict(cur.fetchall())
    return {"items": [{**r, "used": used.get(name, 0), "actions_all": ACTIONS}
                      for name, r in sorted(roles.items(),
                                            key=lambda kv: (kv[1]["source"] != "system",
                                                            kv[0]))]}


@router.post("/admin/roles")
def create_role(request: Request, body: dict,
                role: str | None = None, user: str | None = None,
                authorization: str | None = Header(default=None)) -> dict:
    """创建自定义角色（spec §18）：name 唯一；base ∈ 系统角色（数据面继承）。"""
    role_, person, _planner = resolve_identity(request, authorization, role=role, user=user)
    _require_admin_view(role_)
    if role_ != "admin":
        # 写门收紧到 admin：防越权造角色给自己放行
        raise HTTPException(403, "角色创建仅 admin 可用（spec §18）")
    env = request.app.state.env
    import re
    name = str(body.get("name") or "").strip()
    label = str(body.get("label") or "").strip() or name
    base_role = str(body.get("base_role") or "").strip()
    description = str(body.get("description") or "").strip()
    actions = [a for a in (body.get("actions") or []) if a in ACTIONS]
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", name or ""):
        raise HTTPException(422, "角色名：小写字母开头的字母/数字/下划线，2-31 位")
    existing = roles_of(env)
    if name in existing:
        raise HTTPException(409, f"角色 {name} 已存在")
    if base_role not in existing or existing[base_role]["source"] != "system":
        raise HTTPException(422, f"base_role 必须是系统角色：{base_role}")
    from adkg.guards.audit import audit
    with psycopg.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("INSERT INTO app_role (name, label, source, base_role, description)"
                    " VALUES (%s, %s, 'custom', %s, %s)", (name, label, base_role, description))
        cur.executemany("INSERT INTO app_role_action (role, action) VALUES (%s, %s)",
                        [(name, a) for a in actions])
    audit(env, role_, person, "create_role", name, "allow",
          f"base={base_role}, actions={len(actions)}")
    return {"ok": True, "name": name}


@router.put("/admin/roles/{name}")
def update_role(request: Request, name: str, body: dict,
                role: str | None = None, user: str | None = None,
                authorization: str | None = Header(default=None)) -> dict:
    """更新角色：label/description/按钮权限；系统角色 base 不可改、不可摘 admin 自留权。"""
    role_, person, _planner = resolve_identity(request, authorization, role=role, user=user)
    _require_admin_view(role_)
    env = request.app.state.env
    existing = roles_of(env)
    if name not in existing:
        raise HTTPException(404, f"角色 {name} 不存在")
    is_admin_editing = role_ == "admin"
    if not is_admin_editing:
        raise HTTPException(403, "角色配置写操作仅 admin 可用（spec §18）")
    actions = [a for a in (body.get("actions") or []) if a in ACTIONS]
    if existing[name]["source"] == "custom" and body.get("base_role"):
        new_base = str(body["base_role"])
        if new_base in existing and existing[new_base]["source"] == "system" \
                and new_base != name:
            with psycopg.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
                cur.execute("UPDATE app_role SET base_role = %s WHERE name = %s",
                            (new_base, name))
    from adkg.guards.audit import audit
    with psycopg.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("UPDATE app_role SET label = %s, description = %s WHERE name = %s",
                    (str(body.get("label") or existing[name]["label"]),
                     str(body.get("description") or existing[name]["description"]), name))
        cur.execute("DELETE FROM app_role_action WHERE role = %s", (name,))
        cur.executemany("INSERT INTO app_role_action (role, action) VALUES (%s, %s)",
                        [(name, a) for a in actions])
    audit(env, role_, person, "update_role", name, "allow", f"actions={len(actions)}")
    return {"ok": True}


@router.delete("/admin/roles/{name}")
def delete_role(request: Request, name: str,
                role: str | None = None, user: str | None = None,
                authorization: str | None = Header(default=None)) -> dict:
    role_, person, _planner = resolve_identity(request, authorization, role=role, user=user)
    if role_ != "admin":
        raise HTTPException(403, "角色删除仅 admin 可用（spec §18）")
    env = request.app.state.env
    existing = roles_of(env)
    if name not in existing:
        raise HTTPException(404, f"角色 {name} 不存在")
    if existing[name]["source"] == "system":
        raise HTTPException(422, "系统角色不可删（数据面定义在 permissions.yaml）")
    with psycopg.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM app_user WHERE role = %s", (name,))
        if cur.fetchone()[0]:
            raise HTTPException(409, "仍有账号占用该角色（先在人员管理改绑）")
        cur.execute("DELETE FROM app_role WHERE name = %s", (name,))
    from adkg.guards.audit import audit
    audit(env, role_, person, "delete_role", name, "allow", "自定义角色删除")
    return {"ok": True}


@router.post("/admin/accounts/{uid}/set-role")
def set_account_role(request: Request, uid: str, body: dict,
                     role: str | None = None, user: str | None = None,
                     authorization: str | None = Header(default=None)) -> dict:
    """人员分配角色（spec §18）：角色 ∈ app_role 全集（系统 + 自定义）。"""
    role_, person, _planner = resolve_identity(request, authorization, role=role, user=user)
    env = request.app.state.env
    from adkg.guards.rbac import role_allows
    if not role_allows(env, role_, "account_write"):
        raise HTTPException(403, "人员管理写操作仅 admin 可用（spec §18）")
    new_role = str(body.get("role") or "").strip()
    roles = roles_of(env)
    if new_role not in roles:
        raise HTTPException(422, f"未知角色：{new_role}")
    from adkg.guards.audit import audit
    with psycopg.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        n = cur.execute("UPDATE app_user SET role = %s WHERE id = %s RETURNING username",
                        (new_role, uid)).fetchall()
        if not n:
            raise HTTPException(404, f"账号 {uid} 不存在")
        cur.execute("DELETE FROM app_session WHERE user_id = %s", (uid,))   # 换角色即换会话
    audit(env, role_, person, "set_account_role", n[0][0], "allow", f"→ {new_role}")
    return {"ok": True, "role": new_role}


@router.get("/my-actions")
def my_actions(request: Request,
               role: str | None = None, user: str | None = None,
               authorization: str | None = Header(default=None)) -> dict:
    """当前登录的按钮权限（spec §18 前端按钮显隐）——账号原始角色（含自定义）。"""
    from adkg.guards.rbac import display_role
    shown = display_role(request, authorization, role, user)
    roles = roles_of(request.app.state.env)      # 内部幂等播种
    info = roles.get(shown)
    return {"role": shown,
            "actions": info["actions"] if info else [],
            "is_custom": bool(info and info["source"] == "custom"),
            "base_role": info["base_role"] if info else None}
