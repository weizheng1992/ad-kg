"""GET /settlements（spec §5 财务结算中心）：Case 结算视图 + 达人合作成本。

角色门 SETTLE_ROLES = {management, finance}（spec §4 页面矩阵；属性级口径见
README §9.2——毛利/结算状态对 finance 可见）。达人成本 = collabs_with 达人
quote_20s 之和（种子无逐单成交价，按报价上界估计，前端标注「估」）。
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.http import get_graph, resolve_identity

router = APIRouter()
SETTLE_ROLES = {"management", "finance"}


@router.get("/settlements")
def settlements(request: Request, status: str = "", brand: str = "", stage: str = "",
                role: str | None = None, user: str | None = None,
                authorization: str | None = Header(default=None)) -> dict:
    role, user, _planner = resolve_identity(request, authorization, role=role, user=user)
    if role not in SETTLE_ROLES:
        raise HTTPException(403, "结算中心仅 management / finance 可用（spec §4）")
    with get_graph(request).session() as s:
        rows = s.run(
            "MATCH (c:Entity {class: 'Case'})-[:for_brand]->(b:Entity) "
            "OPTIONAL MATCH (c)-[:collabs_with]->(cr:Entity {class: 'Creator'}) "
            "WITH c, b, collect(DISTINCT cr) AS creators "
            "RETURN c.id AS case_id, c.name AS case_name, c.stage AS stage, "
            "c.settlement_status AS settlement_status, c.bd_budget AS bd_budget, "
            "c.gross_margin AS gross_margin, "
            "b.id AS brand_id, b.name AS brand_name, "
            "size(creators) AS creator_count, "
            "reduce(s = 0, cr IN creators | s + coalesce(cr.quote_20s, 0)) AS creator_cost "
            "ORDER BY c.id").data()
    items = [r for r in rows
             if (not status or r["settlement_status"] == status)
             and (not brand or brand in (r["brand_id"], r["brand_name"]))
             and (not stage or r["stage"] == stage)]
    budget_total = sum(int(r["bd_budget"] or 0) for r in items)
    creator_cost_total = sum(r["creator_cost"] or 0 for r in items)
    paid = sum(1 for r in items if r["settlement_status"] == "paid")
    return {"items": items, "total": len(items),
            "summary": {"budget_total": budget_total, "creator_cost_total": creator_cost_total,
                        "paid": paid, "unbilled": len(items) - paid}}
