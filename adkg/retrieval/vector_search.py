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
    try:
        vec = _vec_literal(embed_fn([question])[0])
    except Exception:
        return _keyword_fallback()

    where, where_params = ["embedding IS NOT NULL"], []
    classes = plan.metadata_filter.get("entity_class__in", [])
    if classes:
        where.append("(entity_class = ANY(%s) OR entity_class IS NULL)")   # 未分类=公共内容
        where_params.append(classes)
    visible = list(plan.visible_entity_ids)
    if visible:
        where.append("(case_id = ANY(%s) OR brand_id = ANY(%s) OR case_id IS NULL)")
        where_params += [visible, visible]

    # 嵌入未命中/失败时的关键词兜底（§7.2 降级矩阵：缺席不如降级检索）
    def _keyword_fallback():
        import re as _re
        stop = "的了吗呢吧啊是有在和与及对从被把"
        kws = []
        for w in _re.findall(r"[\u4e00-\u9fa5]{2,8}", question):
            w = w.strip(stop)                           # 剥首尾虚词，防"信息流视频的"式 miss
            if len(w) >= 2 and w not in kws:
                kws.append(w)
        kws = kws[:4]
        if not kws:
            return {"evidence": [], "degraded": False}
        like = " OR ".join("text ILIKE %s" for _ in kws)
        kws = [f"%{k}%" for k in kws]
        with psycopg.connect(dsn, options="-c statement_timeout=3000") as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT doc_id, chunk_index, text, 0.5 FROM chunks"
                            f" WHERE entity_class IS NOT NULL AND ({like})"
                            f" ORDER BY (entity_class='Guideline') DESC LIMIT 5", kws)
                rows = cur.fetchall()
        return {"evidence": [{
            "type": "doc", "ref": f"chunk:{r[0]}#{r[1]}", "quote": r[2][:200],
            "score": 0.5, "fallback": "keyword",
            "provenance": {"source_type": "official_doc", "authority": 60},
        } for r in rows], "degraded": False}

    sql = (f"""
        SELECT doc_id, chunk_index, text, score FROM (
          SELECT doc_id, chunk_index, text,
                 1 - (embedding <=> %s::vector) AS score,
                 row_number() OVER (PARTITION BY coalesce(entity_class, '~')
                                    ORDER BY embedding <=> %s::vector) AS rn
          FROM chunks WHERE {' AND '.join(where)}
        ) t WHERE rn <= 3 ORDER BY score DESC LIMIT {int(limit)}""")
    with psycopg.connect(dsn, options="-c statement_timeout=3000") as conn:
        with conn.cursor() as cur:
            cur.execute(sql, [vec, vec, *where_params])
            rows = cur.fetchall()
    # 内容级近似去重（模板化文档会产生同文块，只留最高分）+ 类配额已保证规范块在场
    seen_prefix, evidence = set(), []
    for r in rows:
        key = r[2][:60]
        if key in seen_prefix:
            continue
        seen_prefix.add(key)
        evidence.append({
            "type": "doc", "ref": f"chunk:{r[0]}#{r[1]}", "quote": r[2][:200],
            "score": round(float(r[3]), 4),
            "provenance": {"source_type": "official_doc", "authority": 60},
        })
    if not evidence:
        return _keyword_fallback()
    return {"evidence": evidence, "degraded": False}
