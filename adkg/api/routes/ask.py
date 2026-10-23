"""POST /ask（§7.2 使用链路 / §9.4 响应契约）。

链路：认证（token→role，dev 模式 body 兜底）→ PermissionPlan → router →
按 RouterPlan 步序执行三路（依赖已由模型校验指向更早步骤，按序即满足）→
assemble → audit（/ask 按次入审计，§12.4）。
只收查询类；操作类意图返回 /actions/check 指引（§7.3）。
"""
from __future__ import annotations

import time

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
    """惰性 LLM 客户端；探测失败不缓存（限流是暂态，下一问重试，§7.2）。"""
    if not hasattr(request.app.state, "llm"):
        request.app.state.llm = None
    if request.app.state.llm is None and request.app.state.env.get("ADKG_LLM_API_KEY"):
        try:
            from adkg.llm import LLMClient
            client = LLMClient()
            client.chat_json("ping", '返回 {"ok": true}', timeout=12, max_retries=0)
            request.app.state.llm = client
        except Exception:
            return None                                  # 本问降级，不缓存失败
    return request.app.state.llm


def _embed_fn(request: Request):
    """本地 bge 嵌入独立于 chat 探测（失败域解耦，§7.2）：嵌入与 chat 端点零依赖，
    探测失败曾级联杀掉 vector 路（2026-10-23 检查实锤）。常驻缓存（本地模型可靠）。"""
    if not hasattr(request.app.state, "embedder"):
        try:
            from adkg.llm import LLMClient
            request.app.state.embedder = LLMClient()
        except Exception:
            request.app.state.embedder = None
    return request.app.state.embedder.embed if request.app.state.embedder else None


@router.post("/ask")
def ask(request: Request, body: dict,
        authorization: str | None = Header(default=None)) -> dict:
    env = request.app.state.env
    dev_auth_off = env.get("ADKG_DEV_AUTH") == "off"

    resolved = AuthService(env).resolve(authorization)
    planner = _planner(request)
    if resolved:
        role = resolved[0]
        # token 路 person 一律取 bindings 绑定值（§12.4），body 自报仅补缺（多绑定角色）
        person = planner.bound_person(role) or body.get("user")
    elif dev_auth_off and body.get("role"):
        role, person = body["role"], body.get("user")       # 仅本地开发（§9.1）
    else:
        raise HTTPException(401, "缺有效 service token（生产经网关注入；本地 ADKG_DEV_AUTH=off 可 body 传 role）")

    question = str(body.get("question", "")).strip()
    if not question:
        raise HTTPException(422, "question 不能为空")

    if role not in planner.roles:                        # dev 路可传任意值，fail-closed（§十二）
        raise HTTPException(401, f"未知角色：{role}")
    plan = planner.plan(role, person=person)
    llm = _llm(request)
    embed_fn = _embed_fn(request)
    t0 = time.monotonic()                                 # 交互路时延预算（§7.2）
    decision = rule_route(question)
    if llm is not None and decision.confidence < 0.8:     # 强关键词信规则，LLM 只兜弱置信
        try:
            decision = llm_route(question,
                                 lambda s, u: llm.chat_json(s, u, timeout=15, max_retries=0))
        except Exception:
            pass                                          # 回规则（§7.2）

    if decision.intent == "operation":                      # 不进 /ask（§7.3）
        _audit(env, role, person, question, "info", "operation 意图，返回端点指引")
        return {"action": "guidance", "intent": "operation",
                "endpoint": "/actions/check",
                "reason": "操作类请求请直接调用 /actions/check 做裁决（AdKG 只裁决不代执行）"}

    graph = _graph(request)
    results: dict[str, dict] = {}
    for step in decision.plan.steps:                        # 按序执行即满足依赖
        if step.route.value == "graph":
            r = graph_search.search(question, plan, graph, person=person)
        elif step.route.value == "text2sql":
            dep = step.params.get("entity_ids_from")
            entity_ids = results.get(dep, {}).get("entity_ids") if dep else None
            if entity_ids:            # graph 圈到 Brand/Case/Campaign 时展开成素材再进 SQL（§7.3）
                entity_ids = graph.expand_to_creatives(entity_ids) or None
            r = text2sql.run(question, plan, env["ADKG_PG_RO_DSN"], entity_ids,
                             generator=(lambda s, u: llm.chat_json(s, u, timeout=30, max_retries=0))
                             if llm else None)
        else:
            r = vector_search.search(question, plan, env["ADKG_PG_DSN"], embed_fn=embed_fn)
        results[step.step_id] = {"route": step.route.value, "confidence": step.confidence, **r}

    # 事实行→图补 join（"谁做的"）：text2sql 命中的素材回查负责人，作为 relation 证据
    # 注入 graph 路（行权限已由谓词过滤保证；人名脱敏在 assemble 出口统一处理 §12.6）
    creative_ids = sorted({str(row.get("creative_id"))
                           for res in results.values()
                           for ev in res.get("evidence", [])
                           for row in ev.get("rows", [])
                           if row.get("creative_id")})
    joined = []
    for j in graph.responsible_for_creatives(creative_ids):
        joined.append({
            "type": "relation",
            "ref": (f"({j['cid']})<-[:uses]-({j['campaign']})"
                    f"-[:belongs_to]->({j['case']})<-[:responsible_for]-({j['person']})"),
            "who": j.get("person_name") or "",           # agent 总结直接用人名
            "provenance": {"source_type": "system_of_record", "authority": 100},
        })
    # 违规边补拉（G15）："CPA 最差的素材违反了哪些规范"——事实行素材回查 violates 规范；
    # 所问素材集无违规时补图上违规样本（答案如实说明"无违规记录 + 全图样本"），
    # 归因问题必须有 violates 证据可答（§7.3 串行 g→t→v 的 v 步素材）
    for j in graph.violations_of_creatives(creative_ids):
        joined.append({
            "type": "relation",
            "ref": f"({j['cid']})-[:violates]->({j['gid']})",
            "who": j.get("guideline_name") or "",
            "provenance": {"source_type": "official_doc", "authority": 60},
        })
    if "违反" in question and not any("violates" in str(e.get("ref", "")) for e in joined):
        with graph.session() as s:
            for r_ in s.run("MATCH (c:Entity)-[:violates]->(g:Entity)"
                            " RETURN c.id AS cid, g.id AS gid, g.name AS gname LIMIT 5").data():
                joined.append({
                    "type": "relation",
                    "ref": f"({r_['cid']})-[:violates]->({r_['gid']})",
                    "who": r_.get("gname") or "",
                    "provenance": {"source_type": "official_doc", "authority": 60},
                })
    if joined:
        gres = results.get("g")                            # 归并进 graph 路（无则补一路）
        if gres is None:
            for sid, step_res in results.items():
                if step_res["route"] == "graph":
                    gres = step_res
                    break
        if gres is None:                                   # 纯 fact 路也注入（串行依赖的通用化）
            results["g+"] = {"route": "graph", "confidence": 0.9, "evidence": joined,
                             "entity_ids": creative_ids, "filtered": 0}
        else:
            gres["evidence"] = gres.get("evidence", []) + joined

    person_names = None
    if plan.mask_rules:
        with graph.session() as s:                          # 脱敏出口需要人名表（§12.6）
            person_names = [r["n"] for r in s.run(
                "MATCH (p:Entity) WHERE p.class='Person' AND p.name IS NOT NULL RETURN p.name AS n").data()]
    out = assemble(results, plan, decision, person_names=person_names)

    name_map = _id_name_map(out["evidence"], graph)         # ID → 中文名（答案/证据可读性）
    _readable_refs(out["evidence"], name_map)

    answer, answer_source = _summarize(question, out, decision), "template"
    if llm is not None and out["evidence"] and time.monotonic() - t0 < 60:
        try:                                                # agent 总结：只依据证据（§11.3 溯源）；
                                                            # 超预算（前序已 ≥60s）不再发起（§7.2）
            answer, answer_source = _agent_answer(llm, question, out["evidence"], name_map), "agent"
        except Exception:
            pass                                            # 回模板（§7.2）
    _audit(env, role, person, question, "info", f"intent={decision.intent}")
    return {"answer": answer, "answer_source": answer_source, **out}


def _summarize(question: str, out: dict, decision) -> str:
    """模板摘要（LLM 不可用/超时时的降级答案，§7.2）；decision 可为 None（内部回退）。"""
    n = len(out["evidence"])
    routes = "、".join(r["route"] for r in out["routes_used"])
    tail = f"（缺席路：{'、'.join(out['degraded'])}）" if out["degraded"] else ""
    intent = decision.intent if decision is not None else "unknown"
    return f"[{intent}] 命中 {n} 条证据（{routes} 路）{tail}——依据见 evidence，每条带 provenance。"


_ANSWER_PROMPT = (
    "你是知识中台的回答助手。只依据【证据】回答【问题】，输出中文 markdown（结论先行）："
    "清单/排名/多条对比用 markdown 表格（表格前后各空一行；少量条目可用列表），关键数字加粗；"
    "直接给结论（清单/数字/人名），每个事实后标注证据编号如 [#1]；"
    "提到素材/计划/案例/品牌等实体必须用【名称映射】里的中文名（映射没有的可用证据里的可读字段），"
    "禁止输出 Creative:C-xxx 这类裸 ID；日期统一写成 YYYY-MM；"
    "证据不足以回答的部分明说'证据中未涵盖'，禁止编造。"
)


def _id_name_map(evidence: list[dict], graph) -> dict[str, str]:
    """证据中出现的本体 ID → 图上中文名（答案可读性：不让 LLM 对用户输出裸 ID）。"""
    import json as _json
    import re

    ids = set(re.findall(r"(?:Brand|Product|Campaign|Creative|Case|Person|Guideline|Metric"
                         r"|Channel|Audience|LandingPage):[A-Za-z0-9_\-.]+",
                         _json.dumps(evidence, ensure_ascii=False, default=str)))
    if not ids:
        return {}
    with graph.session() as s:
        rows = s.run("MATCH (e:Entity) WHERE e.id IN $ids AND e.name IS NOT NULL "
                     "RETURN e.id AS id, e.name AS name", ids=sorted(ids)).data()
    return {r["id"]: r["name"] for r in rows}


_REL_CN = {                                                 # schema.yaml 14 关系的展示词
    "for_brand": "投放品牌", "for_product": "推广产品", "has_product": "旗下产品",
    "belongs_to": "属于", "uses": "使用", "in_channel": "投放渠道", "targets": "定向",
    "links_to": "落地页", "complies_with": "符合", "violates": "违反",
    "derived_from": "衍生自", "responsible_for": "负责", "belongs_to_brand": "所属品牌",
    "external_for": "客户对接", "supersedes": "替代",
}


def _readable_refs(evidence: list[dict], name_map: dict[str, str]) -> None:
    """ref 原串保留作溯源锚（评测判据锚它）；readable_ref 给前端主行——中文名 + 中文关系词。"""
    import re

    for ev in evidence:
        ref = ev.get("ref")
        if not ref or "-[:" not in ref:
            continue
        text = ref
        for eid, name in name_map.items():
            text = text.replace(eid, f"「{name}」")
        text = re.sub(r"<-\[:(\w+)\]-", lambda m: f"←{_REL_CN.get(m[1], m[1])}—", text)
        text = re.sub(r"-\[:(\w+)\]->", lambda m: f"—{_REL_CN.get(m[1], m[1])}→", text)
        text = re.sub(r"-\[:(\w+)\]-", lambda m: f"—{_REL_CN.get(m[1], m[1])}—", text)
        text = re.sub(r"\(([^()]+)\)", r"\1", text)         # 去括号；未映射 ID 原样保留
        ev["readable_ref"] = text


_SLIM_DROP = {"ref", "provenance"}
# 总结 prompt 不带：溯源锚 ref / 四元组 provenance 只进响应（前端/评测用），进 prompt 纯耗 token
# （filtered/entity_ids/sql 从不落在 evidence 项上，曾列进丢弃集是空转——2026-10-23 检查勘正）


def _agent_answer(llm, question: str, evidence: list[dict],
                  name_map: dict[str, str] | None = None) -> str:
    import json

    payload = llm.chat_json(
        _ANSWER_PROMPT + ' 只输出 JSON：{"answer": "…"}。',
        json.dumps({"问题": question,
                    "名称映射": name_map or {},
                    "证据": [{"#": f"#{i}",
                              **{k: v for k, v in ev.items()
                                 if k not in _SLIM_DROP and k != "rows"},
                              "rows": ev.get("rows", [])[:5]}
                             for i, ev in enumerate(evidence[:10], 1)]},
                   ensure_ascii=False, default=str),
        timeout=60, max_retries=0)                         # 限时单发：超时回模板（§7.2；60s 档）
    return str(payload.get("answer", "")).strip() or _summarize(question, {"evidence": evidence,
                                                                          "routes_used": [],
                                                                          "degraded": []}, None)


def _audit(env: dict, role: str, person: str | None, question: str,
           verdict: str, reason: str) -> None:
    with psycopg.connect(env["ADKG_PG_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO audit_log (user_id, role, action, target, verdict, reason)"
                    " VALUES (%s,%s,'ask',%s,%s,%s)",
                    (person, role, question[:200], verdict, reason))
