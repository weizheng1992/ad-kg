"""POST /ask（§7.2 使用链路 / §9.4 响应契约）。

链路：认证（token→role，dev 模式 body 兜底）→ PermissionPlan → router →
按 RouterPlan 步序执行三路（依赖已由模型校验指向更早步骤，按序即满足）→
assemble → audit（/ask 按次入审计，§12.4）。
只收查询类；操作类意图返回 /actions/check 指引（§7.3）。
"""
from __future__ import annotations

import psycopg

from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.auth import AuthService
from adkg.guards.permission import PermissionPlanner
from adkg.retrieval import graph_search, text2sql, vector_search
from adkg.retrieval.assemble import assemble
from adkg.retrieval.router import llm_route, rule_route

router = APIRouter()


def _planner(request: Request) -> PermissionPlanner:
    if not hasattr(request.app.state, "planner"):
        from pathlib import Path

        from adkg.store.graph import GraphStore
        env = request.app.state.env
        graph = GraphStore(env["ADKG_NEO4J_URI"], env["ADKG_NEO4J_USER"],
                           env["ADKG_NEO4J_PASSWORD"])
        request.app.state.planner = PermissionPlanner(
            Path(__file__).resolve().parents[3] / "ontology" / "permissions.yaml",
            graph=graph)
    return request.app.state.planner


def _graph(request: Request):
    _planner(request)
    return request.app.state.planner._graph


def _llm(request: Request):
    """惰性 LLM 客户端；chat 不可用（无 key/网络）返回 None 走降级。"""
    if not hasattr(request.app.state, "llm"):
        request.app.state.llm = None
        if request.app.state.env.get("ADKG_LLM_API_KEY"):
            try:
                from adkg.llm import LLMClient
                client = LLMClient()
                client.chat_json("ping", '返回 {"ok": true}')
                request.app.state.llm = client
            except Exception:
                request.app.state.llm = None
    return request.app.state.llm


@router.post("/ask")
def ask(request: Request, body: dict,
        authorization: str | None = Header(default=None)) -> dict:
    env = request.app.state.env
    dev_auth_off = env.get("ADKG_DEV_AUTH") == "off"

    resolved = AuthService(env).resolve(authorization)
    if resolved:
        role, _person = resolved
        person = body.get("user")
    elif dev_auth_off and body.get("role"):
        role, person = body["role"], body.get("user")       # 仅本地开发（§9.1）
    else:
        raise HTTPException(401, "缺有效 service token（生产经网关注入；本地 ADKG_DEV_AUTH=off 可 body 传 role）")

    question = str(body.get("question", "")).strip()
    if not question:
        raise HTTPException(422, "question 不能为空")

    planner = _planner(request)
    plan = planner.plan(role, person=person)
    llm = _llm(request)
    if llm is not None:                                   # LLM 路由优先，异常回规则（§7.2）
        try:
            decision = llm_route(question, llm.chat_json)
        except Exception:
            decision = rule_route(question)
    else:
        decision = rule_route(question)

    if decision.intent == "operation":                      # 不进 /ask（§7.3）
        _audit(env, role, person, question, "info", "operation 意图，返回端点指引")
        return {"action": "guidance", "intent": "operation",
                "endpoint": "/actions/check",
                "reason": "操作类请求请直接调用 /actions/check 做裁决（AdKG 只裁决不代执行）"}

    graph = _graph(request)
    results: dict[str, dict] = {}
    for step in decision.plan.steps:                        # 按序执行即满足依赖
        if step.route.value == "graph":
            r = graph_search.search(question, plan, graph)
        elif step.route.value == "text2sql":
            dep = step.params.get("entity_ids_from")
            entity_ids = results.get(dep, {}).get("entity_ids") if dep else None
            r = text2sql.run(question, plan, env["ADKG_PG_RO_DSN"], entity_ids)
        else:
            r = vector_search.search(question, plan, env["ADKG_PG_DSN"],
                                     embed_fn=llm.embed if llm else None)
        results[step.step_id] = {"route": step.route.value, "confidence": step.confidence, **r}

    person_names = None
    if plan.mask_rules:
        with graph.session() as s:                          # 脱敏出口需要人名表（§12.6）
            person_names = [r["n"] for r in s.run(
                "MATCH (p:Entity) WHERE p.class='Person' RETURN p.name AS n").data()]
    out = assemble(results, plan, decision, person_names=person_names)
    _audit(env, role, person, question, "info", f"intent={decision.intent}")
    return {"answer": _summarize(question, out, decision), **out}


def _summarize(question: str, out: dict, decision) -> str:
    """v1 模板摘要；生成式回答在 LLM key 就绪后接入（同一次路由结构）。"""
    n = len(out["evidence"])
    routes = "、".join(r["route"] for r in out["routes_used"])
    tail = f"（缺席路：{'、'.join(out['degraded'])}）" if out["degraded"] else ""
    return f"[{decision.intent}] 命中 {n} 条证据（{routes} 路）{tail}——依据见 evidence，每条带 provenance。"


def _audit(env: dict, role: str, person: str | None, question: str,
           verdict: str, reason: str) -> None:
    with psycopg.connect(env["ADKG_PG_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit_log (user_id, role, action, target, verdict, reason)"
                    " VALUES (%s,%s,'ask',%s,%s,%s)",
                    (person, role, question[:200], verdict, reason))
