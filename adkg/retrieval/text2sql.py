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

DIM_COLUMNS = ["platform", "date", "creative_id", "campaign_id", "case_id", "brand_id"]
ALL_METRICS = ["cost", "impressions", "clicks", "conversions", "ctr", "cvr", "cpa", "cpm", "roi"]

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


def _template(question: str, entity_ids: list[str] | None) -> tuple[str, dict]:
    """问题 → (模板名, 参数)。模板是固定 SQL 骨架，只有参数可变。"""
    q = question.lower()
    n = next((int(x) for x in re.findall(r"([一二三四五六七八九十\d]+)\s*[个条]", q)), 5)
    # 问题里点名具体素材（"X 的平均 CPA"）→ 单素材模板
    slug = re.search(r"(creative_\w+|[A-Z]{1}\d{3}-cp\d-cr\d)", question)
    if slug and ("cpa" in q or "平均" in question or "多少" in question):
        return "entity_metrics", {"ids": [f"Creative:{slug.group(1)}"]}
    if "最差" in question or "最好" in question or "最佳" in question:
        metric = _metric_of(question)
        return "top_metric", {"n": n, "metric": metric,
                              "direction": _direction(metric, question),
                              "platform": _platform_of(question),
                              "window": _window_of(question)}
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
            sql = (f"SELECT creative_id, round(avg({metric})::numeric, 4) AS avg_{metric},"
                   f" count(*) AS days FROM unified_metrics"
                   f" WHERE {' AND '.join(conds2)} GROUP BY 1 HAVING count(*) >= 3"
                   f" ORDER BY avg_{metric} {params['direction']}"
                   f" LIMIT {min(params.get('n', 5), 50)}")   # 闸 5：强制 LIMIT
        else:                                              # 指标不在白名单 → 降级汇总
            cols = ", ".join(f"round(sum({c})::numeric, 2) AS {c}"
                             for c in metrics[:4]) or "count(*) AS rows"
            sql = (f"SELECT platform, {cols} FROM unified_metrics"
                   f" WHERE {' AND '.join(conds)} GROUP BY 1 LIMIT 20")
    elif name == "entity_metrics" and metrics:
        priority = [c for c in ("cpa", "ctr", "cvr", "cost") if c in metrics]
        cols = ", ".join(f"round(avg({c})::numeric, 2) AS {c}"
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
        if gen:
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
            # 空窗口回退：所问自然月无数据（演示数据窗口错位）→ 回退全量并注明
            rows = q(re.sub(r" AND date BETWEEN '[^']+' AND '[^']+'", "", sql))
            note = "所问时间窗口内无数据，以下为全量统计（unified_metrics 实际覆盖 2025-01..12）"
    return {"evidence": [{
        "type": "fact",
        "ref": f"unified_metrics · {(sql.split('FROM')[1].split()[0] if 'FROM' in sql.upper()
                                    and len(sql.split('FROM')) > 1 else 'unified_metrics')}",
        "rows": rows, "note": note, "sql_source": source,
        "provenance": {"source_type": "platform_api", "authority": 80},
    }], "row_count": len(rows)}
