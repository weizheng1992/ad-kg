"""POST /actions/check（§9.4 / §十三）：操作裁决——AdKG 是决策点不是执行点。

allow/deny + 约束依据 + audit_id；执行归调用方，回执回传补写同一条审计。
权限前置：op 必须 ∈ 该 role 的 actions（permissions.yaml）。
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.auth import AuthService
from adkg.guards.permission import load_permissions

router = APIRouter()


@router.post("/actions/check")
def actions_check(request: Request, body: dict,
                  authorization: str | None = Header(default=None)) -> dict:
    env = request.app.state.env
    resolved = AuthService(env).resolve(authorization)
    if resolved:
        role = resolved[0]
    elif env.get("ADKG_DEV_AUTH") == "off" and body.get("role"):
        role = body["role"]                                   # 仅本地开发
    else:
        raise HTTPException(401, "缺有效 service token")

    op = str(body.get("op", ""))
    perms = load_permissions(_perms_path())
    allowed_actions = perms["roles"].get(role, {}).get("actions", [])
    if op not in allowed_actions:
        verdict = {"decision": "deny",
                   "reason": f"role={role} 无动作 {op}（permissions.yaml#actions）"}
    else:
        from adkg.guards.action_check import ActionChecker
        from adkg.models import load_schema
        graph = _graph(request)
        verdict = ActionChecker(load_schema(), graph).check(op, body)

    with psycopg.connect(env["ADKG_PG_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit_log (user_id, role, agent_id, action, target,"
                    " verdict, reason) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (body.get("user"), role, body.get("agent_id"), op,
                     str(body.get("target", ""))[:200], verdict["decision"],
                     verdict["reason"][:500]))
        audit_id = str(cur.fetchone()[0])
    out = {**verdict, "audit_id": audit_id}
    if verdict["decision"] == "allow":
        out["note"] = "AdKG 只裁决不代执行；调用方执行后回传结果与平台回执，补写本条审计（§十三）"
    return out


def _graph(request: Request):
    if not hasattr(request.app.state, "graph"):
        from adkg.store.graph import GraphStore
        env = request.app.state.env
        request.app.state.graph = GraphStore(env["ADKG_NEO4J_URI"], env["ADKG_NEO4J_USER"],
                                             env["ADKG_NEO4J_PASSWORD"])
    return request.app.state.graph


def _perms_path():
    from pathlib import Path
    return Path(__file__).resolve().parents[3] / "ontology" / "permissions.yaml"
