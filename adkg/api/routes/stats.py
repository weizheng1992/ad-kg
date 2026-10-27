"""GET /stats/overview（spec §5 数据看板）：大盘聚合——单一口径（metrics.py 汇总比
铁律）+ 单一道闸（plan.sql_predicate 行谓词 + allowed_columns 指标白名单）。

角色语义：management/finance 全量；ae/optimizer 限锚点案例；client 限自己品牌
（谓词随锚点展开）。达人段（Creator）随类白名单——client 无 Creator 不返回；
阶段分布（Case）对行过滤角色只计可见案例。
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.http import get_graph, resolve_identity
from adkg.retrieval.stats import overview_metrics

router = APIRouter()
# 看板角色门（spec §4 矩阵）：门判收口 rbac.role_allows("dashboard")（display_role，
# 原散抄 DASHBOARD_ROLES 常量已废——2026-10-26 夜检死代码清理）


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
    from adkg.guards.rbac import require
    require(request, authorization, gate="dashboard", role=role, user=user,
            message="当前角色无数据看板权限（spec §18 角色门）")
    plan = planner.plan(role, person=user)
    if plan.deny_all:
        raise HTTPException(403, "行权限未生效（缺有效身份），拒绝读取")
    days = max(7, min(days, 365))
    out = overview_metrics(request.app.state.env, plan, days)
    out.update(_graph_parts(request, plan))
    out["role"] = role
    out["days"] = days
    return out
