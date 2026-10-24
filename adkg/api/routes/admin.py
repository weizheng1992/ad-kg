"""GET /admin/*（spec §7 管理后台，只读三件套）：权限矩阵 + 账号一览 + 审计流水。

角色门 ADMIN_ROLES = {management, admin}；本端点零写操作——「最小账号面，
配置即管理」（README §9.7 拍板延续）：账号开户走脚本、权限定义在
permissions.yaml，这里只做可视化与审计查阅。
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request
from psycopg.rows import dict_row

from adkg.guards.http import get_planner, resolve_identity

router = APIRouter()
ADMIN_ROLES = {"management", "admin"}


def _require_admin(role: str) -> None:
    if role not in ADMIN_ROLES:
        raise HTTPException(403, "管理后台仅 management / admin 可用（spec §7）")


@router.get("/admin/permission-matrix")
def permission_matrix(request: Request,
                      role: str | None = None, user: str | None = None,
                      authorization: str | None = Header(default=None)) -> dict:
    role, user, planner = resolve_identity(request, authorization, role=role, user=user)
    _require_admin(role)
    roles = {}
    for name, cfg in planner.perms.get("roles", {}).items():
        roles[name] = {k: cfg.get(k, []) for k in
                       ("classes", "deny_properties", "allow_properties",
                        "metrics_deny", "metrics_allow", "actions")}
        roles[name]["external"] = bool(cfg.get("external"))
        roles[name]["row_filter"] = cfg.get("row_filter", "")
    return {"roles": roles,
            "global_classes": sorted(planner.global_classes)}


@router.get("/admin/accounts")
def accounts(request: Request,
             role: str | None = None, user: str | None = None,
             authorization: str | None = Header(default=None)) -> dict:
    role, user, _planner = resolve_identity(request, authorization, role=role, user=user)
    _require_admin(role)
    with psycopg.connect(request.app.state.env["ADKG_PG_DSN"],
                         row_factory=dict_row) as c, c.cursor() as cur:
        cur.execute("SELECT id, username, display_name, role, person, disabled, "
                    "created_at FROM app_user ORDER BY username")
        rows = cur.fetchall()                     # 无 password_hash——口令哈希不出应用层
    return {"items": [{**r, "created_at": str(r["created_at"])} for r in rows]}


@router.get("/admin/audit")
def audit_log(request: Request, page: int = 1, size: int = 30,
              role: str | None = None, user: str | None = None,
              authorization: str | None = Header(default=None)) -> dict:
    role, user, _planner = resolve_identity(request, authorization, role=role, user=user)
    _require_admin(role)
    size = max(1, min(size, 100))
    page = max(1, page)
    with psycopg.connect(request.app.state.env["ADKG_PG_DSN"],
                         row_factory=dict_row) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) AS total FROM audit_log")
        total = cur.fetchone()["total"]
        cur.execute("SELECT id, ts, user_id, role, agent_id, action, target, verdict, "
                    "reason FROM audit_log ORDER BY ts DESC LIMIT %s OFFSET %s",
                    (size, (page - 1) * size))
        rows = cur.fetchall()
    return {"items": [{**r, "id": str(r["id"]), "ts": str(r["ts"])} for r in rows],
            "total": total, "page": page, "size": size}
