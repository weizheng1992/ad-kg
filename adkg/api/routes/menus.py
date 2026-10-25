"""侧边栏菜单（spec §17 菜单管理）：数据驱动——admin 可调可见角色/排序/改名/启停。

- path 与 icon 白名单锁定（对应真实路由与前端图标集），不开放增删——凭空造
  菜单项只会指向 404；可见性是导航体验层，真正的权限闸在各后端端点。
- 首访懒播种默认（DEFAULT_MENUS = §4 导航矩阵）；GET /menus 按当前角色过滤。
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request
from psycopg.rows import dict_row

from adkg.guards.http import resolve_identity

router = APIRouter()

# 菜单树（spec §18.5）：页面条 (path, label, icon, roles, sort) + 按钮条
# (path="page#action", parent=页面, type=button, action_key)。
# 按钮可见性 = 角色是否持有该 action（app_role_action），页面可见性走 roles。
DEFAULT_MENUS: list[tuple[str, str, str, str, int]] = [
    ("/", "数据看板", "LayoutDashboard", "management,ae,optimizer,finance,client", 10),
    ("/creators", "达人库", "Users", "management,ae,optimizer,finance", 20),
    ("/cases", "案例", "Briefcase", "management,ae,optimizer,client", 30),
    ("/platform", "数据平台(模拟)", "BarChart3", "management,ae,optimizer", 40),
    ("/brands", "客户", "Building2", "management,ae,client", 50),
    ("/settlements", "财务结算", "Wallet", "management,finance", 60),
    ("/graph", "图谱", "Network", "management,ae,optimizer,creative", 70),
    ("/admin", "管理后台", "ShieldCheck", "management,admin", 80),
    ("/people", "人员管理", "UserCog", "management,admin", 90),
    ("/permissions", "权限管理", "KeyRound", "management,admin", 100),
    ("/menus", "菜单管理", "Menu", "admin", 110),
]
# 按钮（页面, action_key, label, sort）
DEFAULT_BUTTONS: list[tuple[str, str, str, int]] = [
    ("/creators", "creator_write", "录入 / 导入", 10),
    ("/creators", "creator_export", "导出", 20),
    ("/cases", "case_stage_change", "阶段变更", 10),
    ("/settlements", "settlement_view", "结算明细", 10),
    ("/admin", "review_resolve", "人审处置", 10),
    ("/admin", "admin_view", "审计查看", 20),
    ("/people", "account_manage", "人员写操作", 10),
    ("/menus", "menu_manage", "菜单写操作", 10),
]
_PATHS = {m[0] for m in DEFAULT_MENUS} | {b[0] + "#" + b[1] for b in DEFAULT_BUTTONS}
_ICONS = {m[2] for m in DEFAULT_MENUS} | {b[0] + "#" + b[1] for b in DEFAULT_BUTTONS}


def _ensure_seed(env: dict[str, str]) -> None:
    with psycopg.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) FROM app_menu WHERE type = 'page'")
        if cur.fetchone()[0] < len(DEFAULT_MENUS):
            cur.executemany(
                "INSERT INTO app_menu (path, label, icon, roles, sort, type)"
                " VALUES (%s, %s, %s, %s, %s, 'page')"
                " ON CONFLICT (path) DO NOTHING", DEFAULT_MENUS)
        cur.executemany(
            "INSERT INTO app_menu (path, label, icon, roles, sort, type, parent,"
            " action_key) VALUES (%s, '按钮', 'Menu', '', %s + 1, 'button', %s, %s)"
            " ON CONFLICT (path) DO NOTHING",
            [(f"{page}#{action}", sort, page, action)
             for page, action, label, sort in DEFAULT_BUTTONS])


def _items(env: dict[str, str]) -> list[dict]:
    _ensure_seed(env)
    with psycopg.connect(env["ADKG_PG_DSN"], row_factory=dict_row) as c, c.cursor() as cur:
        cur.execute("SELECT path, label, icon, roles, sort, enabled, type, parent,"
                    " action_key FROM app_menu ORDER BY sort")
        return [{"path": r["path"], "label": r["label"], "icon": r["icon"],
                 "roles": r["roles"].split(","), "sort": r["sort"],
                 "enabled": r["enabled"], "type": r["type"],
                 "parent": r["parent"], "action_key": r["action_key"]}
                for r in cur.fetchall()]


@router.get("/menus")
def menus(request: Request, role: str | None = None, user: str | None = None,
          authorization: str | None = Header(default=None)) -> dict:
    """当前角色可见的启用菜单（按账号原始角色——自定义角色见自己的菜单；
    前端失败时回落静态默认，导航不中断）。"""
    from adkg.guards.rbac import display_role
    role_, _user, _planner = resolve_identity(request, authorization, role=role, user=user)
    shown = display_role(request, authorization, role, user)
    from adkg.guards.rbac import role_allows
    items = []
    for m in _items(request.app.state.env):
        if not m["enabled"]:
            continue
        if m["type"] == "page":
            if shown in m["roles"]:
                items.append(m)
        else:                                   # 按钮条：按 action 门
            if m["action_key"] and role_allows(request.app.state.env, shown,
                                               m["action_key"]):
                items.append(m)
    return {"items": items, "role": shown}


@router.get("/admin/menus")
def admin_menus(request: Request, role: str | None = None, user: str | None = None,
                authorization: str | None = Header(default=None)) -> dict:
    role_, _user, _planner = resolve_identity(request, authorization, role=role, user=user)
    from adkg.guards.rbac import role_allows
    if not role_allows(request.app.state.env, role_, "menu_write"):
        raise HTTPException(403, "当前角色无菜单管理权限（spec §18 角色门）")
    return {"items": _items(request.app.state.env)}


@router.put("/admin/menus")
def save_menus(request: Request, body: dict,
               role: str | None = None, user: str | None = None,
               authorization: str | None = Header(default=None)) -> dict:
    """整批保存（spec §17）：label/roles/sort/enabled 可改；path/icon 白名单锁定，
    不开放增删；至少保住 /menus 自身对 admin 可见（防自锁）。"""
    role_, person, _planner = resolve_identity(request, authorization, role=role, user=user)
    from adkg.guards.rbac import role_allows
    if not role_allows(request.app.state.env, role_, "menu_write"):
        raise HTTPException(403, "当前角色无菜单管理权限（spec §18 角色门）")
    items = body.get("items")
    if not isinstance(items, list):
        raise HTTPException(422, "items 必填")
    from adkg.guards.audit import audit
    from adkg.guards.rbac import roles_of
    legal_roles = set(roles_of(request.app.state.env))   # RBAC 全集（系统+自定义）
    cleaned = []
    for m in items:
        path, icon = str(m.get("path") or ""), str(m.get("icon") or "")
        if path not in _PATHS or icon not in _ICONS:
            raise HTTPException(422, f"非法菜单项：{path}（path/icon 白名单锁定）")
        is_button = "#" in path
        if is_button:                           # 按钮条：可见性=action 门，不存 roles
            cleaned.append((str(m.get("label") or path).strip()[:20] or path, path, icon,
                            "", int(m.get("sort") or 0), bool(m.get("enabled"))))
            continue
        roles = [r for r in (m.get("roles") or []) if r in legal_roles]
        if not roles:
            raise HTTPException(422, f"{path} 至少保留一个可见角色")
        cleaned.append((str(m.get("label") or path).strip()[:20] or path, path, icon,
                        ",".join(roles), int(m.get("sort") or 0), bool(m.get("enabled"))))
    # 防自锁：/menus 必须对 admin 可见且启用
    menus_row = next((c for c in cleaned if c[1] == "/menus"), None)
    if menus_row is None or not menus_row[5] or "admin" not in menus_row[3].split(","):
        raise HTTPException(422, "/menus 自身必须对 admin 可见且启用（防自锁）")
    env = request.app.state.env
    with psycopg.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        for label, path, icon, roles, sort, enabled in cleaned:
            cur.execute("UPDATE app_menu SET label=%s, roles=%s, sort=%s,"
                        " enabled=%s, updated_at=now() WHERE path=%s",
                        (label, roles, sort, enabled, path))
    audit(env, role_, person, "save_menus", "app_menu", "allow",
          f"{len(cleaned)} 项整批更新")
    return {"ok": True, "count": len(cleaned)}
