"""vector 路（§7.3）：pgvector cosine + metadata 过滤下推（§八 向量层）。

无嵌入能力（embed_fn 为空，如缺模型/缓存）→ degraded 标记，
assemble 拼装时在响应里注明缺席路（§7.2 降级矩阵）。
"""
from __future__ import annotations

import psycopg

from adkg.store import pg_pool


def _vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


_STOP_CHARS = "的了吗呢吧啊是有在和与及对从被把"
_STOP_WORDS = {"什么", "怎么", "如何", "哪些", "为什么", "这个", "那个", "就是", "还是"}


def _extract_keywords(question: str, k: int = 4) -> list[str]:
    """关键词兜底提词：jieba 分词取内容词，长词优先（更具体、ILIKE 误配少）。
    旧版按 [一-龥]{2,8} 字符窗口切片——中文无空格，长问句切出的
    是任意 8 字窗口而非词，ILIKE 几乎必 miss（2026-10-27 修，缺陷备忘②）；
    jieba 缺席的环境回落窗口切片（聊胜于无，行为同旧版）。"""
    try:
        import jieba
        words = [w.strip(_STOP_CHARS) for w in jieba.lcut(question)]
    except ImportError:
        import re as _re
        words = [w.strip(_STOP_CHARS)
                 for w in _re.findall(r"[一-龥]{2,8}", question)]
    words = [w for w in words if len(w) >= 2 and w not in _STOP_WORDS]
    # 保序去重（dict.fromkeys）+ 长词优先稳定排序：同长词按问句出现序取，
    # 兜底路求召回不求排序语义
    return sorted(dict.fromkeys(words), key=len, reverse=True)[:k]


def search(question: str, plan, dsn: str, embed_fn=None, *, limit: int = 10) -> dict:
    if getattr(plan, "deny_all", False):
        return {"evidence": [], "degraded": False}      # fail-closed：无有效身份零证据（§12.4）
    # 权限子句先建（主路与关键词兜底共用——降级检索不降权限，§12.4 fail-closed）；
    # 主路维持"未分类=公共内容可检索"（类子句自带 OR entity_class IS NULL），
    # entity_class IS NOT NULL 只加在兜底（兜底按类排序需要非空类）——不得进主路，
    # 否则未分类公共块整体从向量检索消失（2026-10-22 二轮验证回归抓出）
    perm, perm_params = [], []
    classes = plan.metadata_filter.get("entity_class__in", [])
    if classes:
        perm.append("(entity_class = ANY(%s) OR entity_class IS NULL)")   # 未分类=公共内容
        perm_params.append(classes)
    visible = list(plan.visible_entity_ids)
    if visible:
        perm.append("(case_id = ANY(%s) OR brand_id = ANY(%s) OR case_id IS NULL)")
        perm_params += [visible, visible]
    where = ["entity_class IS NOT NULL"] + perm            # 兜底用：非空类 + 权限子句
    where_params = list(perm_params)

    # 嵌入未命中/失败时的关键词兜底（§7.2 降级矩阵：缺席不如降级检索）；
    # 必须先于 embed 调用定义——2026-10-22 验证：定义在 try 之后时 embed 一抛异常，
    # 兜底引用未定义局部名，UnboundLocalError 直接把 /ask 打成 500
    def _keyword_fallback():
        kws = _extract_keywords(question)              # jieba 分词（§7.2 降级路，2026-10-27 修）
        if not kws:
            return {"evidence": [], "degraded": False}
        like = " OR ".join("text ILIKE %s" for _ in kws)
        kws = [f"%{k}%" for k in kws]
        with pg_pool.connect(dsn, options="-c statement_timeout=3000") as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT doc_id, chunk_index, text, 0.5 FROM chunks"
                            f" WHERE {' AND '.join(where)} AND ({like})"
                            f" ORDER BY (entity_class='Guideline') DESC LIMIT 5",
                            [*where_params, *kws])
                rows = cur.fetchall()
        return {"evidence": [{
            "type": "doc", "ref": f"chunk:{r[0]}#{r[1]}", "quote": r[2][:200],
            "score": 0.5, "fallback": "keyword",
            "provenance": {"source_type": "official_doc", "authority": 60},
        } for r in rows], "degraded": False}

    if embed_fn is None:
        # 嵌入能力缺失也走关键词兜底（§7.2 缺席不如降级检索）——2026-10-23 检查实锤：
        # 此分支曾直接 degraded，探测失败的级联让概念题当场丢主路
        return _keyword_fallback()

    try:
        vec = _vec_literal(embed_fn([question])[0])
    except Exception:
        return _keyword_fallback()

    sql = (f"""
        SELECT doc_id, chunk_index, text, score FROM (
          SELECT doc_id, chunk_index, text,
                 1 - (embedding <=> %s::vector) AS score,
                 row_number() OVER (PARTITION BY coalesce(entity_class, '~')
                                    ORDER BY embedding <=> %s::vector) AS rn
          FROM chunks WHERE embedding IS NOT NULL{''.join(' AND ' + c for c in perm)}
        ) t WHERE rn <= 3 ORDER BY score DESC LIMIT {int(limit)}""")
    with pg_pool.connect(dsn, options="-c statement_timeout=3000") as conn:
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
