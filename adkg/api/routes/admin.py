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
              action: str = "", verdict: str = "", by_role: str = "", q: str = "",
              role: str | None = None, user: str | None = None,
              authorization: str | None = Header(default=None)) -> dict:
    """审计流水（spec §14 增筛选）：action / verdict / by_role / 对象包含。"""
    role_, user, _planner = resolve_identity(request, authorization, role=role, user=user)
    _require_admin(role_)
    size = max(1, min(size, 100))
    page = max(1, page)
    conds, args = [], {"size": size, "offset": (page - 1) * size}
    if action.strip():
        conds.append("action = %(action)s"); args["action"] = action.strip()
    if verdict.strip():
        conds.append("verdict = %(verdict)s"); args["verdict"] = verdict.strip()
    if by_role.strip():
        conds.append("role = %(by_role)s"); args["by_role"] = by_role.strip()
    if q.strip():
        conds.append("target ILIKE %(q)s"); args["q"] = f"%{q.strip()}%"
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with psycopg.connect(request.app.state.env["ADKG_PG_DSN"],
                         row_factory=dict_row) as c, c.cursor() as cur:
        cur.execute("SELECT count(*) AS total FROM audit_log" + where, args)
        total = cur.fetchone()["total"]
        cur.execute("SELECT id, ts, user_id, role, agent_id, action, target, verdict, "
                    "reason FROM audit_log" + where +
                    " ORDER BY ts DESC LIMIT %(size)s OFFSET %(offset)s", args)
        rows = cur.fetchall()
    return {"items": [{**r, "id": str(r["id"]), "ts": str(r["ts"])} for r in rows],
            "total": total, "page": page, "size": size}


@router.get("/admin/review-queue")
def review_queue(request: Request, status: str = "open", kind: str = "",
                 role: str | None = None, user: str | None = None,
                 authorization: str | None = Header(default=None)) -> dict:
    """人审队列只读（spec §14）：权威仲裁的冲突真实在写入，必须可见；
    附同状态各 kind 计数（low_confidence/reconcile/unmatched/conflict 各有来源）；
    处置 approve/reject 留后置（§9.7 人审操作台）。"""
    role_, user, _planner = resolve_identity(request, authorization, role=role, user=user)
    _require_admin(role_)
    status = status if status in ("open", "approved", "rejected") else "open"
    conds, args = ["status = %(status)s"], {"status": status}
    if kind.strip():
        conds.append("kind = %(kind)s"); args["kind"] = kind.strip()
    where = " WHERE " + " AND ".join(conds)
    with psycopg.connect(request.app.state.env["ADKG_PG_DSN"],
                         row_factory=dict_row) as c, c.cursor() as cur:
        cur.execute("SELECT kind, count(*) AS n FROM review_queue"
                    " WHERE status = %(status)s GROUP BY kind", {"status": status})
        kinds = {r["kind"]: r["n"] for r in cur.fetchall()}
        cur.execute("SELECT id, kind, payload, status, created_at, resolved_at, resolved_by"
                    " FROM review_queue" + where +
                    " ORDER BY created_at DESC LIMIT 100", args)
        rows = cur.fetchall()
    return {"items": [{**r, "id": str(r["id"]), "created_at": str(r["created_at"]),
                       "payload": r["payload"]} for r in rows],
            "total": len(rows), "kinds": kinds}
