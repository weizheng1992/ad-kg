"""指标口径单一来源（README §六，2026-10-23 收敛）。

Text2SQL 模板、图侧统计卡（/graph/entity stats）、权限指标列宇宙共用本模块——
改口径只动一个文件。graph.py ↔ text2sql.py 双写曾是多起口径实弹的温床
（cvr 裸 sum 出 120%、orders 按投放行数放大、词表漂移三起实弹）。
"""
from __future__ import annotations

# 视图维度列（sql/002 unified_metrics）
DIM_COLUMNS = ["platform", "date", "creative_id", "campaign_id", "case_id", "brand_id",
               "product_id"]
# 视图原生指标列（unified_metrics 实有列）
VIEW_METRICS = ["cost", "impressions", "clicks", "conversions", "ctr", "cvr", "cpa"]
# 模板/投影可选指标 = 视图列 ∪ 公式列（cpm 由 _agg_expr 现算，视图无列）
ALL_METRICS = VIEW_METRICS + ["cpm", "roi"]
# 权限矩阵的指标列宇宙（§12.4 作用域声明）——再并入仅作权限语义的 gross_margin
#（内部核算列，Case 属性与指标列两处同步 deny）
PERMISSION_METRIC_COLUMNS = ALL_METRICS + ["gross_margin"]

# 聚合口径铁律（§六）：比率型跨行聚合 = 汇总比 sum(分子)/NULLIF(sum(分母),0)，
# 禁止对行比率再求 avg——小分母行会带偏总量结论；粒度上卷同样适用
RATIO_NUM_DEN = {"ctr": ("clicks", "impressions"), "cvr": ("conversions", "clicks"),
                 "cpa": ("cost", "conversions"), "cpm": ("cost * 1000", "impressions")}
LOWER_IS_BETTER = {"cpa", "cost"}          # 成本型越低越好（方向反转判断用）
# 可算指标 = 视图原生列 ∪ 公式列；roi 需回传收入（Metric valid_scope）、
# gross_margin 仅 Case 属性——均不可算，进 SQL 即炸/空证据
COMPUTABLE_METRICS = set(VIEW_METRICS) | set(RATIO_NUM_DEN)

# 口径感知（§六 Metric）：指标词 → 统一列。匹配方按词长降序（复合词先行，
# 插入序不敏感——"转化率"先于"转化"、"千次曝光成本"先于"成本"）
METRIC_WORDS = {"点击率": "ctr", "ctr": "ctr", "转化率": "cvr", "cvr": "cvr",
                "消耗": "cost", "成本": "cost", "花费": "cost",
                "花钱": "cost", "烧钱": "cost",
                "跑量": "cost", "爆量": "cost", "投放量": "cost",
                "转化量": "conversions", "转化数": "conversions", "转化": "conversions",
                "conversions": "conversions",
                "点击": "clicks", "clicks": "clicks",
                "曝光": "impressions", "展现": "impressions", "impressions": "impressions",
                "转化成本": "cpa", "cpa": "cpa",
                "roi": "roi", "投产比": "roi", "投产": "roi",
                "毛利率": "gross_margin", "毛利": "gross_margin",
                "千次曝光": "cpm", "千次曝光成本": "cpm", "千次展现成本": "cpm", "cpm": "cpm"}
PLATFORM_WORDS = {"抖音": "douyin", "巨量": "douyin", "小红书": "xhs", "聚光": "xhs"}


def agg_expr(metric: str) -> str:
    """指标聚合表达式：比率型=汇总比（§六 铁律），总量型=sum。"""
    if metric in RATIO_NUM_DEN:
        num, den = RATIO_NUM_DEN[metric]
        return f"round(sum({num})::numeric / NULLIF(sum({den}), 0), 4)"
    return f"round(sum({metric})::numeric, 2)"


def uncomputable_note(metric: str) -> str:
    """不可算指标的降级注记（模板回落平台汇总时挂 evidence.note）。"""
    return (f"{metric} 当前不可算（视图无该列：roi 需回传收入、gross_margin 仅 Case 属性），"
            "已回退平台汇总——投放侧可问 CPA/消耗/转化")
