"""GET /brands + /brands/{id}（spec §5 客户页）：品牌列表 + 子图详情。

可见性走 Brand 常规行权限 + 锚点豁免类闸（与 /graph/entity 同语义）：management
无行过滤全见；ae = 对接品牌；client 类白名单虽无 Brand（§12.4 逐字一致），但
external_for 锚点路径上的品牌豁免——只见自己绑定的品牌，锚点外 404。投放统计
过 plan.sql_predicate 同一道闸（指标列出口再过白名单，client 不见 cpa）。
商品段（has_product→Product）随 Product 类白名单——client 无 Product，商品卡
不返回（同一权限矩阵的副作用）。
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request
from psycopg.rows import dict_row

from adkg.guards.http import get_graph, resolve_identity
from adkg.retrieval.metrics import STAT_FAMILY, agg_expr

router = APIRouter()


def _brand_stats(env: dict, plan, brand_ids: list[str], days: int | None = None) -> dict[str, dict]:
    """unified_metrics 按 brand 汇总比聚合（§六 铁律），一道闸 + 列白名单；
    days 给定时只聚合近 N 天（spec §5 健康度窗口）。"""
    if not brand_ids:
        return {}
    predicate = f" AND {plan.sql_predicate}" if plan.sql_predicate else ""
    window = f" AND date >= current_date - {int(days)}::int" if days else ""
    try:
        proj = ", ".join(f"{agg_expr(c)} AS {c}" for c in STAT_FAMILY)
        with psycopg.connect(env["ADKG_PG_RO_DSN"], options="-c statement_timeout=3000",
                             row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT brand_id, {proj}, count(DISTINCT date) AS days"
                " FROM unified_metrics WHERE NOT unmatched"
                " AND brand_id = ANY(%(ids)s)" + window + predicate +
                " GROUP BY brand_id", {"ids": brand_ids})
            rows = cur.fetchall()
    except psycopg.Error:
        return {}                                            # 统计失败不阻塞列表（§7.2 降级）
    return {r["brand_id"]: {k: v for k, v in r.items()
                            if k not in STAT_FAMILY or k in plan.allowed_columns}
            for r in rows}


@router.get("/brands")
def list_brands(request: Request, q: str = "",
                role: str | None = None, user: str | None = None,
                authorization: str | None = Header(default=None)) -> dict:
    role, user, planner = resolve_identity(request, authorization, role=role, user=user)
    plan = planner.plan(role, person=user)
    if plan.deny_all:
        raise HTTPException(403, "行权限未生效（缺有效身份），拒绝读取")
    allowed = set(plan.metadata_filter.get("entity_class__in", []))
    visible = plan.visible_entity_ids
    if "Brand" not in allowed and not visible:
        raise HTTPException(403, "类 Brand 不在当前角色白名单")
    with get_graph(request).session() as s:
        rows = s.run("MATCH (b:Entity {class: 'Brand'}) "
                     "WHERE $q = '' OR b.name CONTAINS $q "
                     "OPTIONAL MATCH (c:Entity {class: 'Case'})-[:for_brand]->(b) "
                     "WITH b, c "
                     "RETURN b.id AS id, b.name AS name, b.category AS category, "
                     "count(DISTINCT c) AS cases_total, "
                     "sum(CASE WHEN c.stage = 'live' THEN 1 ELSE 0 END) AS cases_live, "
                     "sum(CASE WHEN c.stage = 'lost' THEN 1 ELSE 0 END) AS cases_lost "
                     "ORDER BY b.id", q=q.strip()).data()
    items = [r for r in rows if not visible or r["id"] in visible]
    if "Brand" not in allowed and not items:
        raise HTTPException(403, "类 Brand 不在当前角色白名单且锚点内无品牌")
    stats = _brand_stats(request.app.state.env, plan, [r["id"] for r in items])
    stats_30d = _brand_stats(request.app.state.env, plan, [r["id"] for r in items], days=30)
    for r in items:
        r["stats"] = stats.get(r["id"])
        r["cost_30d"] = (stats_30d.get(r["id"]) or {}).get("cost")   # 健康度窗口（spec §5）
    return {"items": items, "total": len(items)}


@router.get("/brands/{bid}")
def brand_detail(request: Request, bid: str,
                 role: str | None = None, user: str | None = None,
                 authorization: str | None = Header(default=None)) -> dict:
    role, user, planner = resolve_identity(request, authorization, role=role, user=user)
    plan = planner.plan(role, person=user)
    if plan.deny_all:
        raise HTTPException(403, "行权限未生效（缺有效身份），拒绝读取")
    allowed = set(plan.metadata_filter.get("entity_class__in", []))
    visible = plan.visible_entity_ids
    with get_graph(request).session() as s:
        rec = s.run("MATCH (b:Entity {id: $id}) RETURN b.id AS id, b.name AS name, "
                    "b.category AS category, b.class AS class", id=bid).single()
        if not rec or rec["class"] != "Brand":
            raise HTTPException(404, f"品牌 {bid} 不存在")
        # 锚点豁免类闸（client：Brand 不在类白名单但 external_for 锚点内可见）
        in_vis = bool(visible) and bid in visible
        if visible and bid not in visible:
            raise HTTPException(404, "品牌不在当前身份可见范围（锚点外）")
        if "Brand" not in allowed and not in_vis:
            raise HTTPException(403, "类 Brand 不在当前角色白名单")
        products = []
        if "Product" in allowed:
            products = s.run(
                "MATCH (b:Entity {id: $id})-[:has_product]->(p:Entity) "
                "RETURN p.id AS id, p.name AS name, p.category AS category, "
                "p.spec AS spec, p.detail AS detail, p.price AS price, "
                "p.target_age AS target_age, p.platform AS platform ORDER BY p.id",
                id=bid).data()
        # Case 属性按角色收敛：内部回 stage/lost_reason；外部（client）属性白名单只剩 stage
        external = bool(plan.allow_properties)
        cases = s.run(
            "MATCH (c:Entity {class: 'Case'})-[:for_brand]->(b:Entity {id: $id}) "
            "RETURN c.id AS id, c.name AS name, c.stage AS stage, "
            "c.lost_reason AS lost_reason, c.settlement_status AS settlement_status "
            "ORDER BY c.id", id=bid).data()
        cases = [c for c in cases if not visible or c["id"] in visible]
        if external:       # client 保留 lost_reason（spec §5；2026-10-25 审查勘误）
            cases = [{"id": c["id"], "name": c["name"], "stage": c["stage"],
                      "lost_reason": c["lost_reason"]} for c in cases]
        # 对接人（spec §14）：内部角色可见（姓名经关系边，同案例 owners 口径）；外部掩码
        owners = [] if external else [
            dict(r) for r in s.run(
                "MATCH (p:Entity)-[:belongs_to_brand]->(b:Entity {id: $id}) "
                "RETURN p.id AS id, p.name AS name ORDER BY p.id", id=bid).data()]
    env = request.app.state.env
    st = _brand_stats(env, plan, [bid]).get(bid)
    return {"brand": {"id": rec["id"], "name": rec["name"], "category": rec["category"]},
            "products": products, "cases": cases, "stats": st, "owners": owners,
            "role": role}
