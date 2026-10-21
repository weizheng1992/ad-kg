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
    tables = [t for m in re.finditer(r"(?i)\b(?:from|join)\s+([a-z_][a-z0-9_.]*)", s)
              for t in [m.group(1)]]
    if any(t.split(".")[-1].rstrip(")") != view for t in tables):
        return f"表白名单（只允许 {view}）", s
    aliases = {a.lower() for a in re.findall(r"(?i)\bas\s+([a-z_][a-z0-9_]*)", s)}
    allowed = set(plan.allowed_columns) | set(DIM_COLUMNS) | aliases | {
        "t", "days", "n", "as", "and", "or", "not", "null", "is", "in", "between",
        "desc", "asc", "group", "by", "order", "limit", "where", "select", "from",
        "avg", "sum", "count", "min", "max", "round", "numeric", "distinct", "date",
        "string_agg",
        "coalesce", "case", "when", "then", "end", "else", "having", "interval", "as",
        view}
    stripped = re.sub(r"'[^']*'", "''", s)                # 剥字符串字面量再扫标识符
    for ident in re.findall(r"(?i)\b([a-z_][a-z0-9_]*)\b", stripped):
        if ident.lower() not in allowed and not ident[0].isdigit():
            return f"列 {ident} 不在白名单", s
    if not re.search(r"(?i)\blimit\s+\d+", s):
        s += " LIMIT 50"                                   # 闸 5：强制 LIMIT
    return None, s


def generate_sql(chat_json, question: str, plan) -> str | None:
    """LLM 生成 + 闸门：谓词强制（闸 4）由调用方 wrap 完成；任何失败返回 None。"""
    dims = ", ".join(DIM_COLUMNS)
    metrics = ", ".join(plan.allowed_columns) or "cost"
    predicate = (f"行权限：WHERE 必须包含 {plan.sql_predicate}。"
                 if plan.sql_predicate else "")
    try:
        sql = str(chat_json(_GEN_PROMPT % {"dims": dims, "metrics": metrics,
                                           "predicate": predicate},
                            question).get("sql", ""))
    except Exception:
        return None
    err, fixed = validate_sql(sql, plan)
    return None if err else fixed


def enforce_predicate(sql: str, plan) -> str:
    """闸 4：有行谓词而生成 SQL 未包含 → 系统包一层（不信任生成 SQL 的落点）。"""
    if not plan.sql_predicate or "brand_id" in sql.lower():
        return sql
    return f"SELECT * FROM ({sql}) t WHERE {plan.sql_predicate}"


def enforce_semantics(sql: str) -> str:
    """语义不变量系统注入（§12.5）：unmatched 行不进聚合对比——LLM 常漏，必须强制。"""
    if re.search(r"(?i)not\s+unmatched", sql):
        return sql
    if re.search(r"(?i)from\s+unified_metrics\s+where\s+", sql):
        return re.sub(r"(?i)(from\s+unified_metrics\s+where\s+)",
                      r"\1NOT unmatched AND ", sql, count=1)
    return re.sub(r"(?i)(from\s+unified_metrics)",
                  r"\1 WHERE NOT unmatched", sql, count=1)

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

# 口径感知（§六 Metric）：指标词 → 统一列；成本型越低越好、比率型越高越好
METRIC_WORDS = {"点击率": "ctr", "ctr": "ctr", "转化率": "cvr", "cvr": "cvr",
                "消耗": "cost", "成本": "cost", "花费": "cost",
                "cpa": "cpa", "roi": "roi", "千次曝光": "cpm"}
LOWER_IS_BETTER = {"cpa", "cost"}
PLATFORM_WORDS = {"抖音": "douyin", "巨量": "douyin", "小红书": "xhs", "聚光": "xhs"}


def _metric_of(question: str) -> str:
    q = question.lower()
    for word, col in METRIC_WORDS.items():
        if word in q or word in question:
            return col
    return "cpa"                                            # 缺省口径


def _direction(metric: str, question: str) -> str:
    best = "最好" in question or "最佳" in question
    asc = (metric in LOWER_IS_BETTER) == best              # 最好+成本型 → ASC
    return "ASC" if asc else "DESC"


def _platform_of(question: str) -> str | None:
    for word, p in PLATFORM_WORDS.items():
        if word in question:
            return p
    return None


def _window_of(question: str, today: date | None = None) -> tuple[str, str] | None:
    """相对时间窗 → (起, 止)；本月/上月/近N天。"""
    today = today or date.today()
    if "本月" in question:
        return (today.replace(day=1).isoformat(), today.isoformat())
    if "上月" in question or "上个月" in question or "上个号" in question:
        first = today.replace(day=1)
        prev_last = first.toordinal() - 1
        d = date.fromordinal(prev_last)
        return (d.replace(day=1).isoformat(), d.isoformat())
    m = re.search(r"近(\d+)天", question)
    if m:
        n = int(m.group(1))
        return (date.fromordinal(today.toordinal() - n + 1).isoformat(), today.isoformat())
    return None


_NUM_CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9}


def _count_of(q: str) -> int:
    """数量词 → N（top-N 模板）：阿拉伯数字直取；中文数字查表 + 十位组合（十二→12）。
    解析不了的片段跳过，整体解析不了维持默认 5。2026-10-21 线上：int('一') 曾崩穿 /ask。"""
    for m in re.findall(r"([一二三四五六七八九十两\d]+)\s*[个条]", q):
        try:
            return int(m)
        except ValueError:
            pass
        if m in _NUM_CN:                                    # 单字：一个 / 两条
            return _NUM_CN[m]
        if "十" in m:                                       # 组合：十 / 十二 / 二十三
            a, _, b = m.partition("十")
            return (_NUM_CN.get(a, 1) if a else 1) * 10 + _NUM_CN.get(b, 0)
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
    if "最差" in question or "最好" in question or "最佳" in question:
        metric = _metric_of(question)
        return "top_metric", {"n": n, "metric": metric,
                              "direction": _direction(metric, question),
                              "platform": _platform_of(question),
                              "window": _window_of(question),
                              "group": "case_id" if "案例" in question else "creative_id"}
    if "案例" in question and ("率" in q or any(w in q for w in ("cpa", "消耗", "成本", "花费"))):
        # 案例粒度统计/排名（§六 聚合口径铁律：比率型=汇总比）；"各案例"看全量
        metric = _metric_of(question)
        return "top_metric", {"n": 20 if ("各" in question or "所有" in question) else n,
                              "metric": metric,
                              "direction": _direction(metric, question),
                              "platform": _platform_of(question),
                              "window": _window_of(question),
                              "group": "case_id"}
    # 交易口径（§六 分列）：购买率/订单/GMV 走 product_orders join，与投放 cvr 不混
    if "购买率" in q or "订单" in q or "成交" in q or "gmv" in q or "销售额" in q:
        return "product_orders", {"window": _window_of(question)}
    if any(w in question for w in ("商品", "单品", "套装", "礼盒", "套餐", "年卡")) and \
            ("率" in q or any(w in q for w in ("cpa", "消耗", "成本", "花费"))):
        # 商品粒度投放统计（product_id 由 case→for_product 物化，§八）
        metric = _metric_of(question)
        return "top_metric", {"n": 20 if ("各" in question or "所有" in question) else n,
                              "metric": metric,
                              "direction": _direction(metric, question),
                              "platform": _platform_of(question),
                              "window": _window_of(question),
                              "group": "product_id"}
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
        if metric not in metrics and metric in ("cpa", "roi", "cost"):
            metric = "cpa" if "cpa" in metrics else ("cost" if "cost" in metrics else None)
        if metric and metric in metrics:
            conds2 = list(conds)
            if params.get("platform"):
                conds2.append(f"platform = '{params['platform']}'")
            if params.get("window"):
                w = params["window"]
                conds2.append(f"date BETWEEN '{w[0]}' AND '{w[1]}'")
            group = params.get("group", "creative_id")      # 粒度上卷：案例级统计（§六）
            # 案例统计常一问多指标 → 输出指标全家桶（按问句指标排序）；素材榜保持单指标
            stat_cols = ([f"{_agg_expr(c)} AS {c}" for c in ("cost", "ctr", "cvr", "cpa")
                          if c in metrics] if group == "case_id"
                         else [_agg_expr(metric) + f" AS {metric}"])
            # 案例跨平台投放 → 附覆盖平台（一案例双平台各占行，DISTINCT 聚合成一列）
            plat_col = ("string_agg(DISTINCT platform::text, ',') AS platforms, "
                        if group == "case_id" else "")
            sql = (f"SELECT {group}, {plat_col}{', '.join(stat_cols)},"
                   f" count(*) AS days FROM unified_metrics"
                   f" WHERE {' AND '.join(conds2)} GROUP BY 1 HAVING count(*) >= 3"
                   f" ORDER BY {metric} {params['direction']}"
                   f" LIMIT {min(params.get('n', 5), 50)}")   # 闸 5：强制 LIMIT
        else:                                              # 指标不在白名单 → 降级汇总
            cols = ", ".join(f"round(sum({c})::numeric, 2) AS {c}"
                             for c in metrics[:4]) or "count(*) AS rows"
            sql = (f"SELECT platform, {cols} FROM unified_metrics"
                   f" WHERE {' AND '.join(conds)} GROUP BY 1 LIMIT 20")
    elif name == "product_orders":
        # 交易模板：orders/gmv 与投放 clicks 按 product×day join 出购买率（§六 分列口径）；
        # LEFT JOIN——无投放覆盖的 SKU 仍出 orders/gmv，购买率留空（诚实，不编数）；
        # 购买率分子限定在投放覆盖天（FILTER），与分母 clicks 时间窗对齐，防虚高
        w = params.get("window")
        wcond = (f" AND o.date BETWEEN '{w[0]}' AND '{w[1]}'" if w else "")
        sql = ("SELECT o.product_id, sum(o.orders) AS orders,"
               " round(sum(o.gmv)::numeric, 2) AS gmv,"
               " round(sum(o.orders) FILTER (WHERE u.clicks IS NOT NULL)::numeric"
               "   / NULLIF(sum(u.clicks), 0), 4) AS purchase_rate"
               " FROM product_orders_daily o"
               " LEFT JOIN unified_metrics u ON u.product_id = o.product_id AND u.date = o.date"
               f" WHERE (u.unmatched = false OR u.unmatched IS NULL){wcond}"
               " GROUP BY 1 ORDER BY orders DESC LIMIT 20")
    elif name == "entity_metrics" and metrics:
        priority = [c for c in ("cpa", "ctr", "cvr", "cost") if c in metrics]
        cols = ", ".join(f"{_agg_expr(c)} AS {c}"
                         for c in priority + [m for m in metrics if m not in priority][:2])
        ids = [i for i in params["ids"] if i.startswith("Creative:")]
        sql = (f"SELECT creative_id, {cols} FROM unified_metrics"
               f" WHERE {' AND '.join(conds + ['creative_id = ANY(%(ids)s)'])} GROUP BY 1 LIMIT 50")
        params = {**params, "ids": ids or ["Creative:-"]}
    else:
        cols = ", ".join(f"round(sum({c})::numeric, 2) AS {c}" for c in metrics[:4]) or "count(*) AS rows"
        sql = (f"SELECT platform, {cols} FROM unified_metrics"
               f" WHERE {' AND '.join(conds)} GROUP BY 1 LIMIT 20")
    return sql, params


def run(question: str, plan, dsn_ro: str, entity_ids: list[str] | None = None,
        generator=None) -> dict:
    """generator（LLM chat_json）可用时走自由生成 + 五道闸；否则/失败回落模板。"""
    sql, params, source = None, None, "template"
    if generator is not None:
        gen = generate_sql(generator, question, plan)
        if gen and _named_creative_hit(question, gen):
            sql = enforce_semantics(enforce_predicate(gen, plan))
            source = "llm+五道闸"
    if sql is None:
        sql, params = build_sql(question, plan, entity_ids)
    note = None
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
            source, rows = "template(fallback)", q(sql)
        if source.startswith("llm") and not rows:         # 生成路径无结果 → 模板再试
            sql, params = build_sql(question, plan, entity_ids)
            source, rows = "template(fallback)", q(sql)
        if not rows and "BETWEEN" in sql:
            # 空窗口回退：所问时间窗无数据（权限过滤/数据窗口）→ 回退全量并注明实际覆盖范围
            rows = q(re.sub(r" AND date BETWEEN '[^']+' AND '[^']+'", "", sql))
            span = q("SELECT min(date)::text AS a, max(date)::text AS b FROM unified_metrics")
            note = (f"所问时间窗口内无可比数据，以下为全量统计"
                    f"（unified_metrics 实际覆盖 {span[0]['a']} ~ {span[0]['b']}）") if span else \
                   "所问时间窗口内无可比数据，以下为全量统计"
    return {"evidence": [{
        "type": "fact",
        "ref": f"unified_metrics · {(sql.split('FROM')[1].split()[0] if 'FROM' in sql.upper()
                                    and len(sql.split('FROM')) > 1 else 'unified_metrics')}",
        "rows": rows, "note": note, "sql_source": source,
        "provenance": {"source_type": "platform_api", "authority": 80},
    }], "row_count": len(rows)}
