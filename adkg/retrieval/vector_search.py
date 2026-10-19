"""vector 路（§7.3）：pgvector cosine + metadata 过滤下推（§八 向量层）。

无嵌入能力（embed_fn 为空，如缺模型/缓存）→ degraded 标记，
assemble 拼装时在响应里注明缺席路（§7.2 降级矩阵）。
"""
from __future__ import annotations

import psycopg


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def search(question: str, plan, dsn: str, embed_fn=None, *, limit: int = 10) -> dict:
    if embed_fn is None:
        return {"evidence": [], "degraded": True, "reason": "无嵌入能力（缺本地模型）"}
    vec = _vec_literal(embed_fn([question])[0])

    where, where_params = ["embedding IS NOT NULL"], []
    classes = plan.metadata_filter.get("entity_class__in", [])
    if classes:
        where.append("entity_class = ANY(%s)")
        where_params.append(classes)
    visible = list(plan.visible_entity_ids)
    if visible:
        where.append("(case_id = ANY(%s) OR brand_id = ANY(%s) OR case_id IS NULL)")
        where_params += [visible, visible]

    sql = (f"SELECT doc_id, chunk_index, text, 1 - (embedding <=> %s::vector) AS score"
           f" FROM chunks WHERE {' AND '.join(where)}"
           f" ORDER BY embedding <=> %s::vector LIMIT {int(limit)}")
    with psycopg.connect(dsn, options="-c statement_timeout=3000") as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [vec, *where_params, vec])
            rows = cur.fetchall()
    return {"evidence": [{
        "type": "doc", "ref": f"chunk:{r[0]}#{r[1]}", "quote": r[2][:200],
        "score": round(float(r[3]), 4),
        "provenance": {"source_type": "official_doc", "authority": 60},
    } for r in rows], "degraded": False}
