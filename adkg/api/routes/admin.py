"""GET /admin/*（spec §7 管理后台，只读三件套）：权限矩阵 + 账号一览 + 审计流水。

读门收口（spec §19）：读端点统一走 role_allows('admin_view')——与词表 / 播种 /
GATES 同源，初始语义等价 management/admin 可读，自定义角色授 admin_view 后同样
可读；写端点门 2026-10-26 起同走 require()（display_role 判 action）——原
ADMIN_ROLES 预检 + 基角色 action 门会让 base=admin 的自定义角色绕过自身配置
获得全部写权（夜检 RBAC 三缺陷之一），ADMIN_ROLES 硬门随之废除。
"""
from __future__ import annotations

import psycopg

from adkg.store import pg_pool
from fastapi import APIRouter, Header, HTTPException, Request
from psycopg.rows import dict_row

from adkg.guards.http import get_graph, get_planner, resolve_identity
from adkg.guards.rbac import require, require_admin_view   # 门唯一实现（spec §19 收口）

router = APIRouter()


@router.get("/admin/permission-matrix")
def permission_matrix(request: Request,
                      role: str | None = None, user: str | None = None,
                      authorization: str | None = Header(default=None)) -> dict:
    role_, _u, planner = resolve_identity(request, authorization, role=role, user=user)
    require_admin_view(request, authorization, role, user)
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
    role_, user_, _planner = resolve_identity(request, authorization, role=role, user=user)
    require_admin_view(request, authorization, role, user)
    with pg_pool.connect(request.app.state.env["ADKG_PG_DSN"],
                         row_factory=dict_row) as c, c.cursor() as cur:
        cur.execute("SELECT id, username, display_name, role, person, disabled, "
                    "created_at FROM app_user ORDER BY username")
        rows = cur.fetchall()                     # 无 password_hash——口令哈希不出应用层
    return {"items": [{**r, "created_at": str(r["created_at"])} for r in rows]}


@router.post("/admin/accounts")
def create_account(request: Request, body: dict,
                   role: str | None = None, user: str | None = None,
                   authorization: str | None = Header(default=None)) -> dict:
    """开户（spec §16 人员管理）：role 过 permissions.yaml 合法集；门判 display_role。"""
    role_, person, planner = resolve_identity(request, authorization, role=role, user=user)
    shown = require(request, authorization, gate="account_write", role=role, user=user)
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    display_name = str(body.get("display_name") or "").strip() or username
    new_role = str(body.get("role") or "").strip()
    bind_person = str(body.get("person") or "").strip() or None
    if not username or not password:
        raise HTTPException(422, "username 与 password 必填")
    from adkg.guards.rbac import roles_of
    if new_role not in roles_of(request.app.state.env):     # RBAC 全集（系统+自定义）
        raise HTTPException(422, f"未知角色：{new_role}")
    import psycopg as _p
    from adkg.guards.audit import audit
    from adkg.guards.passwords import hash_password
    env = request.app.state.env
    try:
        with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
            cur.execute("INSERT INTO app_user (id, username, password_hash, display_name,"
                        " role, person) VALUES (%s, %s, %s, %s, %s, %s)",
                        (f"u_{username}", username, hash_password(password),
                         display_name, new_role, bind_person))
    except _p.errors.UniqueViolation:
        raise HTTPException(409, f"账号 {username} 已存在") from None
    audit(env, shown, person, "create_account", username, "allow", f"role={new_role}")
    return {"ok": True, "username": username}


@router.post("/admin/accounts/{uid}/reset-password")
def reset_password(request: Request, uid: str, body: dict,
                   role: str | None = None, user: str | None = None,
                   authorization: str | None = Header(default=None)) -> dict:
    role_, person, _planner = resolve_identity(request, authorization, role=role, user=user)
    shown = require(request, authorization, gate="account_write", role=role, user=user)
    password = str(body.get("password") or "")
    if not password:
        raise HTTPException(422, "password 必填")
    from adkg.guards.audit import audit
    from adkg.guards.passwords import hash_password
    env = request.app.state.env
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        n = cur.execute("UPDATE app_user SET password_hash = %s WHERE id = %s"
                        " RETURNING username", (hash_password(password), uid)).fetchall()
        if not n:
            raise HTTPException(404, f"账号 {uid} 不存在")
        cur.execute("DELETE FROM app_session WHERE user_id = %s", (uid,))   # 旧会话全吊销
    audit(env, shown, person, "reset_password", n[0][0], "allow", "改密并吊销既有会话")
    return {"ok": True}


@router.post("/admin/accounts/{uid}/toggle")
def toggle_account(request: Request, uid: str, body: dict,
                   role: str | None = None, user: str | None = None,
                   authorization: str | None = Header(default=None)) -> dict:
    role_, person, _planner = resolve_identity(request, authorization, role=role, user=user)
    shown = require(request, authorization, gate="account_write", role=role, user=user)
    disabled = bool(body.get("disabled"))
    from adkg.guards.audit import audit
    env = request.app.state.env
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        n = cur.execute("UPDATE app_user SET disabled = %s WHERE id = %s"
                        " RETURNING username", (disabled, uid)).fetchall()
        if not n:
            raise HTTPException(404, f"账号 {uid} 不存在")
        if disabled:
            cur.execute("DELETE FROM app_session WHERE user_id = %s", (uid,))
    audit(env, shown, person, "toggle_account", n[0][0], "allow",
          "停用并吊销会话" if disabled else "启用")
    return {"ok": True, "disabled": disabled}


@router.get("/admin/audit")
def audit_log(request: Request, page: int = 1, size: int = 30,
              action: str = "", verdict: str = "", by_role: str = "", q: str = "",
              role: str | None = None, user: str | None = None,
              authorization: str | None = Header(default=None)) -> dict:
    """审计流水（spec §14 增筛选）：action / verdict / by_role / 对象包含。"""
    role_, user, _planner = resolve_identity(request, authorization, role=role, user=user)
    require_admin_view(request, authorization, role, user)
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
    with pg_pool.connect(request.app.state.env["ADKG_PG_DSN"],
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
    require_admin_view(request, authorization, role, user)
    status = status if status in ("open", "approved", "rejected") else "open"
    conds, args = ["status = %(status)s"], {"status": status}
    if kind.strip():
        conds.append("kind = %(kind)s"); args["kind"] = kind.strip()
    where = " WHERE " + " AND ".join(conds)
    with pg_pool.connect(request.app.state.env["ADKG_PG_DSN"],
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


@router.post("/admin/review-queue/{qid}/resolve")
def resolve_review(request: Request, qid: str, body: dict,
                   role: str | None = None, user: str | None = None,
                   authorization: str | None = Header(default=None)) -> dict:
    """人审处置（spec §15）：approve 对 conflict 把 incoming_props 落图（进源
    provenance，人审背书）；其余 kind / reject 仅状态流转；双落审计 + resolved_by。
    读改同一连接同一事务：FOR UPDATE 锁行串行化并发处置，UPDATE 带 open 守卫
    （0 行 → 409 已被处置）；先占状态流转再落图，图写失败事务回滚条目回 open。
    """
    role, person, _planner = resolve_identity(request, authorization, role=role, user=user)
    shown = require(request, authorization, gate="review_resolve", role=role, user=user)
    decision = str(body.get("decision") or "")
    note = str(body.get("note") or "").strip()
    if decision not in ("approved", "rejected"):
        raise HTTPException(422, "decision 只能是 approved / rejected")
    env = request.app.state.env
    from psycopg.types.json import Json
    applied = False
    with pg_pool.connect(env["ADKG_PG_DSN"], row_factory=dict_row) as c, c.cursor() as cur:
        cur.execute("SELECT id, kind, payload FROM review_queue"
                    " WHERE id = %(id)s FOR UPDATE", {"id": qid})
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "条目不存在")
        payload = row["payload"] or {}
        cur.execute("UPDATE review_queue SET status = %s, resolved_at = now(),"
                    " resolved_by = %s, payload = payload || %s::jsonb"
                    " WHERE id = %s AND status = 'open'",
                    (decision, person or role,
                     Json({"resolution_note": note}), qid))
        if cur.rowcount == 0:      # open 守卫拦下并发/重复处置（替代先读后判）
            raise HTTPException(409, "条目已被处置")
        if decision == "approved" and row["kind"] == "conflict" and (
                payload.get("incoming_props") or payload.get("field_diff")):
            # 采纳进源数据（人审背书）：incoming 来源 provenance 原样落图——
            # 字段级仲裁载荷（2026-10-25）：空缺 filled + 冲突 field_diff 的 incoming 值
            from datetime import datetime, timezone

            from adkg.models import Entity, Provenance
            src_id = str(payload.get("incoming_source") or "review:resolve")
            # source_type 优先入队时补记的 incoming_source_type（spec §15）；
            # 前缀猜测只兜未补记该字段的旧条目
            src_type = str(payload.get("incoming_source_type") or
                           ("platform_api" if src_id.startswith("mock-douyin")
                            else "conversation"))
            props = dict(payload.get("incoming_props") or {})
            props.update(payload.get("filled") or {})
            props.update({k: v["incoming"] for k, v in
                          (payload.get("field_diff") or {}).items()})
            get_graph(request).upsert_entities([Entity(
                entity_class=str(payload.get("entity", "")).split(":", 1)[0] or "Creator",
                entity_id=str(payload["entity"]),
                props=props,
                provenance=Provenance(                     # type: ignore[arg-type]
                    source_type=src_type, source_id=src_id,
                    fetched_at=datetime.now(timezone.utc)))])
            if str(payload["entity"]).startswith("Creator:"):
                from adkg.store.creator_quotes import record_quote_history
                record_quote_history(env, str(payload["entity"]), props.get("quote_20s"),
                                     src_type, src_id)      # 采纳即留痕（§15）
            applied = True
    from adkg.guards.audit import audit
    audit(env, shown, person, "review_resolve", str(payload.get("entity") or qid),
          "allow" if decision == "approved" else "filtered",
          f"{row['kind']} → {decision}" + (f"（{note}）" if note else "")
          + ("；进源数据已落图" if applied else ""))
    return {"ok": True, "id": qid, "decision": decision, "applied": applied}
