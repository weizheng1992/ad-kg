"""汇总比统计查询共享助手（2026-10-27 收敛缺陷⑤⑨）。

六处 route 各抄的「unified_metrics 按案例/品牌/商品/素材维度聚合算汇总比」SQL
脚手架收拢于此：STAT_FAMILY 投影、plan.sql_predicate 同一道闸、指标列白名单
出口、psycopg.Error 降级（§7.2 统计失败不阻塞）与 statement_timeout 六处一价。
口径本体（分子分母怎么算）仍在 metrics.py——本模块只收脚手架，不收口径。

落点说明：放 retrieval 而非 store——口径词汇表（metrics.py）住本层，store 层
不逆向 import retrieval（七层单向）；查询形态与 text2sql / vector_search 同款
（pg_pool + plan + statement_timeout）。route 只留 HTTP 壳。
"""
from __future__ import annotations

import psycopg

from adkg.store import pg_pool
from psycopg.rows import dict_row

from adkg.retrieval.metrics import STAT_FAMILY, agg_expr

# statement_timeout 统一（缺陷⑤：原六处 3000/4000 漂移）——拍板取 4000ms：案例
# 批量与看板本值；其余四处由 3000 放宽 1s，只改慢查询容忍度，不改任何返回语义
STATS_TIMEOUT_MS = 4000

# STAT_FAMILY 汇总比投影（六处同款；含被白名单剥列的角色——分组排序仍按全列算）
_STAT_PROJ = ", ".join(f"{agg_expr(c)} AS {c}" for c in STAT_FAMILY)


def _predicate(plan) -> str:
    """行权限谓词（同一道闸）：plan.sql_predicate 存在则拼 AND 前缀。"""
    return f" AND {plan.sql_predicate}" if plan.sql_predicate else ""


def _allow_columns(plan, row: dict) -> dict:
    """指标列出口白名单（§12.4）：STAT_FAMILY 外的维度列（case_id/days 等）全放行。"""
    return {k: v for k, v in row.items()
            if k not in STAT_FAMILY or k in plan.allowed_columns}


def _query(env: dict, sql: str, params: dict) -> list[dict] | None:
    """单条统计查询（RO 账号 + 统一超时）；psycopg.Error → None，调用方按各自
    口径降级（None/{}/[]，§7.2 统计失败不阻塞）。"""
    try:
        with pg_pool.connect(env["ADKG_PG_RO_DSN"],
                             options=f"-c statement_timeout={STATS_TIMEOUT_MS}",
                             row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except psycopg.Error:
        return None


def case_stats_batch(env: dict, plan, case_ids: list[str]) -> dict[str, dict]:
    """案例维度批量汇总比（一条 SQL，原 cases._case_stats_batch）：/cases 列表
    与详情、/creators 详情共用（缺陷⑨跨 route import 一并消除）。"""
    if not case_ids:
        return {}
    rows = _query(
        env,
        f"SELECT case_id, {_STAT_PROJ}, string_agg(DISTINCT platform::text, ',') AS platforms,"
        " count(DISTINCT date) AS days FROM unified_metrics"
        " WHERE NOT unmatched AND case_id = ANY(%(ids)s)" + _predicate(plan) +
        " GROUP BY case_id", {"ids": case_ids})
    if rows is None:
        return {}                                            # 统计失败不阻塞列表（§7.2 降级）
    return {r["case_id"]: _allow_columns(plan, r) for r in rows}


def collab_stats(env: dict, plan, case_ids: list[str]) -> dict | None:
    """达人合作案例合并单行统计（spec §3，原 creators._collab_stats）：多案例
    上卷一行，platforms/days/首末日齐备；无数据返回 None。"""
    if not case_ids:
        return None
    rows = _query(
        env,
        f"SELECT {_STAT_PROJ}, string_agg(DISTINCT platform::text, ',') AS platforms,"
        " count(DISTINCT date) AS days, min(date)::text AS first_day,"
        " max(date)::text AS last_day FROM unified_metrics"
        " WHERE NOT unmatched AND case_id = ANY(%(ids)s)" + _predicate(plan),
        {"ids": case_ids})
    row = rows[0] if rows else None
    if not row or row["days"] == 0:
        return None
    return _allow_columns(plan, row)


def brand_stats(env: dict, plan, brand_ids: list[str],
                days: int | None = None) -> dict[str, dict]:
    """品牌维度批量汇总比（原 brands._brand_stats）：与案例批量不同形——无
    platforms 列（/brands 契约如此，保留差异不强扭）；days 给定时只聚合近
    N 天（spec §5 健康度窗口）。"""
    if not brand_ids:
        return {}
    window = f" AND date >= current_date - {int(days)}::int" if days else ""
    rows = _query(
        env,
        f"SELECT brand_id, {_STAT_PROJ}, count(DISTINCT date) AS days"
        " FROM unified_metrics WHERE NOT unmatched"
        " AND brand_id = ANY(%(ids)s)" + window + _predicate(plan) +
        " GROUP BY brand_id", {"ids": brand_ids})
    if rows is None:
        return {}                                            # 统计失败不阻塞列表（§7.2 降级）
    return {r["brand_id"]: _allow_columns(plan, r) for r in rows}


def invest_stats(env: dict, plan, dim_col: str, entity_id: str) -> dict | None:
    """单实体投放统计卡（原 graph._invest_stats）：dim_col ∈ case_id/product_id/
    creative_id（调用点固定枚举）；单实体上卷一行，与 collab_stats 同形不同维度。"""
    rows = _query(
        env,
        f"SELECT {_STAT_PROJ},"
        " string_agg(DISTINCT platform::text, ',') AS platforms,"
        " count(DISTINCT date) AS days,"
        " min(date)::text AS first_day, max(date)::text AS last_day"
        " FROM unified_metrics WHERE NOT unmatched AND "
        f"{dim_col} = %(id)s" + _predicate(plan), {"id": entity_id})
    row = rows[0] if rows else None
    if not row or row["days"] == 0:
        return None
    return _allow_columns(plan, row)


def creative_stats_by_case(env: dict, plan, case_id: str) -> list[dict]:
    """案例内素材维度明细（原 cases 详情内联块）：HAVING 滤无数据素材；cost
    DESC 排序在 SQL 侧按全列算，出口白名单照剥（排序键与可见列解耦，语义保持）。"""
    rows = _query(
        env,
        f"SELECT creative_id, string_agg(DISTINCT platform::text, ',') AS platforms,"
        f" {_STAT_PROJ} FROM unified_metrics WHERE NOT unmatched"
        f" AND case_id = %(id)s" + _predicate(plan) + " GROUP BY creative_id"
        " HAVING count(DISTINCT date) >= 1 ORDER BY cost DESC", {"id": case_id})
    if rows is None:
        return []                                            # 统计失败不阻塞详情（§7.2）
    return [_allow_columns(plan, r) for r in rows]


def overview_metrics(env: dict, plan, days: int) -> dict:
    """看板三视图（原 stats._metrics，spec §5）：趋势/平台/品牌——分子分母各
    求和，比率不预聚合。与统计卡族的实质差异（不强扭）：投影按白名单在 SQL 侧
    NULL 占位（列形固定），而非 STAT_FAMILY 事后过滤；三视图同一连接串行、
    一败全空（部分成功不外泄）。"""
    predicate = _predicate(plan)
    show_cost = "cost" in plan.allowed_columns
    show_conv = "conversions" in plan.allowed_columns
    cost_sel = f"{agg_expr('cost')} AS cost" if show_cost else "NULL::numeric AS cost"
    conv_sel = "sum(conversions) AS conversions" if show_conv else "NULL::numeric AS conversions"
    try:
        with pg_pool.connect(env["ADKG_PG_RO_DSN"],
                             options=f"-c statement_timeout={STATS_TIMEOUT_MS}",
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
