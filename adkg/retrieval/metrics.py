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

# —— 最X/方向词族（排名语义，§六 方向反转）：router 意图词（_FACT/_DEF_EXCLUDE）与
# text2sql 排名/方向判定的单一来源（2026-10-24 收敛：此前三处各抄一份，加词曾三处
# 漂移）——加词只改这里，两端自动跟随
HIGH_WORDS = ("最高", "最多", "最大", "最凶", "最猛")     # 绝对高向：不随成本型反转
LOW_WORDS = ("最低", "最少", "最小")                      # 绝对低向
# 好坏向：按成本型反转（§六）。"效果差"不带"最"也是排名语义（G14 实弹：缺此词时
# 模板落到平台汇总/entity_metrics，"CPA 排序的素材清单"证据点永远缺席）
VALENCE_WORDS = ("最差", "最好", "最佳", "效果差")
RANK_WORDS = HIGH_WORDS + LOW_WORDS + VALENCE_WORDS + ("排名",)   # 排名语义全集
TRADE_ASC_WORDS = LOW_WORDS + ("最差",)   # 交易模板方向：orders/gmv 无成本型，最差=最少

# 案例统计全家桶（§六）：一问多指标的默认投影族——graph 统计卡与 text2sql 案例粒度
# top_metric 共用（曾两处硬编码 ("cost","ctr","cvr","cpa")）
STAT_FAMILY = ("cost", "ctr", "cvr", "cpa")
# top-1 窗口查询的"多天覆盖"阈值（HAVING）——text2sql top_metric 模板与 recalc_*
# 锚点重算共用一价（改阈值动一处；曾三处字面同形漂移隐患，2026-10-31 收口）
STAT_HAVING = "HAVING count(DISTINCT date) >= 3"

# —— 交易口径（§六 分列）：orders/gmv 与投放 clicks 按 product×day 对齐 ——
# unified 粒度是 creative×platform×day，直接 join 会把 orders/gmv 按投放行数放大
# （2026-10-22 夜检抓出，graph 统计卡与 text2sql 模板同款同修；2026-10-24 形状收口
# 进本模块）。购买率分子限定在投放覆盖天（FILTER），与分母 clicks 时间窗对齐，防虚高
TRADE_SELECT = ("sum(o.orders) AS orders, round(sum(o.gmv)::numeric, 2) AS gmv, "
                "round(sum(o.orders) FILTER (WHERE uc.clicks IS NOT NULL)::numeric"
                " / NULLIF(sum(uc.clicks), 0), 4) AS purchase_rate")


def uc_clicks_sql(where: str, *, with_product: bool) -> str:
    """投放侧 clicks 预聚合（上卷到 product×day / 单产品 day）——graph 统计卡与
    text2sql 交易模板共用的 uc 子查询体（调用方自行包 CTE/括号与命名 uc）。"""
    cols = "product_id, date" if with_product else "date"
    group = "1, 2" if with_product else "1"
    return (f"SELECT {cols}, sum(clicks) AS clicks FROM unified_metrics"
            f" WHERE {where} GROUP BY {group}")


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
