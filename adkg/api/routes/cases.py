"""案例全生命周期端点（spec §13.2）：列表（批量指标）+ 详情六段。

可见性：Case 类白名单 + 行过滤（client 只见自己品牌；ae 对接品牌；optimizer
负责案例）。指标批量/明细全部走 metrics.py 汇总比 + plan.sql_predicate 同一道
闸，指标列出口过白名单；ae 的 Case.bd_budget / gross_margin 按 deny_properties
出口过滤（client 外部属性白名单只剩 stage，内容/指标对 client 收敛到可见范围）。
"""
from __future__ import annotations

import psycopg

from adkg.store import pg_pool
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request
from psycopg.rows import dict_row

from adkg.guards.http import get_graph, resolve_identity
from adkg.retrieval.metrics import STAT_FAMILY, agg_expr

router = APIRouter()

STAGE_LABEL = {"proposal": "提案中", "live": "投放中", "closed": "已结案",
               "lost": "未成单", "terminated": "已终止"}
# 状态机主线 + 分支（schema.yaml#constraints 的展示形态）
STAGE_FLOW = ["proposal", "live", "closed"]
STAGE_BRANCH = {"lost": "proposal", "terminated": "live"}


def _case_stats_batch(env: dict, plan, case_ids: list[str]) -> dict[str, dict]:
    """案例维度批量汇总比（一条 SQL）：与 /graph stats、/brands 同口径同闸。"""
    if not case_ids:
        return {}
    predicate = f" AND {plan.sql_predicate}" if plan.sql_predicate else ""
    try:
        proj = ", ".join(f"{agg_expr(c)} AS {c}" for c in STAT_FAMILY)
        with pg_pool.connect(env["ADKG_PG_RO_DSN"], options="-c statement_timeout=4000",
                             row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT case_id, {proj}, string_agg(DISTINCT platform::text, ',') AS platforms,"
                " count(DISTINCT date) AS days FROM unified_metrics"
                " WHERE NOT unmatched AND case_id = ANY(%(ids)s)" + predicate +
                " GROUP BY case_id", {"ids": case_ids})
            rows = cur.fetchall()
    except psycopg.Error:
        return {}                                            # 统计失败不阻塞列表（§7.2 降级）
    return {r["case_id"]: {k: v for k, v in r.items()
                           if k not in STAT_FAMILY or k in plan.allowed_columns}
            for r in rows}


def _mask_case_props(plan, props: dict) -> dict:
    """Case 属性出口过滤：内部 deny_properties（ae 不见预算/毛利）、外部只剩 stage。"""
    if plan.allow_properties:                               # 外部角色属性白名单
        return {k: props.get(k) for k in ("stage",) if props.get(k) is not None}
    denied = {d.split(".", 1)[1] for d in plan.deny_properties if d.startswith("Case.")}
    return {k: v for k, v in props.items() if k not in denied}


@router.get("/cases")
def list_cases(request: Request, q: str = "", stage: str = "", brand: str = "",
               page: int = 1, size: int = 20,
               role: str | None = None, user: str | None = None,
               authorization: str | None = Header(default=None)) -> dict:
    role, user, planner = resolve_identity(request, authorization, role=role, user=user)
    plan = planner.plan(role, person=user)
    if plan.deny_all:
        raise HTTPException(403, "行权限未生效（缺有效身份），拒绝读取")
    allowed = set(plan.metadata_filter.get("entity_class__in", []))
    if "Case" not in allowed:
        raise HTTPException(403, "类 Case 不在当前角色白名单")
    visible = plan.visible_entity_ids
    size = max(1, min(size, 100))
    page = max(1, page)
    with get_graph(request).session() as s:
        # 全量取出再行过滤后 Python 分页——锚点角色若先分页后过滤，首页会被
        # 不可见案例占满（案例量级 ≤ 数百，全量可控）
        rows = s.run(
            "MATCH (c:Entity {class: 'Case'})-[:for_brand]->(b:Entity) "
            "WHERE ($q = '' OR c.name CONTAINS $q)"
            "  AND ($stage = '' OR c.stage = $stage)"
            "  AND ($brand = '' OR b.id = $brand OR b.name CONTAINS $brand) "
            "OPTIONAL MATCH (p:Entity)-[:responsible_for]->(c) "
            "RETURN c.id AS id, c.name AS name, c.stage AS stage, "
            "c.settlement_status AS settlement_status, c.bd_budget AS bd_budget, "
            "c.gross_margin AS gross_margin, c.lost_reason AS lost_reason, "
            "c.terminate_reason AS terminate_reason, "
            "b.id AS brand_id, b.name AS brand_name, "
            "collect(DISTINCT p.name) AS owners ORDER BY c.id LIMIT 500",
            q=q.strip(), stage=stage.strip(), brand=brand.strip()).data()
    rows = [r for r in rows if not visible or r["id"] in visible]
    total = len(rows)
    items = rows[(page - 1) * size:page * size]
    stats = _case_stats_batch(request.app.state.env, plan, [r["id"] for r in items])
    external = bool(plan.allow_properties)
    for r in items:
        r["stats"] = stats.get(r["id"])
        if external:                                        # client：姓名掩码 + 只留 stage
            r["owners"] = []
            # client 保留 lost_reason（spec §5「为什么没成」；2026-10-25 审查勘误）
            for k in ("bd_budget", "gross_margin", "settlement_status",
                      "terminate_reason"):
                r.pop(k, None)
        else:
            denied = {d.split(".", 1)[1] for d in plan.deny_properties
                      if d.startswith("Case.")}
            for k in denied:
                r.pop(k, None)
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/cases/{cid}")
def case_detail(request: Request, cid: str,
                role: str | None = None, user: str | None = None,
                authorization: str | None = Header(default=None)) -> dict:
    role, user, planner = resolve_identity(request, authorization, role=role, user=user)
    plan = planner.plan(role, person=user)
    if plan.deny_all:
        raise HTTPException(403, "行权限未生效（缺有效身份），拒绝读取")
    allowed = set(plan.metadata_filter.get("entity_class__in", []))
    if "Case" not in allowed:
        raise HTTPException(403, "类 Case 不在当前角色白名单")
    visible = plan.visible_entity_ids
    external = bool(plan.allow_properties)                  # client：属性白名单 + 姓名掩码
    env = request.app.state.env

    with get_graph(request).session() as s:
        rec = s.run("MATCH (c:Entity {id: $id}) RETURN c.id AS id, c.name AS name, "
                    "c.stage AS stage, c.bd_budget AS bd_budget, "
                    "c.gross_margin AS gross_margin, "
                    "c.settlement_status AS settlement_status, "
                    "c.lost_reason AS lost_reason, "
                    "c.terminate_reason AS terminate_reason, c.class AS class",
                    id=cid).single()
        if not rec or rec["class"] != "Case":
            raise HTTPException(404, f"案例 {cid} 不存在")
        if visible and cid not in visible:
            raise HTTPException(404, "案例不在当前身份可见范围（锚点外）")
        brand = product = None
        b = s.run("MATCH (:Entity {id: $id})-[:for_brand]->(b:Entity) "
                  "RETURN b.id AS id, b.name AS name", id=cid).single()
        if b and ("Brand" in allowed or (visible and b["id"] in visible)):
            brand = dict(b)              # 锚点豁免类闸：client 见自己绑定的品牌（同 /brands）
        if "Product" in allowed:
            p = s.run("MATCH (:Entity {id: $id})-[:for_product]->(p:Entity) "
                      "RETURN p.id AS id, p.name AS name, p.spec AS spec, "
                      "p.price AS price, p.target_age AS target_age", id=cid).single()
            product = dict(p) if p else None
        owners = [] if external else [
            dict(r) for r in s.run(
                "MATCH (p:Entity)-[:responsible_for]->(:Entity {id: $id}) "
                "RETURN p.id AS id, p.name AS name ORDER BY p.id", id=cid).data()]
        campaigns = s.run(
            "MATCH (cp:Entity)-[:belongs_to]->(:Entity {id: $id}) "
            "RETURN cp.id AS id, cp.name AS name, cp.status AS status ORDER BY cp.id",
            id=cid).data()
        creatives = s.run(
            "MATCH (cp:Entity)-[:belongs_to]->(:Entity {id: $id}) "
            "MATCH (cp)-[:uses]->(cr:Entity) "
            "RETURN cr.id AS id, cr.name AS name ORDER BY cr.id", id=cid).data()
        creators = [
            dict(r) for r in s.run(
                "MATCH (:Entity {id: $id})-[:collabs_with]->(cr:Entity) "
                "RETURN cr.id AS id, cr.name AS name, cr.niches AS niches, "
                "cr.followers AS followers, cr.quote_20s AS quote_20s ORDER BY cr.id",
                id=cid).data()]

    # 素材指标明细（汇总比 + 指标白名单 + 行谓词同闸）
    predicate = f" AND {plan.sql_predicate}" if plan.sql_predicate else ""
    creative_rows: list[dict] = []
    try:
        proj = ", ".join(f"{agg_expr(c)} AS {c}" for c in STAT_FAMILY)
        with pg_pool.connect(env["ADKG_PG_RO_DSN"], options="-c statement_timeout=3000",
                             row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT creative_id, string_agg(DISTINCT platform::text, ',') AS platforms,"
                f" {proj} FROM unified_metrics WHERE NOT unmatched"
                f" AND case_id = %(id)s{predicate} GROUP BY creative_id"
                " HAVING count(DISTINCT date) >= 1 ORDER BY cost DESC", {"id": cid})
            creative_rows = [{k: v for k, v in r.items()
                              if k not in STAT_FAMILY or k in plan.allowed_columns}
                             for r in cur.fetchall()]
    except psycopg.Error:
        creative_rows = []                                   # 统计失败不阻塞详情（§7.2）

    # 内容：案例文档 chunks（gen_seed 模板即真源，chunk#0 首行为标题）
    docs: list[dict] = []
    try:
        with pg_pool.connect(env["ADKG_PG_DSN"], row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("SELECT doc_id, chunk_index, text FROM chunks"
                        " WHERE case_id = %(id)s ORDER BY doc_id, chunk_index LIMIT 30",
                        {"id": cid})
            docs = [{"doc_id": r["doc_id"], "chunk_index": r["chunk_index"],
                     "text": r["text"]} for r in cur.fetchall()]
    except psycopg.Error:
        docs = []

    # 流转记录：该案例的审计动作（种子无记录时前端诚实显示「暂无」）
    timeline: list[dict] = []
    try:
        with pg_pool.connect(env["ADKG_PG_DSN"], row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("SELECT ts::text AS ts, role, action, verdict, reason"
                        " FROM audit_log WHERE target = %(id)s"
                        " ORDER BY ts DESC LIMIT 20", {"id": cid})
            timeline = [dict(r) for r in cur.fetchall()]
    except psycopg.Error:
        timeline = []

    if plan.mask_rules:            # 外部角色出口脱敏（§12.6）：chunk 文本掩人名、
        with get_graph(request).session() as _s:  # timeline 剥 role/reason（内部身份与人名）
            _names = [r["n"] for r in _s.run(
                "MATCH (p:Entity) WHERE p.class='Person' AND p.name IS NOT NULL"
                " RETURN p.name AS n").data()]
        for d in docs:
            for n in _names:
                d["text"] = d["text"].replace(n, "＊＊")
        timeline = [{k: t[k] for k in ("ts", "action", "verdict")} for t in timeline]
    props = _mask_case_props(plan, {k: rec[k] for k in
                                    ("stage", "bd_budget", "gross_margin",
                                     "settlement_status", "lost_reason",
                                     "terminate_reason")})
    stats = _case_stats_batch(env, plan, [cid]).get(cid)
    # 状态变更权限（spec §15）：按 permissions.yaml actions 动态判定，不硬抄角色表
    from adkg.guards.rbac import role_allows
    can_stage = role_allows(env, role, "case_stage")
    return {"case": {"id": rec["id"], "name": rec["name"], **props},
            "brand": brand, "product": product, "owners": owners,
            "campaigns": campaigns,
            "creatives": [{"id": c["id"], "name": c["name"],
                           "metrics": next((m for m in creative_rows
                                            if m["creative_id"] == c["id"]), None)}
                          for c in creatives],
            "creators": [{"id": c["id"], "name": c["name"],
                          "niches": (c["niches"] or "").split("|") if c["niches"] else [],
                          "followers": c["followers"], "quote_20s": c["quote_20s"]}
                         for c in creators],
            "stats": stats, "docs": docs, "timeline": timeline,
            "stage_flow": {"main": STAGE_FLOW, "branch": STAGE_BRANCH,
                           "current": rec["stage"]},
            "can_update_stage": can_stage}


# 状态机合法目标（schema.yaml#constraints 的展示形态，与 ActionChecker 同源语义）


@router.post("/cases/{cid}/stage")
def update_case_stage(request: Request, cid: str, body: dict,
                      role: str | None = None, user: str | None = None,
                      authorization: str | None = Header(default=None)) -> dict:
    """状态变更写操作（spec §15）：角色门按 permissions.yaml update_stage action；
    迁移合法性走 ActionChecker 状态机（terminated 必填原因）——拒绝 409 + 审计 deny，
    通过则写图（stage + 拒因）+ 审计 allow。"""
    role, person, planner = resolve_identity(request, authorization, role=role, user=user)
    from adkg.guards.rbac import role_allows
    if not role_allows(request.app.state.env, role, "case_stage"):
        raise HTTPException(403, "当前角色无案例阶段变更权限（spec §18 角色门）")
    plan = planner.plan(role, person=person)
    to_stage = str(body.get("to_stage") or "")
    reason = str(body.get("reason") or "").strip()
    graph = get_graph(request)
    with graph.session() as s:
        rec = s.run("MATCH (c:Entity {id: $id}) RETURN c.stage AS stage, c.class AS class",
                    id=cid).single()
    if not rec or rec["class"] != "Case":
        raise HTTPException(404, f"案例 {cid} 不存在")
    if plan.visible_entity_ids and cid not in plan.visible_entity_ids:
        raise HTTPException(404, "案例不在当前身份可见范围（锚点外）")
    from adkg.guards.action_check import ActionChecker
    from adkg.models import load_schema
    verdict = ActionChecker(load_schema(), graph).check(
        "update_stage", {"case_id": cid, "from_stage": rec["stage"],
                         "to_stage": to_stage,
                         **({"terminate_reason": reason} if to_stage == "terminated" else {}),
                         **({"lost_reason": reason} if to_stage == "lost" else {})})
    from adkg.guards.audit import audit
    if verdict["decision"] != "allow":
        audit(request.app.state.env, role, person, "update_stage", cid,
              "deny", verdict.get("reason", ""))
        raise HTTPException(409, verdict.get("reason", "状态机拒绝该迁移"))
    audit_id = audit(request.app.state.env, role, person, "update_stage", cid, "allow",
                     f"{rec['stage']} -> {to_stage}" + (f"（{reason}）" if reason else ""))
    with graph.session() as s:   # 写图带 provenance（§六/§12.1：audit_id 可溯源；Neo4j 属性须原子值）
        s.run("MATCH (c:Entity {id: $id}) SET c.stage = $to,"
              " c.stage_prov_source_id = $psrc, c.stage_prov_actor = $pactor,"
              " c.stage_prov_ts = $pts"
              + (", c.lost_reason = $r" if to_stage == "lost" else "")
              + (", c.terminate_reason = $r" if to_stage == "terminated" else ""),
              id=cid, to=to_stage, r=reason or None,
              psrc=f"audit:{audit_id}", pactor=person or role,
              pts=datetime.now(timezone.utc).isoformat())
    return {"ok": True, "case_id": cid, "stage": to_stage}
