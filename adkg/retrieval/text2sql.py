"""text2sql 路（§7.3）：五道闸 + 模板生成（LLM 版留接口，规则版先兜底）。

五道闸（§四 text2sql.py 注释）：
1. 只读账号（ADKG_PG_RO_DSN）
2. 仅 SELECT——SQL 由模板拼装，问题文本永不进 SQL 字符串
3. 视图/列白名单——只打 unified_metrics，投影经 plan.allowed_columns 过滤
4. row_filter 谓词注入——plan.sql_predicate 由系统拼进 WHERE，不信任生成 SQL
5. 强制 LIMIT + 语句超时
"""
from __future__ import annotations

import re
from datetime import date

import psycopg

# ---------------------------------------------------------------- LLM 生成 + 五道闸
# 学 smartServe 的自由生成，落 AdKG 的五道闸（§7.3：不信任生成的 SQL——校验/改写后才执行）
_GEN_PROMPT = (
    "你是只读 SQL 生成器。仅基于视图 unified_metrics(%(dims)s, %(metrics)s) 写一条 "
    "PostgreSQL SELECT 回答问题；聚合函数随意（sum/avg/count/order by/group by）；"
    "口径铁律：比率型指标跨行聚合必须用汇总比 sum(分子)/NULLIF(sum(分母),0)，"
    "禁止 avg(比率列)——ctr=clicks/impressions、cvr=conversions/clicks、"
    "cpa=cost/conversions、cpm=cost*1000/impressions；"
    "按案例/素材分组统计时建议附 string_agg(DISTINCT platform::text, ',') AS platforms（覆盖平台），"
    "一案例常跨双平台投放；"
    "platform 列的值只能是 'douyin' 或 'xhs'（中文'抖音'=douyin、'小红书'=xhs）；"
    "creative_id/brand_id 等 ID 列的值带类前缀，如 'Creative:C-2025-003-cp1-cr1'、"
    "'Brand:B04'——问题里的实体 ID 原样使用；"
    "必须带 LIMIT；不要分号；只输出 JSON：{\"sql\": \"…\"}。%(predicate)s"
)


def validate_sql(sql: str, plan, *, view: str = "unified_metrics") -> tuple[str | None, str]:
    """闸 2/3/5 的静态校验与改写：返回 (错误|None, 改写后的 SQL)。"""
    s = " ".join(sql.strip().rstrip(";").split())
    if ";" in s:
        return "多语句", s
    if not re.match(r"(?i)^SELECT\b", s):
        return "仅允许 SELECT", s
    if re.search(r"(?i)\b(insert|update|delete|drop|alter|create|grant|truncate|copy|pg_|do)\b", s):
        return "含写操作或系统命令", s
    # 先剥 extract(...)——`extract(month from date)` 的 from 会撞表扫描、
    # month 等字段名会撞列扫描（prompt 推荐的日期模式曾被系统性误杀）
    s_scan = re.sub(r"(?i)extract\s*\([^)]*\)", " ", s)
    tables = [t for m in re.finditer(r"(?i)\b(?:from|join)\s+([a-z_][a-z0-9_.]*)", s_scan)
              for t in [m.group(1)]]
    if any(t.split(".")[-1].rstrip(")") != view for t in tables):
        return f"表白名单（只允许 {view}）", s
    aliases = {a.lower() for a in re.findall(r"(?i)\bas\s+([a-z_][a-z0-9_]*)", s)}
    # 别名走私闸（2026-10-22 验证）：被拒指标名作别名不得豁免列扫描——
    # deny cost 的角色，`sum(cost) AS cost` 里的 cost 引用仍须拒
    aliases -= {c for c in ALL_METRICS if c not in plan.allowed_columns}
    allowed = set(plan.allowed_columns) | set(DIM_COLUMNS) | aliases | {
        "t", "days", "n", "as", "and", "or", "not", "null", "is", "in", "between",
        "desc", "asc", "group", "by", "order", "limit", "where", "select", "from",
        "avg", "sum", "count", "min", "max", "round", "numeric", "distinct", "date",
        "string_agg", "nullif", "filter", "extract", "date_trunc", "to_char",
        "coalesce", "case", "when", "then", "end", "else", "having", "interval",
        "text", "int", "integer", "bigint", "float", "double", "precision", "varchar",
        "char", "current_date", "now", "month", "year", "quarter", "week", "day", "as",
        view}
    stripped = re.sub(r"'[^']*'", "''", s_scan)           # 剥字符串字面量再扫标识符
    for ident in re.findall(r"(?i)\b([a-z_][a-z0-9_]*)\b", stripped):
        if ident.lower() not in allowed and not ident[0].isdigit():
            return f"列 {ident} 不在白名单", s
    if not re.search(r"(?i)\blimit\s+\d+", s):
        s += " LIMIT 50"                                   # 闸 5：强制 LIMIT
    return None, s


def generate_sql(chat_json, question: str, plan) -> str | None:
    """LLM 生成 + 闸门：谓词强制（闸 4）由调用方 wrap 完成；任何失败返回 None。"""
    dims = ", ".join(DIM_COLUMNS)
    # 只向 LLM 声明可算列（视图原生 ∪ 公式列）——roi/gross_margin 视图无列，
    # 声明了只会诱导生成 sum(roi) 类必炸 SQL（2026-10-22 验证抓出）
    metrics = ", ".join(c for c in plan.allowed_columns if c in _COMPUTABLE) or "cost"
    predicate = (f"行权限：WHERE 必须包含 {plan.sql_predicate}。"
                 if plan.sql_predicate else "")
    try:
        sql = str(chat_json(_GEN_PROMPT % {"dims": dims, "metrics": metrics,
                                           "predicate": predicate},
                            question).get("sql", ""))
    except Exception:
        return None
    err, fixed = validate_sql(sql, plan)
    if err:
        return None
    # 值级越权闸：行谓词只能包裹外层——标量子查询/多表引用/窗口函数会把跨权限的
    # 聚合值带出去，静态检测到即弃用生成回模板（模板自身谓词口径安全）
    if plan.sql_predicate and (
            len(re.findall(r"(?i)\bfrom\s+unified_metrics\b", fixed)) > 1
            or re.search(r"(?i)\bover\s*\(", fixed)):
        return None
    return fixed


def enforce_predicate(sql: str, plan) -> str:
    """闸 4：行谓词一律系统包裹——生成 SQL 提到 brand_id ≠ 已施加行过滤
    （2026-10-22 验证：见字样即跳过曾让 client 跨品牌全量泄漏）。内层缺谓词列时
    执行失败自然回落模板，方向 fail-closed。"""
    if not plan.sql_predicate:
        return sql
    return f"SELECT * FROM ({sql}) t WHERE {plan.sql_predicate}"


def enforce_semantics(sql: str) -> str:
    """语义不变量系统注入（§12.5）：unmatched 行不进聚合对比——LLM 常漏，必须强制。
    兼容表别名（FROM unified_metrics AS u）——注入点在别名之后、并进已有 WHERE。"""
    if re.search(r"(?i)not\s+unmatched", sql):
        return sql
    m = re.search(r"(?i)(from\s+unified_metrics(?:\s+as\s+\w+)?)(\s+where\s+)?", sql)
    if not m:
        return sql
    if m.group(2):
        return sql[:m.start(2)] + " WHERE NOT unmatched AND " + sql[m.end(2):]
    return sql[:m.end(1)] + " WHERE NOT unmatched" + sql[m.end(1):]

DIM_COLUMNS = ["platform", "date", "creative_id", "campaign_id", "case_id", "brand_id",
               "product_id"]
ALL_METRICS = ["cost", "impressions", "clicks", "conversions", "ctr", "cvr", "cpa", "cpm", "roi"]

# 聚合口径铁律（README §六）：比率型指标跨行聚合 = 汇总比 sum(分子)/sum(分母)，
# 禁止对行比率再求 avg——小分母行会带偏总量结论；粒度上卷（case/campaign/brand）同样适用
_RATIO_NUM_DEN = {"ctr": ("clicks", "impressions"), "cvr": ("conversions", "clicks"),
                  "cpa": ("cost", "conversions"), "cpm": ("cost * 1000", "impressions")}


def _agg_expr(metric: str) -> str:
    """指标聚合表达式：比率型=汇总比，总量型=sum。"""
    if metric in _RATIO_NUM_DEN:
        num, den = _RATIO_NUM_DEN[metric]
        return f"round(sum({num})::numeric / NULLIF(sum({den}), 0), 4)"
    return f"round(sum({metric})::numeric, 2)"

# 口径感知（§六 Metric）：指标词 → 统一列；成本型越低越好、比率型越高越好。
# _metric_of 按词长降序匹配——复合词（转化成本/千次曝光成本/转化率）必先于短词命中，
# 词表插入序不再敏感（2026-10-22 验证：插入序曾让"成本"截胡"千次曝光成本"）
METRIC_WORDS = {"点击率": "ctr", "ctr": "ctr", "转化率": "cvr", "cvr": "cvr",
                "消耗": "cost", "成本": "cost", "花费": "cost",
                "花钱": "cost", "烧钱": "cost",                       # 口径同 cost（夜检 A11）
                "跑量": "cost", "爆量": "cost", "投放量": "cost",
                "转化量": "conversions", "转化数": "conversions", "转化": "conversions",
                "conversions": "conversions",
                "点击": "clicks", "clicks": "clicks",
                "曝光": "impressions", "展现": "impressions", "impressions": "impressions",
                "转化成本": "cpa", "cpa": "cpa",
                "roi": "roi", "投产比": "roi", "投产": "roi",
                "毛利率": "gross_margin", "毛利": "gross_margin",
                "千次曝光": "cpm", "千次曝光成本": "cpm", "千次展现成本": "cpm", "cpm": "cpm"}
LOWER_IS_BETTER = {"cpa", "cost"}
PLATFORM_WORDS = {"抖音": "douyin", "巨量": "douyin", "小红书": "xhs", "聚光": "xhs"}
# 可算指标 = 视图原生列（sql/002）∪ _RATIO_NUM_DEN 公式列（cpm 现算）；
# roi 需回传收入数据（schema valid_scope）、gross_margin 仅 Case 属性——均不可算
_COMPUTABLE = {"cost", "impressions", "clicks", "conversions", "ctr", "cvr", "cpa", "cpm"}


def _uncomputable_note(metric: str) -> str:
    return (f"{metric} 当前不可算（视图无该列：roi 需回传收入、gross_margin 仅 Case 属性），"
            "已回退平台汇总——投放侧可问 CPA/消耗/转化")


def _metric_of(question: str) -> str:
    q = question.lower()
    for word, col in sorted(METRIC_WORDS.items(), key=lambda kv: -len(kv[0])):
        if word in q or word in question:
            return col
    return "cpa"                                            # 缺省口径


def _direction(metric: str, question: str) -> str:
    if any(w in question for w in ("最高", "最多", "最大", "最凶", "最猛")):
        return "DESC"                       # 绝对方向词：不随成本型反转（夜检 D2）
    if any(w in question for w in ("最低", "最少", "最小")):
        return "ASC"
    if not any(w in question for w in ("最差", "最好", "最佳")):
        return "DESC"          # 裸排名/统计题：多的在前（无方向词曾排成最差优先）
    best = "最好" in question or "最佳" in question
    asc = (metric in LOWER_IS_BETTER) == best              # 最好+成本型 → ASC
    return "ASC" if asc else "DESC"


def _platform_of(question: str) -> str | None:
    for word, p in PLATFORM_WORDS.items():
        if word in question:
            return p
    return None


_DUR_DAYS = {"天": 1, "日": 1, "周": 7, "月": 30}         # 口语月 = 30 天（与"最近一个月"口径一致）


def _cn_num(s: str) -> int | None:
    """中文/阿拉伯数字 → int；单字查表 + 十位组合（十二→12）；解析不了返回 None。"""
    if s.isdigit():
        return int(s)
    if s in _NUM_CN:
        return _NUM_CN[s]
    if "十" in s:
        a, _, b = s.partition("十")
        return (_NUM_CN.get(a, 1) if a else 1) * 10 + _NUM_CN.get(b, 0)
    return None


def _window_of(question: str, today: date | None = None) -> tuple[str, str] | None:
    """相对时间窗 → (起, 止)。本月/上月/昨天/今天/前天/本周/上周 +
    泛化时长（最?近|过去 N 天/日/周/月，中文数字可，月=30天、周=7天）。"""
    today = today or date.today()
    if "本月" in question or "这个月" in question or "这月" in question:
        return (today.replace(day=1).isoformat(), today.isoformat())
    if "上周" in question:
        mon = today.toordinal() - today.weekday() - 7      # 周一为一周之始
        return (date.fromordinal(mon).isoformat(), date.fromordinal(mon + 6).isoformat())
    if "本周" in question or "这周" in question:
        mon = today.toordinal() - today.weekday()
        return (date.fromordinal(mon).isoformat(), today.isoformat())
    if "上月" in question or "上个月" in question or "上个号" in question:
        first = today.replace(day=1)
        d = date.fromordinal(first.toordinal() - 1)
        return (d.replace(day=1).isoformat(), d.isoformat())
    for w in ("前天", "昨天", "今天"):                      # 单日窗
        if w in question:
            ds = date.fromordinal(today.toordinal() - ("前天", "昨天", "今天").index(w))
            return (ds.isoformat(), ds.isoformat())
    m = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", question)   # 绝对年月窗
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            last = date(y + (mo == 12), mo % 12 + 1, 1).toordinal() - 1
            return (date(y, mo, 1).isoformat(), date.fromordinal(last).isoformat())
    m = re.search(r"(20\d{2})\s*年", question)              # 绝对年份窗
    if m:
        y = int(m.group(1))
        return (date(y, 1, 1).isoformat(), date(y, 12, 31).isoformat())
    m = re.search(r"(?:最?近|过去)\s*([0-9一二两三四五六七八九十]+)\s*个?\s*(天|日|周|月)", question)
    if m:
        n = _cn_num(m.group(1))
        if n:
            days = n * _DUR_DAYS[m.group(2)]
            return (date.fromordinal(today.toordinal() - days + 1).isoformat(),
                    today.isoformat())
    return None


_NUM_CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9}


def _count_of(q: str) -> int:
    """数量词 → N（top-N 模板）：阿拉伯数字直取；中文数字查表 + 十位组合（十二→12）。
    解析不了的片段跳过，整体解析不了维持默认 5。2026-10-21 线上：int('一') 曾崩穿 /ask；
    2026-10-22：「最近一个月」的"一个"是时长不是计数——仅当前接时间指示词（近/前/去/这/上）
    且后接月/年/周时跳过（"三个月饼"仍计 3）。"""
    m_top = re.search(r"top\s*(\d+)", q)
    if m_top:                                              # top3 / top 5 的 N 直取
        return int(m_top.group(1))
    for m in re.finditer(r"([一二三四五六七八九十两\d]+)\s*[个条]", q):
        pre = q[max(0, m.start() - 1):m.start()]
        if pre in ("近", "前", "去", "这", "上") and q[m.end():m.end() + 1] in ("月", "年", "周"):
            continue
        n = _cn_num(m.group(1))
        if n:
            return n
    return 5


_SLUG_RE = re.compile(r"(creative_\w+|[A-Z](?:-\d+)+-cp\d+-cr\d+)")


def _named_creative_of(question: str) -> str | None:
    """问题里点名的素材（creative_992 / C-2025-003-cp1-cr1 两种叫法）。"""
    m = _SLUG_RE.search(question)
    return m.group(1) if m else None


def _named_creative_hit(question: str, sql: str) -> bool:
    """点名素材的题，生成 SQL 必须真落在该素材上：SELECT 段带 creative_id 列（证据
    可溯源到实体）+ slug 字面量在场（确证按该素材过滤）。静态五道闸拦不住"全局
    均值冒充单素材答案"，这道口径闸不过就弃用生成、回模板（2026-10-20 评测实测）。"""
    slug = _named_creative_of(question)
    if not slug:
        return True
    select_part = sql.lower().split("from")[0]
    return slug in sql and "creative_id" in select_part


def _template(question: str, entity_ids: list[str] | None) -> tuple[str, dict]:
    """问题 → (模板名, 参数)。模板是固定 SQL 骨架，只有参数可变。"""
    q = question.lower()
    n = _count_of(q)
    # 问题里点名具体素材（"X 的平均 CPA"）→ 单素材模板
    slug = _named_creative_of(question)
    if slug and ("cpa" in q or "平均" in question or "多少" in question):
        return "entity_metrics", {"ids": [f"Creative:{slug}"]}
    # 交易口径（§六 分列）：购买率/订单/GMV/卖得类 走 product_orders join，与投放 cvr 不混；
    # 必须先于排名词——"购买率最高""卖得最好"是交易语义，落 top_metric 会问交易答投放（夜检 D7）
    if "购买率" in question or "订单" in question or "成交" in question or "gmv" in q \
            or "销售额" in question or any(w in question for w in
                                           ("卖得", "卖了", "好卖", "销量", "热销", "畅销")):
        return "product_orders", {"window": _window_of(question)}
    # 排名语义：方向/名次词 → top-N；粒度按问句实体词判（商品/品牌/案例/计划），缺省素材——
    # 粒度判定收在排名分支内，交易分支前移后不再漏商品粒度（2026-10-22 验证回归抓出）
    if any(w in question for w in ("最差", "最好", "最佳", "最高", "最低", "最多", "最少",
                                   "最大", "最小", "最凶", "最猛", "排名")) or "top" in q:
        metric = _metric_of(question)
        # 粒度取问句最右的实体词（中心词）——"案例展现最多的计划"问的是计划；
        # 素材/创意也要进候选，否则"品牌下消耗最高的素材"被品牌劫持
        grains = []
        for words, dim in ((("案例",), "case_id"),
                           (("商品", "单品", "套装", "礼盒", "套餐", "年卡"), "product_id"),
                           (("品牌",), "brand_id"),
                           (("计划",), "campaign_id"),
                           (("素材", "创意", "物料"), "creative_id")):
            hit_words = tuple(w for w in words if w in question)
            if hit_words:
                grains.append((max(question.rfind(w) for w in hit_words), dim))
        group = max(grains)[1] if grains else "creative_id"
        return "top_metric", {"n": 20 if ("各" in question or "所有" in question) else n,
                              "metric": metric,
                              "direction": _direction(metric, question),
                              "platform": _platform_of(question),
                              "window": _window_of(question),
                              "group": group}
    _stat_words = ("cpa", "消耗", "成本", "花费", "转化", "点击", "曝光", "展现",
                   "跑量", "爆量", "投放量")
    if "案例" in question and ("率" in q or any(w in q for w in _stat_words)):
        # 案例粒度统计/排名（§六 聚合口径铁律：比率型=汇总比）；"各案例"看全量
        metric = _metric_of(question)
        return "top_metric", {"n": 20 if ("各" in question or "所有" in question) else n,
                              "metric": metric,
                              "direction": _direction(metric, question),
                              "platform": _platform_of(question),
                              "window": _window_of(question),
                              "group": "case_id"}
    if (any(w in question for w in ("商品", "单品", "套装", "礼盒", "套餐", "年卡", "品牌"))
            and ("率" in q or any(w in q for w in _stat_words))):
        # 商品/品牌粒度投放统计（product_id 由 case→for_product 物化，§八）
        metric = _metric_of(question)
        return "top_metric", {"n": 20 if ("各" in question or "所有" in question) else n,
                              "metric": metric,
                              "direction": _direction(metric, question),
                              "platform": _platform_of(question),
                              "window": _window_of(question),
                              "group": "brand_id" if "品牌" in question else "product_id"}
    if entity_ids:                                        # 归因串行：graph 圈的实体作条件
        return "entity_metrics", {"ids": entity_ids}
    return "platform_summary", {}


def build_sql(question: str, plan, entity_ids: list[str] | None = None) -> tuple[str, dict]:
    name, params = _template(question, entity_ids)
    metrics = [c for c in ALL_METRICS if c in plan.allowed_columns]
    predicate = plan.sql_predicate                        # 闸 4：系统拼接的行谓词
    conds = ["NOT unmatched"]
    if predicate:
        conds.append(predicate)
    if name == "top_metric":
        metric = params["metric"]                           # 口径感知的 top-N（§六 Metric）
        note = None
        if metric not in _COMPUTABLE:                       # roi/毛利率等：视图无列也无公式
            metric, note = None, _uncomputable_note(metric)
        elif metric not in metrics and metric in ("cpa", "cost"):
            metric = "cpa" if "cpa" in metrics else ("cost" if "cost" in metrics else None)
        if metric and metric in metrics:
            conds2 = list(conds)
            if params.get("platform"):
                conds2.append(f"platform = '{params['platform']}'")
            if params.get("window"):
                w = params["window"]
                conds2.append(f"date BETWEEN '{w[0]}' AND '{w[1]}'")
            group = params.get("group", "creative_id")      # 粒度上卷：案例级统计（§六）
            # 案例统计常一问多指标 → 输出指标全家桶（按问句指标排序）；素材榜保持单指标；
            # 所问指标不在家族四列时追加进投影——ORDER BY 裸列引用投影外列会 42803
            stat_cols = ([f"{_agg_expr(c)} AS {c}" for c in ("cost", "ctr", "cvr", "cpa")
                          if c in metrics] if group == "case_id"
                         else [_agg_expr(metric) + f" AS {metric}"])
            if group == "case_id" and metric not in ("cost", "ctr", "cvr", "cpa"):
                stat_cols.append(_agg_expr(metric) + f" AS {metric}")
            # 案例跨平台投放 → 附覆盖平台（一案例双平台各占行，DISTINCT 聚合成一列）
            plat_col = ("string_agg(DISTINCT platform::text, ',') AS platforms, "
                        if group == "case_id" else "")
            # days = 投放天数：行粒度是 creative×platform×day，count(*) 会按行数虚高
            sql = (f"SELECT {group}, {plat_col}{', '.join(stat_cols)},"
                   f" count(DISTINCT date) AS days FROM unified_metrics"
                   f" WHERE {' AND '.join(conds2)} GROUP BY 1"
                   f" HAVING count(DISTINCT date) >= 3"
                   f" ORDER BY {metric} {params['direction']}"
                   f" LIMIT {min(params.get('n', 5), 50)}")   # 闸 5：强制 LIMIT
        else:                                              # 指标不在白名单/不可算 → 降级汇总
            cols = ", ".join(_agg_expr(c) + f" AS {c}"
                             for c in metrics[:4]) or "count(*) AS rows"
            sql = (f"SELECT platform, {cols} FROM unified_metrics"
                   f" WHERE {' AND '.join(conds)} GROUP BY 1 LIMIT 20")
            params = {**params, "note": note} if note else params
    elif name == "product_orders":
        # 交易模板：orders/gmv 与投放 clicks 按 product×day join 出购买率（§六 分列口径）；
        # 投放侧先预聚合到 product×day——unified 粒度是 creative×platform×day，直接 join
        # 会把 orders/gmv 按投放行数放大（2026-10-22 夜检抓出，graph.py 同款同修）；
        # LEFT JOIN——无投放覆盖的 SKU 仍出 orders/gmv，购买率留空（诚实，不编数）；
        # 购买率分子限定在投放覆盖天（FILTER），与分母 clicks 时间窗对齐，防虚高；
        # 行权限：谓词注入预聚合内（案例/品牌维度都在 unified 行上），且用产品级半连接
        # 只留权限内有投放的产品——权限内产品的 orders/gmv 仍是全量（与统计卡口径一致），
        # 权限外产品一行不出（fail-closed，§12.4）
        w = params.get("window")
        wcond = (f" AND o.date BETWEEN '{w[0]}' AND '{w[1]}'" if w else "")
        pcond = (f" AND {predicate}" if predicate else "")
        cover = (" AND o.product_id IN (SELECT product_id FROM uc)" if predicate else "")
        if "购买率" in question:
            order_key = "purchase_rate"
        elif "gmv" in question.lower() or "成交" in question or "销售额" in question:
            order_key = "gmv"
        else:
            order_key = "orders"
        asc = any(w in question for w in ("最低", "最少", "最差", "最小"))
        # uc 走 CTE：半连接要在 WHERE 里引用它，join 别名进不了子查询 FROM（实测 UndefinedTable）
        sql = ("WITH uc AS (SELECT product_id, date, sum(clicks) AS clicks"
               "   FROM unified_metrics"
               f"  WHERE NOT unmatched{pcond} GROUP BY 1, 2)"
               " SELECT o.product_id, sum(o.orders) AS orders,"
               " round(sum(o.gmv)::numeric, 2) AS gmv,"
               " round(sum(o.orders) FILTER (WHERE uc.clicks IS NOT NULL)::numeric"
               "   / NULLIF(sum(uc.clicks), 0), 4) AS purchase_rate"
               " FROM product_orders_daily o LEFT JOIN uc"
               " ON uc.product_id = o.product_id AND uc.date = o.date"
               f" WHERE TRUE{wcond}{cover}"
               f" GROUP BY 1 ORDER BY {order_key}"
               f" {'ASC NULLS LAST' if asc else 'DESC NULLS LAST'} LIMIT 20")
    elif name == "entity_metrics" and metrics:
        priority = [c for c in ("cpa", "ctr", "cvr", "cost") if c in metrics]
        cols = ", ".join(f"{_agg_expr(c)} AS {c}"
                         for c in priority + [m for m in metrics if m not in priority][:2])
        ids = [i for i in params["ids"] if i.startswith("Creative:")]
        sql = (f"SELECT creative_id, {cols} FROM unified_metrics"
               f" WHERE {' AND '.join(conds + ['creative_id = ANY(%(ids)s)'])} GROUP BY 1 LIMIT 50")
        params = {**params, "ids": ids or ["Creative:-"]}
    else:
        # 平台汇总：投影一律 _agg_expr——比率列汇总比，禁止裸 sum(ctr/cvr)（§六 铁律，
        # 2026-10-22 验证抓出裸 sum 曾给出 cvr=1.2 的不可能值）
        cols = ", ".join(_agg_expr(c) + f" AS {c}" for c in metrics[:4]) or "count(*) AS rows"
        sql = (f"SELECT platform, {cols} FROM unified_metrics"
               f" WHERE {' AND '.join(conds)} GROUP BY 1 LIMIT 20")
        m = _metric_of(question)                            # 非排名 roi 问句同样注记不可算
        if m not in _COMPUTABLE:
            params = {**params, "note": _uncomputable_note(m)}
    return sql, params


def run(question: str, plan, dsn_ro: str, entity_ids: list[str] | None = None,
        generator=None) -> dict:
    """generator（LLM chat_json）可用时走自由生成 + 五道闸；否则/失败回落模板。
    模板自身不可执行时降级为空证据 + note——事实路永不把异常抛给 /ask
    （2026-10-22 验证：问 roi 曾生成 sum(roi) 必炸 SQL，fallback 重放同款直接 500）。"""
    sql, params, source = None, None, "template"
    if generator is not None:
        gen = generate_sql(generator, question, plan)
        m = _metric_of(question)
        if gen and m not in _COMPUTABLE:
            # 不可算指标（视图无列）在生成 SQL 里裸出现即伪造——隐式别名
            # `(cost/conversions) roi`、引号别名 "ROI" 一并覆盖，弃用回模板降级+note
            if re.search(rf"(?i)\b{m}\b", re.sub(r"'[^']*'", "''", gen)):
                gen = None
        if gen and _named_creative_hit(question, gen):
            sql = enforce_semantics(enforce_predicate(gen, plan))
            source = "llm+五道闸"

    def _drain_note(p):
        return p.pop("note", None) if isinstance(p, dict) else None

    if sql is None:
        sql, params = build_sql(question, plan, entity_ids)
    note = _drain_note(params)
    with psycopg.connect(dsn_ro, options="-c statement_timeout=3000") as conn:   # 闸 1 + 5
        def q(stmt: str):
            with conn.cursor() as cur:
                cur.execute(stmt, params)                 # 闸 2/3：校验后的生成 SQL 或模板
                cols = [d.name for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        try:
            rows = q(sql)
            if rows and all(v is None for v in rows[0].values()):
                rows = []                                 # 空集聚合的 NULL 行视同无结果
        except psycopg.Error:                             # 生成 SQL 执行失败 → 回落模板
            conn.rollback()                               # 先解除中止态，再执行模板
            sql, params = build_sql(question, plan, entity_ids)
            source, rows = "template(fallback)", []
            note = _drain_note(params) or note
            try:
                rows = q(sql)
            except psycopg.Error:                         # 模板自身不可执行 → 空证据降级
                conn.rollback()
                rows = []
                note = note or "事实路无可执行口径，已降级为空证据"
        if source.startswith("llm"):
            # 生成路径无结果，或行谓词包裹在内层 LIMIT 之后导致"全局 top-N ∩ 权限"的
            # 子集冒充完整榜（行数 < LIMIT 即被截断）→ 模板再试（谓词在模板里天然在内）
            lim = re.search(r"(?i)limit\s+(\d+)", sql)
            partial = bool(plan.sql_predicate and rows and lim
                           and len(rows) < int(lim.group(1)))
            if not rows or partial:
                sql, params = build_sql(question, plan, entity_ids)
                source, rows = "template(fallback)", []
                note = _drain_note(params) or note
                try:
                    rows = q(sql)
                except psycopg.Error:
                    conn.rollback()
                    rows = []
                    note = note or "事实路查询失败，已降级为空证据"
        if not rows and "BETWEEN" in sql:
            # 空窗口回退：所问时间窗无数据（权限过滤/数据窗口）→ 回退全量并注明实际覆盖；
            # 回退仍无数据则如实说明（权限内无数据），不谎称"以下为全量统计"；
            # 正则兼容 o.date 别名（product_orders 模板的时间谓词带表别名）
            try:
                rows = q(re.sub(r" AND (?:o\.)?date BETWEEN '[^']+' AND '[^']+'", "", sql))
                if rows:
                    # span 按当前 SQL 主表取——交易模板的回退行来自 product_orders_daily
                    span_tbl = ("product_orders_daily" if "product_orders_daily" in sql
                                else "unified_metrics")
                    span = q(f"SELECT min(date)::text AS a, max(date)::text AS b"
                             f" FROM {span_tbl}")
                    note = (f"所问时间窗口内无可比数据，以下为全量统计"
                            f"（{span_tbl} 实际覆盖 {span[0]['a']} ~ {span[0]['b']}）"
                            ) if span else "所问时间窗口内无可比数据，以下为全量统计"
                elif not note:
                    note = "所问时间窗口与行权限范围内均无可比数据"
            except psycopg.Error:
                conn.rollback()
                rows = []
    return {"evidence": [{
        "type": "fact",
        "ref": f"unified_metrics · {(sql.split('FROM')[1].split()[0] if 'FROM' in sql.upper()
                                    and len(sql.split('FROM')) > 1 else 'unified_metrics')}",
        "rows": rows, "note": note, "sql_source": source,
        "provenance": {"source_type": "platform_api", "authority": 80},
    }], "row_count": len(rows)}
