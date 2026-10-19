"""vector 路（§7.3）：pgvector cosine + metadata 过滤下推（§八 向量层）。

无嵌入能力（embed_fn 为空，如无 API key）→ 返回 degraded 标记，
assemble 拼装时在响应里注明缺席路（§7.2 降级矩阵）。
"""
from __future__ import annotations

import psycopg


def search(question: str, plan, dsn: str, embed_fn=None, *, limit: int = 10) -> dict:
    if embed_fn is None:
        return {"evidence": [], "degraded": True, "reason": "无嵌入能力（缺 API key）"}
    vec = embed_fn([question])[0]
    classes = plan.metadata_filter.get("entity_class__in", [])
    conds, params = ["1=1"], [vec]
    if classes:
        conds.append("entity_class = ANY(%s)")
        params.append(classes)
    if plan.visible_entity_ids:
        conds.append("(case_id = ANY(%s) OR brand_id = ANY(%s) OR case_id IS NULL)")
        vis = list(plan.visible_entity_ids)
        params += [vis, vis]
    with psycopg.connect(dsn, options="-c statement_timeout=3000") as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT doc_id, chunk_index, text, 1 - (embedding <=> %s) AS score"
                f" FROM chunks WHERE embedding IS NOT NULL AND {' AND '.join(conds)}"
                f" ORDER BY embedding <=> %s LIMIT {int(limit)}",
                [vec, vec] if not classes else [vec, classes, vec])
            rows = cur.fetchall()
    return {"evidence": [{
        "type": "doc", "ref": f"chunk:{r[0]}#{r[1]}", "quote": r[2][:200],
        "score": round(float(r[3]), 4),
        "provenance": {"source_type": "official_doc", "authority": 60},
    } for r in rows], "degraded": False}
