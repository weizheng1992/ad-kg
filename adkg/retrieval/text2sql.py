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

import psycopg

DIM_COLUMNS = ["platform", "date", "creative_id", "campaign_id", "case_id", "brand_id"]
ALL_METRICS = ["cost", "impressions", "clicks", "conversions", "ctr", "cvr", "cpa", "cpm", "roi"]


def _template(question: str, entity_ids: list[str] | None) -> tuple[str, dict]:
    """问题 → (模板名, 参数)。模板是固定 SQL 骨架，只有参数可变。"""
    q = question.lower()
    n = next((int(x) for x in re.findall(r"([一二三四五六七八九十\d]+)\s*[个条]", q)), 5)
    if "最差" in question or "最好" in question or "cpa" in q:
        return "top_cpa", {"n": n, "worst": "最差" in question or "cpa" in q}
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
    if name == "top_cpa" and "cpa" in metrics:
        sql = (f"SELECT creative_id, round(avg(cpa)::numeric, 1) AS avg_cpa, count(*) AS days"
               f" FROM unified_metrics WHERE {' AND '.join(conds)}"
               f" GROUP BY 1 HAVING count(*) >= 5 ORDER BY avg_cpa {'DESC' if params.get('worst', True) else 'ASC'}"
               f" LIMIT {min(params.get('n', 5), 50)}")       # 闸 5：强制 LIMIT
    elif name == "entity_metrics" and metrics:
        cols = ", ".join(f"round(avg({c})::numeric, 2) AS {c}" for c in metrics[:4])
        ids = [i for i in params["ids"] if i.startswith("Creative:")]
        sql = (f"SELECT creative_id, {cols} FROM unified_metrics"
               f" WHERE {' AND '.join(conds + ['creative_id = ANY(%(ids)s)'])} GROUP BY 1 LIMIT 50")
        params = {**params, "ids": ids or ["Creative:-"]}
    else:
        cols = ", ".join(f"round(sum({c})::numeric, 2) AS {c}" for c in metrics[:4]) or "count(*) AS rows"
        sql = (f"SELECT platform, {cols} FROM unified_metrics"
               f" WHERE {' AND '.join(conds)} GROUP BY 1 LIMIT 20")
    return sql, params


def run(question: str, plan, dsn_ro: str, entity_ids: list[str] | None = None) -> dict:
    sql, params = build_sql(question, plan, entity_ids)
    with psycopg.connect(dsn_ro, options="-c statement_timeout=3000") as conn:   # 闸 1 + 5
        with conn.cursor() as cur:
            cur.execute(sql, params)                      # 闸 2/3：模板 + 白名单投影
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"evidence": [{
        "type": "fact",
        "ref": f"unified_metrics · {sql.split('FROM')[1].split()[0]}",
        "rows": rows,
        "provenance": {"source_type": "platform_api", "authority": 80},
    }], "row_count": len(rows)}
