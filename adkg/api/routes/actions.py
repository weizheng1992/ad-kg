"""POST /actions/check（§9.4 / §十三）：操作裁决——AdKG 是决策点不是执行点。

allow/deny + 约束依据 + audit_id；执行归调用方，回执回传补写同一条审计。
权限前置：op 必须 ∈ 该 role 的 actions（permissions.yaml）。
"""
from __future__ import annotations

from fastapi import APIRouter, Header, Request

from adkg.guards.audit import audit
from adkg.guards.http import get_graph, resolve_identity

router = APIRouter()


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
        out["note"] = "AdKG 只裁决不代执行；调用方执行后回传结果与平台回执，补写本条审计（§十三）"
    return out
