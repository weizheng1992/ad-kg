"""POST /agent/chat（§9.7「Agent 对话」）：对话式 agent——ReAct 循环 + 只读工具。

- 纯 JSON 契约（不赌端点的 function-calling）：模型每轮输出
  {"action": 工具名, "args": {...}} 或 {"final": {...}}，循环 ≤5 轮
- 工具全只读且过 PermissionPlan（§12.4），结果带 provenance 可溯源
- 产出的 case_draft 不直接入图：由 materialize_draft 在服务端对齐/建号成标准草稿，
  前端确认后仍走 /ingest/case-commit 服务端重校验——铁律不因 agent 而绕过
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.auth import AuthService

router = APIRouter()

MAX_TURNS = 5

_AGENT_SYSTEM = (
    "你是 AdKG 知识中台的助手：既能回答知识问题（问答），也能把已入库知识变成案例/素材草稿（生成）。"
    "每轮只输出 JSON，二选一——"
    '需要更多信息：{"action": "工具名", "args": {...}}；'
    '信息足够：{"final": {"answer": "给用户的说明", '
    '"case_seed": {"brand_name", "product_names": [], "case_name"?, "stage"?, "doc_id"?, "person_ids": []} 或 null, '
    '"creative_drafts": [{"title","format","platform","hook_3s","script","copy"}] 或 null}}。'
    "工具（全部只读）："
    'ask_knowledge {"question"} → 知识问答（指标/排名/归因/关系类问题，走三路检索管线）；'
    'list_brands {} → 品牌与类目；'
    'search_product_knowledge {"query"} → 已入库文档的商品知识（卖点/售后/尺码）；'
    'search_best_creatives {"brand_id", "n"} → 同类目最好案例素材（CPA 口径）；'
    'get_guidelines {} → 创意规范与机判阈值；'
    'list_synced_docs {"q"} → 已同步飞书文档（生成案例的素材源）。'
    "规矩：事实/排名/归因类问题直接调 ask_knowledge，一次调用即完整转述答案（保留数字与结论），"
    "不要重复调用；不知道就先调工具查，禁止编造实体、卖点与数据；"
    "person_ids 只能用工具结果里见到的真实 id（未对齐不入图）；"
    "creative hook_3s 必须满足规范阈值，卖点只能来自 search_product_knowledge；"
    "answer 里说明依据了哪些工具结果；一次 final 可以同时带问答要点、案例种子与素材草稿。"
)


@router.post("/agent/chat")
def agent_chat(request: Request, body: dict,
               authorization: str | None = Header(default=None)) -> dict:
    env = request.app.state.env
    resolved = AuthService(env).resolve(authorization)
    if resolved:
        role, person = resolved[0], body.get("user") or resolved[1]
    elif env.get("ADKG_DEV_AUTH") == "off" and body.get("role"):
        role, person = body["role"], body.get("user")
    else:
        raise HTTPException(401, "缺有效 service token（本地 ADKG_DEV_AUTH=off 可 body 传 role）")

    history = [m for m in body.get("messages") or [] if isinstance(m, dict)]
    last = next((m for m in reversed(history) if m.get("role") == "user"), None)
    if not last or not str(last.get("content") or "").strip():
        raise HTTPException(422, "messages 至少要有一条非空 user 消息")

    from adkg.api.routes.ask import _llm, _planner
    llm = _llm(request)
    if llm is None:
        raise HTTPException(503, "LLM 不可用（稍后重试，§7.2）")
    planner = _planner(request)
    if role not in planner.roles:                        # fail-closed（§十二）
        raise HTTPException(401, f"未知角色：{role}")
    plan = planner.plan(role, person=person)
    graph = _graph_of(request)

    trace, reply, case_draft, creative_drafts = [], "", None, None
    generate = getattr(llm, "chat_json_slow", None) or llm.chat_json
    for _ in range(MAX_TURNS):
        payload = generate(_AGENT_SYSTEM, _turn_prompt(history, trace))
        if not isinstance(payload, dict):
            break
        if "final" in payload:
            fin = payload["final"] if isinstance(payload["final"], dict) else {}
            reply = str(fin.get("answer") or "").strip()
            seed = fin.get("case_seed")
            if isinstance(seed, dict) and any(seed.get(k) for k in
                                              ("brand_name", "product_names", "case_name")):
                from adkg.models import load_schema
                from adkg.pipeline.case_gen import materialize_draft
                try:
                    case_draft = materialize_draft(
                        str(seed.get("doc_id") or "agent"), seed, graph,
                        load_schema(), now=datetime.now(timezone.utc))
                except ValueError as e:
                    reply += f"\n\n（案例草稿未生成：{e}）"
            cd = fin.get("creative_drafts")
            if isinstance(cd, list):
                creative_drafts = [d for d in cd if isinstance(d, dict)][:5]
            break
        action = str(payload.get("action") or "")
        args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        trace.append({"tool": action, "args": args,
                      "result": _run_tool(action, args, env, graph, plan, llm,
                                          request, role, person, authorization)[:1200]})
    else:
        reply = reply or f"工具轮次用尽（{MAX_TURNS} 轮）仍未收敛，请缩小问题再试。"
    if not reply and not case_draft and not creative_drafts:
        raise HTTPException(503, f"agent 未能产出结果（{len(trace)} 次工具调用），请重试")

    _audit(env, role, person, str(last.get("content") or ""), len(trace))
    return {"reply": reply, "case_draft": case_draft,
            "creative_drafts": creative_drafts, "trace": trace}


def _run_tool(action: str, args: dict, env: dict, graph, plan, llm,
              request: Request, role: str, person: str | None,
              authorization: str | None) -> str:
    """只读工具执行；结果序列化为紧凑 JSON 供模型下一轮阅读。"""
    if action == "ask_knowledge":                        # 问答：内部走 /ask 三路管线
        from adkg.api.routes.ask import ask as ask_endpoint
        q = str(args.get("question") or "").strip()
        if not q:
            return "question 必填"
        try:
            out = ask_endpoint(request, {"question": q, "role": role, "user": person},
                               authorization)
        except Exception as e:                           # 管线异常不断循环（§7.2）
            return f"ask 失败：{type(e).__name__}"
        return _compact({"answer": out.get("answer"),
                         "routes": [r.get("route") for r in out.get("routes_used", [])],
                         "evidence_n": len(out.get("evidence") or []),
                         "degraded": out.get("degraded", [])})
    if action == "list_brands":
        with graph.session() as s:
            rows = s.run("MATCH (b:Entity {class:'Brand'})"
                         " RETURN b.id AS id, b.name AS name, b.category AS category"
                         " ORDER BY b.id").data()
        return _compact(rows)
    if action == "search_product_knowledge":
        from adkg.retrieval import vector_search
        out = vector_search.search(str(args.get("query") or ""), plan,
                                   env["ADKG_PG_DSN"], embed_fn=llm.embed)
        chunks = [{"ref": e.get("ref"), "quote": str(e.get("quote") or "")[:160],
                   "score": e.get("score")} for e in out.get("evidence", [])[:6]]
        return _compact({"degraded": out.get("degraded", False), "chunks": chunks})
    if action == "search_best_creatives":
        from adkg.api.routes.creative import best_creatives_for, related_brand_ids
        bid = str(args.get("brand_id") or "")
        if not bid.startswith("Brand:"):
            return "brand_id 必须是 Brand:{slug} 形态（先调 list_brands 拿真实 id）"
        try:
            related = related_brand_ids(graph, bid)
        except LookupError as e:
            return str(e)
        refs = best_creatives_for(graph, plan, env["ADKG_PG_RO_DSN"], related,
                                  k=int(args.get("n") or 5))
        return _compact([{k: r.get(k) for k in ("creative_id", "cpa", "ctr", "cost",
                                                "brand_id", "case_id")} for r in refs])
    if action == "get_guidelines":
        return _compact(graph.guidelines_with_thresholds())
    if action == "list_synced_docs":
        from adkg.api.routes.ingest import synced_docs
        return _compact(synced_docs(env["ADKG_PG_DSN"], str(args.get("q") or ""))[:10])
    return f"未知工具：{action}（可用：list_brands / search_product_knowledge / " \
           "search_best_creatives / get_guidelines / list_synced_docs）"


def _turn_prompt(history: list[dict], trace: list[dict]) -> str:
    convo = [{"role": m.get("role"), "content": str(m.get("content") or "")[:2000]}
             for m in history if m.get("role") in ("user", "assistant")]
    return json.dumps({"对话": convo[-8:], "已执行工具及结果": trace},
                      ensure_ascii=False, default=str)


def _compact(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _graph_of(request: Request):
    from adkg.api.routes.ask import _graph
    return _graph(request)


def _audit(env: dict, role: str, person: str | None, question: str, turns: int) -> None:
    with psycopg.connect(env["ADKG_PG_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit_log (user_id, role, action, target, verdict, reason)"
                    " VALUES (%s,%s,'agent_chat',%s,'info',%s)",
                    (person, role, question[:200], f"turns={turns}"))
