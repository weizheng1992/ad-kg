"""GET /graph/entity（§四 api/routes/graph.py）：实体、关系展开、来源。

供 web 图谱页与 smartServe 工具用；权限同 /ask（token 或 dev 模式，
PermissionPlan 可见集过滤）。
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.auth import AuthService

router = APIRouter()


@router.get("/graph/entity")
def graph_entity(request: Request, id: str, hops: int = 1,
                 role: str | None = None, user: str | None = None,
                 authorization: str | None = Header(default=None)) -> dict:
    env = request.app.state.env
    resolved = AuthService(env).resolve(authorization)
    if resolved:
        role = resolved[0]
    elif not (env.get("ADKG_DEV_AUTH") == "off" and role):
        raise HTTPException(401, "缺有效 service token")

    from adkg.api.routes.ask import _graph, _planner
    planner = _planner(request)
    if role not in planner.roles:                        # dev 路可传任意值，fail-closed（§十二）
        raise HTTPException(401, f"未知角色：{role}")
    graph = _graph(request)
    plan = planner.plan(role, person=user)
    visible = plan.visible_entity_ids
    allowed_classes = set(plan.metadata_filter.get("entity_class__in", []))

    with graph.session() as s:
        rec = s.run("MATCH (n:Entity {id: $id})"
                    " RETURN n.id AS id, n.class AS class, n.name AS name,"
                    " n.stage AS stage, n.authority AS authority", id=id).single()
        if not rec:
            raise HTTPException(404, f"实体 {id} 不存在")
        rows = s.run(
            "MATCH (a:Entity {id: $id})-[r]-(b:Entity) RETURN a.id AS src,"
            " type(r) AS rel, b.id AS dst, b.class AS cls, b.name AS name,"
            " r.confidence AS conf, r.prov_source AS psrc,"
            " r.authority AS auth LIMIT 100", id=id).data()

    edges, filtered = [], 0
    global_classes = {"Metric", "Guideline", "Channel"}
    for r in rows:
        if allowed_classes and r["cls"] not in allowed_classes and r["cls"] not in global_classes:
            filtered += 1
            continue
        if visible and r["dst"] not in visible and not (r["src"] in visible):
            filtered += 1
            continue
        edges.append(r)

    return {
        "entity": dict(rec),
        "neighbors": [{"id": r["dst"], "class": r["cls"], "name": r["name"],
                       "via": r["rel"], "confidence": r["conf"],
                       "provenance": {"source_type": r["psrc"], "authority": r["auth"]}}
                      for r in edges],
        "filtered": filtered,
        "role": role,
        "stats": _entity_stats(env, plan, graph, rec["class"], rec["id"]),
    }


def _entity_stats(env: dict, plan, graph, cls: str | None, entity_id: str) -> dict | None:
    """Case/Product/Creative 实体附统计卡（README §9.7）：汇总比口径（§六 铁律），
    行权限用 plan.sql_predicate 同一道闸（client 看越权对象不出数）。"""
    if cls == "Case":
        if plan.visible_entity_ids and entity_id not in plan.visible_entity_ids:
            return None                                      # fail-closed：不可见即无统计
        return _invest_stats(env, plan, "case_id", entity_id)
    if cls == "Product":
        st = _invest_stats(env, plan, "product_id", entity_id)
        if st is None:
            return None
        st.update(_trade_stats(env, plan, graph, entity_id))
        return st
    if cls == "Creative":
        return _invest_stats(env, plan, "creative_id", entity_id)
    return None


def _invest_stats(env: dict, plan, dim_col: str, entity_id: str) -> dict | None:
    """投放侧统计：unified_metrics 按 case/product 维度汇总比聚合。"""
    import psycopg
    from psycopg.rows import dict_row

    predicate = f" AND {plan.sql_predicate}" if plan.sql_predicate else ""
    try:
        with psycopg.connect(env["ADKG_PG_RO_DSN"], options="-c statement_timeout=3000",
                             row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT round(sum(cost)::numeric, 2) AS cost,"
                    " round(sum(clicks)::numeric / NULLIF(sum(impressions), 0), 4) AS ctr,"
                    " round(sum(conversions)::numeric / NULLIF(sum(clicks), 0), 4) AS cvr,"
                    " round(sum(cost)::numeric / NULLIF(sum(conversions), 0), 2) AS cpa,"
                    " string_agg(DISTINCT platform::text, ',') AS platforms,"
                    " count(*) AS days, min(date)::text AS first_day, max(date)::text AS last_day"
                    " FROM unified_metrics WHERE NOT unmatched AND "
                    f"{dim_col} = %(id)s" + predicate,
                    {"id": entity_id})
                row = cur.fetchone()
    except psycopg.Error:
        return None                                          # 统计失败不阻塞图谱（§7.2 降级）
    if not row or row["days"] == 0:
        return None
    return dict(row)


def _trade_stats(env: dict, plan, graph, product_id: str) -> dict:
    """交易侧统计（§六 交易口径分列）：orders/gmv 全量、购买率与投放 clicks 按
    product×day 对齐；仅当商品挂至少一个可见案例时展示（client fail-closed）。"""
    empty = {"orders": None, "gmv": None, "purchase_rate": None}
    if plan.visible_entity_ids:
        with graph.session() as s:
            hit = s.run(
                "MATCH (cs:Entity {class:'Case'})-[:for_product]->(p:Entity {id: $pid})"
                " WHERE cs.id IN $visible RETURN count(*) AS c LIMIT 1",
                pid=product_id, visible=sorted(plan.visible_entity_ids)).single()
        if not hit or not hit["c"]:
            return empty
    import psycopg
    from psycopg.rows import dict_row

    try:
        with psycopg.connect(env["ADKG_PG_RO_DSN"], options="-c statement_timeout=3000",
                             row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sum(o.orders) AS orders,"
                    " round(sum(o.gmv)::numeric, 2) AS gmv,"
                    " round(sum(o.orders) FILTER (WHERE u.clicks IS NOT NULL)::numeric"
                    "   / NULLIF(sum(u.clicks), 0), 4) AS purchase_rate"
                    " FROM product_orders_daily o"
                    " LEFT JOIN unified_metrics u"
                    " ON u.product_id = o.product_id AND u.date = o.date"
                    " AND NOT u.unmatched"
                    " WHERE o.product_id = %(id)s", {"id": product_id})
                row = cur.fetchone()
    except psycopg.Error:
        return empty
    return dict(row) if row and row["orders"] is not None else empty
