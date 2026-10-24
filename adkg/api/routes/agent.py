"""POST /agent/chat（§9.7「Agent 助手」）与 /agent/chat/stream（spec §6 SSE 流式）。

对话式 agent——ReAct 循环 + 工具面（§12.4 过 PermissionPlan）：

- 纯 JSON 契约（不赌端点的 function-calling）：模型每轮输出
  {"action": 工具名, "args": {...}, "think"?: 一句话思路} 或 {"final": {...}}，
  循环 ≤5 轮；think / 工具调用 / 浏览子步（含截图）逐事件下发（ZCode 式透明）
- 工具全只读，唯 fetch_creator_from_platform 是「数据平台连接器」（spec §6）：
  读取星图·模拟页并按 platform_api 口径幂等入图——连接器主数据同步，非 agent 断言
- 产出的 case_draft 不直接入图：由 materialize_draft 在服务端对齐/建号成标准草稿，
  前端确认后仍走 /ingest/case-commit 服务端重校验——铁律不因 agent 而绕过
- 事件契约（SSE data 行）：thought / tool_start / tool_step（含 screenshot data
  URL）/ tool_result / reply / draft / done / error；/agent/chat 聚合同一事件流
  返回原 JSON 形状（测试与旧消费方兼容）
"""
from __future__ import annotations

import json
import time
from collections.abc import Generator
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from adkg.guards.http import get_graph, resolve_identity

router = APIRouter()

MAX_TURNS = 5


class _ToolCtx:                                          # 工具执行上下文（循环内不变量打包）
    def __init__(self, env, graph, plan, llm, request, role, person, authorization,
                 emit=None):
        self.env, self.graph, self.plan, self.llm = env, graph, plan, llm
        self.request, self.role, self.person, self.authorization = \
            request, role, person, authorization
        self.emit = emit                                 # 浏览工具子步回调（SSE 路）


def _t_ask_knowledge(args: dict, ctx: _ToolCtx) -> str:
    from adkg.api.routes.ask import ask as ask_endpoint
    q = str(args.get("question") or "").strip()
    if not q:
        return "question 必填"
    try:
        out = ask_endpoint(ctx.request, {"question": q, "role": ctx.role,
                                         "user": ctx.person}, ctx.authorization)
    except Exception as e:                                # 管线异常不断循环（§7.2）
        return f"ask 失败：{type(e).__name__}"
    return _compact({"answer": out.get("answer"),
                     "routes": [r.get("route") for r in out.get("routes_used", [])],
                     "evidence_n": len(out.get("evidence") or []),
                     "degraded": out.get("degraded", [])})


def _t_list_brands(args: dict, ctx: _ToolCtx) -> str:
    if getattr(ctx.plan, "deny_all", False):
        return "行权限未生效（缺有效身份）"
    with ctx.graph.session() as s:
        rows = s.run("MATCH (b:Entity {class:'Brand'})"
                     " RETURN b.id AS id, b.name AS name, b.category AS category"
                     " ORDER BY b.id").data()
    from adkg.api.routes.creative import _scoped_brands
    return _compact(_scoped_brands(rows, ctx.plan, ctx.graph))   # 行权限裁剪（§12.4）


def _t_search_product_knowledge(args: dict, ctx: _ToolCtx) -> str:
    from adkg.retrieval import vector_search
    out = vector_search.search(str(args.get("query") or ""), ctx.plan,
                               ctx.env["ADKG_PG_DSN"], embed_fn=ctx.llm.embed)
    chunks = [{"ref": e.get("ref"), "quote": str(e.get("quote") or "")[:160],
               "score": e.get("score")} for e in out.get("evidence", [])[:6]]
    return _compact({"degraded": out.get("degraded", False), "chunks": chunks})


def _t_search_best_creatives(args: dict, ctx: _ToolCtx) -> str:
    from adkg.api.routes.creative import best_creatives_for, related_brand_ids
    bid = str(args.get("brand_id") or "")
    if not bid.startswith("Brand:"):
        return "brand_id 必须是 Brand:{slug} 形态（先调 list_brands 拿真实 id）"
    try:
        related = related_brand_ids(ctx.graph, bid)
    except LookupError as e:
        return str(e)
    refs = best_creatives_for(ctx.graph, ctx.plan, ctx.env["ADKG_PG_RO_DSN"], related,
                              k=int(args.get("n") or 5))
    return _compact([{k: r.get(k) for k in ("creative_id", "cpa", "ctr", "cost",
                                            "brand_id", "case_id")} for r in refs])


def _t_get_guidelines(args: dict, ctx: _ToolCtx) -> str:
    return _compact(ctx.graph.guidelines_with_thresholds())


def _t_list_synced_docs(args: dict, ctx: _ToolCtx) -> str:
    from adkg.api.routes.ingest import synced_docs
    if ctx.plan.mask_rules:                       # 外部角色：文档标题含他牌月报，不见
        return "当前角色不可见文档清单"
    return _compact(synced_docs(ctx.env["ADKG_PG_DSN"], str(args.get("q") or ""))[:10])


def _t_fetch_creator_from_platform(args: dict, ctx: _ToolCtx) -> str:
    from adkg.api.routes.platform_browser import fetch_creator_from_platform
    return fetch_creator_from_platform(args, ctx)


# 工具注册表（§9.1 收口）：名 → (签名+描述, handler)——system prompt、未知工具提示、
# 分发三处同源，加工具只改这里
_TOOLS: dict[str, tuple[str, object]] = {
    "ask_knowledge": ('{"question"} → 知识问答（指标/排名/归因/关系类问题，走三路检索管线）',
                      _t_ask_knowledge),
    "list_brands": ('{} → 品牌与类目', _t_list_brands),
    "search_product_knowledge": ('{"query"} → 已入库文档的商品知识（卖点/售后/尺码）',
                                 _t_search_product_knowledge),
    "search_best_creatives": ('{"brand_id", "n"} → 同类目最好案例素材（CPA 口径）',
                              _t_search_best_creatives),
    "get_guidelines": ('{} → 创意规范与机判阈值', _t_get_guidelines),
    "list_synced_docs": ('{"q"} → 已同步飞书文档（生成案例的素材源）', _t_list_synced_docs),
    "fetch_creator_from_platform": (
        '{"query"|"creator_no"} → 星图·模拟数据平台连接器：无头浏览器真实搜索/点击达人页，'
        '抓档案（粉丝/报价/GMV/视频方向）并幂等入图（platform_api 口径）——查达人现价用它',
        _t_fetch_creator_from_platform),
}

_AGENT_SYSTEM = (
    "你是 AdKG 知识中台的助手：既能回答知识问题（问答），也能把已入库知识变成案例/素材草稿（生成）。"
    "每轮只输出 JSON，二选一——"
    '需要更多信息：{"action": "工具名", "args": {...}, "think": "一句话当前思路"}；'
    '信息足够：{"final": {"answer": "给用户的说明", '
    '"case_seed": {"brand_name", "product_names": [], "case_name"?, "stage"?, "doc_id"?, "person_ids": []} 或 null, '
    '"creative_drafts": [{"title","format","platform","hook_3s","script","copy"}] 或 null}}。'
    "工具（全部只读）：" + "；".join(f"{n} {d}" for n, (d, _) in _TOOLS.items()) + "。"
    "规矩：think 必填且不超过 40 字（用户会看到你的思考轨迹）；"
    "事实/排名/归因类问题直接调 ask_knowledge，一次调用即完整转述答案（保留数字与结论），"
    "不要重复调用；不知道就先调工具查，禁止编造实体、卖点与数据；"
    "person_ids 只能用工具结果里见到的真实 id（未对齐不入图）；"
    "creative hook_3s 必须满足规范阈值，卖点只能来自 search_product_knowledge；"
    "answer 里说明依据了哪些工具结果；一次 final 可以同时带问答要点、案例种子与素材草稿。"
)


def _prepare(request: Request, body: dict, authorization: str | None):
    """身份与输入校验（流式响应开始前完成——错了还能回标准 HTTP 错误码）。"""
    env = request.app.state.env
    from adkg.api.routes.ask import _llm
    role, person, planner = resolve_identity(request, authorization, body=body)
    history = [m for m in body.get("messages") or [] if isinstance(m, dict)]
    last = next((m for m in reversed(history) if m.get("role") == "user"), None)
    if not last or not str(last.get("content") or "").strip():
        raise HTTPException(422, "messages 至少要有一条非空 user 消息")
    llm = _llm(request)
    if llm is None:
        raise HTTPException(503, "LLM 不可用（稍后重试，§7.2）")
    plan = planner.plan(role, person=person)
    graph = get_graph(request)
    tool_ctx = _ToolCtx(env, graph, plan, llm, request, role, person, authorization)
    return env, role, person, history, last, tool_ctx


def _agent_events(tool_ctx: _ToolCtx, history: list[dict],
                  last: dict) -> Generator[dict, None, None]:
    """ReAct 循环 → 事件流（唯一实现；/agent/chat 聚合，stream 逐条下发）。"""
    trace: list[dict] = []
    reply, case_draft, creative_drafts = "", None, None
    generate = getattr(tool_ctx.llm, "chat_json_slow", None) or tool_ctx.llm.chat_json
    t_start = time.monotonic()                           # 整循环墙钟（§7.2：120s 上限）
    for _ in range(MAX_TURNS):
        if time.monotonic() - t_start > 120:             # 超限带已有 trace 收敛，不再发起调用
            reply = reply or f"已达处理时限，基于已获取的 {len(trace)} 次工具结果回答。"
            break
        # timeout=60 单轮限时（§7.2）。不带 max_retries：chat_json_slow 内部本就
        # max_retries=0，且真客户端签名不收该参（原样传参曾致真机路 TypeError——
        # FakeLLM 收 **kw 掩盖了它，2026-10-24 实弹发现）
        payload = generate(_AGENT_SYSTEM, _turn_prompt(history, trace), timeout=60)
        if not isinstance(payload, dict):
            break
        think = str(payload.get("think") or "").strip()
        if think:
            yield {"type": "thought", "text": think[:200]}
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
                        str(seed.get("doc_id") or "agent"), seed, tool_ctx.graph,
                        load_schema(), now=datetime.now(timezone.utc))
                except ValueError as e:
                    reply += f"\n\n（案例草稿未生成：{e}）"
            cd = fin.get("creative_drafts")
            if isinstance(cd, list):
                creative_drafts = [d for d in cd if isinstance(d, dict)][:5]
            break
        action = str(payload.get("action") or "")
        args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
        yield {"type": "tool_start", "tool": action, "args": args}
        ran = _run_tool_streamed(action, args, tool_ctx)
        if isinstance(ran, dict):                    # 工具子步事件（含截图）——边执行边上屏
            for ev in ran["events"]:
                yield ev
            result = ran["result"]
        else:
            result = ran
        trace.append({"tool": action, "args": args, "result": result[:1200]})
        yield {"type": "tool_result", "tool": action, "result": result[:600]}
    else:
        reply = reply or f"工具轮次用尽（{MAX_TURNS} 轮）仍未收敛，请缩小问题再试。"
    if reply:
        yield {"type": "reply", "text": reply}
    if case_draft is not None or creative_drafts is not None:
        yield {"type": "draft", "case_draft": case_draft, "creative_drafts": creative_drafts}
    from adkg.api.routes.ingest import CASEGEN_ROLES
    yield {"type": "done", "turns": len(trace),
           "can_commit_case": tool_ctx.role in CASEGEN_ROLES,
           "has_result": bool(reply or case_draft or creative_drafts)}


@router.post("/agent/chat")
def agent_chat(request: Request, body: dict,
               authorization: str | None = Header(default=None)) -> dict:
    """聚合形态（测试与既有消费方兼容）：吃同一事件流，还原原 JSON 返回。"""
    env, role, person, history, last, tool_ctx = _prepare(request, body, authorization)
    trace: list[dict] = []
    reply, case_draft, creative_drafts = "", None, None
    can_commit, has_result = False, False
    for ev in _agent_events(tool_ctx, history, last):
        if ev["type"] == "tool_start":
            trace.append({"tool": ev["tool"], "args": ev["args"], "result": ""})
        elif ev["type"] == "tool_result" and trace:
            trace[-1]["result"] = ev["result"][:1200]
        elif ev["type"] == "reply":
            reply = ev["text"]
        elif ev["type"] == "draft":
            case_draft, creative_drafts = ev["case_draft"], ev["creative_drafts"]
        elif ev["type"] == "done":
            can_commit, has_result = ev["can_commit_case"], ev["has_result"]
    if not has_result:
        raise HTTPException(503, f"agent 未能产出结果（{len(trace)} 次工具调用），请重试")
    _audit(env, role, person, str(last.get("content") or ""), len(trace))
    return {"reply": reply, "case_draft": case_draft,
            "creative_drafts": creative_drafts, "trace": trace,
            "can_commit_case": can_commit}   # 前端不本地硬抄角色表（§9.7）


@router.post("/agent/chat/stream")
def agent_chat_stream(request: Request, body: dict,
                      authorization: str | None = Header(default=None)) -> StreamingResponse:
    """SSE 流式（spec §6）：事件逐条下发——思考/工具/浏览子步（截图）实时上屏。

    校验在响应开始前完成（_prepare）；循环内异常转 error 事件，不裸断流。
    """
    env, role, person, history, last, tool_ctx = _prepare(request, body, authorization)

    def gen() -> Generator[str, None, None]:
        turns = 0
        try:
            for ev in _agent_events(tool_ctx, history, last):
                if ev["type"] == "done":
                    turns = ev["turns"]
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            _audit(env, role, person, str(last.get("content") or ""), turns)
        except Exception as e:                              # noqa: BLE001 不断流：转 error 事件
            yield f"data: {json.dumps({'type': 'error', 'detail': f'{type(e).__name__}: {e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _run_tool(action: str, args: dict, ctx: _ToolCtx) -> str:
    """工具执行（注册表分发，§9.1 收口）；结果序列化为紧凑 JSON 供模型阅读。"""
    entry = _TOOLS.get(action)
    if entry is None:
        return f"未知工具：{action}（可用：{' / '.join(_TOOLS)}）"
    return str(entry[1](args if isinstance(args, dict) else {}, ctx))


def _run_tool_streamed(action: str, args: dict, ctx: _ToolCtx) -> str | dict:
    """工具执行 + 子步事件实时性：emit 的工具（如平台浏览）放线程跑，事件经队列
    即时产出（截图边浏览边上屏，spec §6）；无 emit 输出的工具同步执行完即返回 str。"""
    import queue
    import threading
    events: "queue.Queue[dict]" = queue.Queue()
    done = queue.Queue()
    ctx.emit = lambda kind, **kw: events.put({"type": kind, **kw})

    def _work():
        try:
            done.put(_run_tool(action, args, ctx))
        except Exception as e:                          # noqa: BLE001 工具异常不砸循环（§7.2）
            done.put(f"工具执行失败：{type(e).__name__}: {e}")

    threading.Thread(target=_work, daemon=True).start()
    collected: list[dict] = []
    while True:
        try:
            ev = events.get(timeout=0.2)
            collected.append(ev)
        except queue.Empty:
            pass
        try:
            result = done.get_nowait()
            # worker 单线程：done 就绪即全部 emit 已入队——drain 尾部事件防截丢
            while True:
                try:
                    collected.append(events.get_nowait())
                except queue.Empty:
                    break
            return {"result": result, "events": collected}
        except queue.Empty:
            continue


def _turn_prompt(history: list[dict], trace: list[dict]) -> str:
    convo = [{"role": m.get("role"), "content": str(m.get("content") or "")[:2000]}
             for m in history if m.get("role") in ("user", "assistant")]
    return json.dumps({"对话": convo[-8:], "已执行工具及结果": trace},
                      ensure_ascii=False, default=str)


def _compact(data) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _audit(env: dict, role: str, person: str | None, question: str, turns: int) -> None:
    from adkg.guards.audit import audit                  # 审计写入收口（§9.1）
    audit(env, role, person, "agent_chat", question, "info", f"turns={turns}")
