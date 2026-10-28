"""POST /actions/check（§9.4 / §十三）：操作裁决——AdKG 是决策点不是执行点。

allow/deny + 约束依据 + audit_id；执行归调用方。
POST /actions/receipt（备忘⑮，2026-10-28 拍板「现在实现」）：执行方回写
结果，补审计链新行引用原 audit_id（audit_log 只追加，不回改原行；
outcome ∈ done/failed/skipped，011 迁移扩 verdict 约束）。
权限前置：op 必须 ∈ 该 role 的 actions（permissions.yaml）。
"""
from __future__ import annotations

import uuid as _uuid

from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.audit import audit
from adkg.guards.http import get_graph, resolve_identity
from adkg.store import pg_pool

router = APIRouter()

_RECEIPT_OUTCOMES = ("done", "failed", "skipped")


@router.post("/actions/check")
def actions_check(request: Request, body: dict,
                  authorization: str | None = Header(default=None)) -> dict:
    env = request.app.state.env
    role, _person, planner = resolve_identity(request, authorization, body=body)

    op = str(body.get("op", ""))
    allowed_actions = planner.perms["roles"].get(role, {}).get("actions", [])
    if op not in allowed_actions:
        verdict = {"decision": "deny",
                   "reason": f"role={role} 无动作 {op}（permissions.yaml#actions）"}
    else:
        from adkg.guards.action_check import ActionChecker
        from adkg.models import load_schema
        graph = get_graph(request)
        verdict = ActionChecker(load_schema(), graph).check(op, body)

    audit_id = audit(env, role, body.get("user"), op, str(body.get("target", "")),
                     verdict["decision"], verdict["reason"],
                     agent_id=body.get("agent_id"))
    out = {**verdict, "audit_id": audit_id}
    if verdict["decision"] == "allow":
        out["note"] = ("AdKG 只裁决不代执行；调用方执行后 POST /actions/receipt "
                       "回传结果（audit_id + outcome），补写审计链（§十三）")
    return out


@router.post("/actions/receipt")
def actions_receipt(request: Request, body: dict,
                    authorization: str | None = Header(default=None)) -> dict:
    """执行回执（§9.4/§十三 两段契约的后半段）：引用原裁决 audit_id 写新行——
    action=action_receipt、target=audit:<原id>、verdict=outcome（done/failed/
    skipped）。任意已存在的审计行可被引用（不限于 /actions/check，阶段流转等
    写操作同样可回执）；审计只追加，回执本身不可再被回执覆盖语义。"""
    env = request.app.state.env
    role, person, _planner = resolve_identity(request, authorization, body=body)
    audit_id = str(body.get("audit_id", "")).strip()
    outcome = str(body.get("outcome", "")).strip()
    note = str(body.get("note", "")).strip()
    if outcome not in _RECEIPT_OUTCOMES:
        raise HTTPException(422, f"outcome 必填 ∈ {_RECEIPT_OUTCOMES}")
    try:
        _uuid.UUID(audit_id)
    except ValueError:
        raise HTTPException(422, "audit_id 必填（/actions/check 等返回的 uuid）")
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("SELECT 1 FROM audit_log WHERE id = %s", (audit_id,))
        if cur.fetchone() is None:
            raise HTTPException(404, f"审计 {audit_id} 不存在")
    rid = audit(env, role, person, "action_receipt", f"audit:{audit_id}",
                outcome, note, agent_id=body.get("agent_id"))
    return {"ok": True, "receipt_audit_id": rid, "linked": audit_id,
            "outcome": outcome}
