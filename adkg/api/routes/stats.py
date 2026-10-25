"""GET /stats/overview（spec §5 数据看板）：大盘聚合——单一口径（metrics.py 汇总比
铁律）+ 单一道闸（plan.sql_predicate 行谓词 + allowed_columns 指标白名单）。

角色语义：management/finance 全量；ae/optimizer 限锚点案例；client 限自己品牌
（谓词随锚点展开）。达人段（Creator）随类白名单——client 无 Creator 不返回；
阶段分布（Case）对行过滤角色只计可见案例。
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Header, HTTPException, Request
from psycopg.rows import dict_row

from adkg.guards.http import get_graph, resolve_identity
from adkg.retrieval.metrics import agg_expr

router = APIRouter()
# 看板角色门（spec §4 矩阵）：矩阵外角色（creative/admin）服务端拒绝——
# 导航隐藏只是体验，不是闸（2026-10-24 复审：曾只靠 nav 兑现，直连越权）
DASHBOARD_ROLES = {"management", "ae", "optimizer", "finance", "client"}


def _metrics(env: dict, plan, days: int) -> dict:
    """unified_metrics 三视图：趋势 / 平台 / 品牌——分子分母各求和，比率不预聚合。"""
    predicate = f" AND {plan.sql_predicate}" if plan.sql_predicate else ""
    show_cost = "cost" in plan.allowed_columns
    show_conv = "conversions" in plan.allowed_columns
    cost_sel = f"{agg_expr('cost')} AS cost" if show_cost else "NULL::numeric AS cost"
    conv_sel = "sum(conversions) AS conversions" if show_conv else "NULL::numeric AS conversions"
    try:
        with psycopg.connect(env["ADKG_PG_RO_DSN"], options="-c statement_timeout=4000",
                             row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT date::text AS date, " + cost_sel + ", " + conv_sel +
                " FROM unified_metrics WHERE NOT unmatched"
                " AND date >= current_date - %(days)s::int" + predicate +
                " GROUP BY date ORDER BY date", {"days": days})
            trend = cur.fetchall()
            cur.execute(
                "SELECT platform::text AS platform, " + cost_sel + ", " + conv_sel +
                " FROM unified_metrics WHERE NOT unmatched"
                " AND date >= current_date - %(days)s::int" + predicate +
                " GROUP BY platform", {"days": days})
            platforms = cur.fetchall()
            cur.execute(
                "SELECT brand_id, " + cost_sel + ", " + conv_sel + ", count(DISTINCT case_id) AS cases"
                " FROM unified_metrics WHERE NOT unmatched"
                " AND date >= current_date - %(days)s::int" + predicate +
                " GROUP BY brand_id ORDER BY cost DESC NULLS LAST", {"days": days})
            brands = cur.fetchall()
    except psycopg.Error:
        return {"trend": [], "platforms": [], "brands": []}   # 统计失败不阻塞（§7.2 降级）
    return {"trend": trend, "platforms": platforms, "brands": brands}


def _graph_parts(request: Request, plan) -> dict:
    """图侧两段：案例阶段分布（行过滤收敛）+ 达人 Top（类白名单）。"""
    visible = plan.visible_entity_ids
    out: dict = {"stages": [], "top_creators": None}
    with get_graph(request).session() as s:
        rows = s.run("MATCH (c:Entity {class: 'Case'}) RETURN c.stage AS stage, "
                     "collect(c.id) AS ids").data()
        out["stages"] = [{"stage": r["stage"],
                          "count": len(r["ids"]) if not visible
                          else sum(1 for i in r["ids"] if i in visible)}
                         for r in rows if r["stage"]]
        if "Creator" in set(plan.metadata_filter.get("entity_class__in", [])):
            out["top_creators"] = s.run(
                "MATCH (c:Entity {class: 'Creator'}) "
                "OPTIONAL MATCH (cs:Entity {class: 'Case'})-[:collabs_with]->(c) "
                "WITH c, count(cs) AS cases "
                "WHERE cases > 0 "
                "RETURN c.id AS id, c.name AS name, c.gmv_30d AS gmv_30d, cases "
                "ORDER BY c.gmv_30d DESC LIMIT 8").data()
    return out


@router.get("/stats/overview")
def stats_overview(request: Request, days: int = 90,
                   role: str | None = None, user: str | None = None,
                   authorization: str | None = Header(default=None)) -> dict:
    role, user, planner = resolve_identity(request, authorization, role=role, user=user)
    from adkg.guards.rbac import role_allows
    if not role_allows(request.app.state.env, role, "dashboard"):
        raise HTTPException(403, "当前角色无数据看板权限（spec §18 角色门）")
    plan = planner.plan(role, person=user)
    if plan.deny_all:
        raise HTTPException(403, "行权限未生效（缺有效身份），拒绝读取")
    days = max(7, min(days, 365))
    out = _metrics(request.app.state.env, plan, days)
    out.update(_graph_parts(request, plan))
    out["role"] = role
    out["days"] = days
    return out
