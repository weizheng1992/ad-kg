"""向量层适配器（§八）：chunks + provenance 写入与计数。

upsert 语义（ON CONFLICT (doc_id, chunk_index)）——§二.5 全量重跑幂等；
embedding 可空（无 API key 时降级，Phase 4 检索前补）。
"""
from __future__ import annotations

import psycopg

from adkg.store import pg_pool


class VectorStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def save_chunks(self, chunks) -> None:
        """一批 chunk 连同各自 provenance 一次事务写入。"""
        with pg_pool.connect(self.dsn) as conn:
            for c in chunks:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO provenance (source_type, source_id, fetched_at,"
                        " authority, source_url, version, confidence)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (c.provenance.source_type.value, c.provenance.source_id,
                         c.provenance.fetched_at, c.provenance.authority,
                         c.provenance.source_url, c.provenance.version,
                         c.provenance.confidence))
                    prov_id = cur.fetchone()[0]
                    cur.execute(
                        "INSERT INTO chunks (doc_id, chunk_index, text, entity_class,"
                        " brand_id, case_id, embedding, provenance_id)"
                        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
                        " ON CONFLICT (doc_id, chunk_index) DO UPDATE SET"
                        " text = EXCLUDED.text, entity_class = EXCLUDED.entity_class,"
                        " brand_id = EXCLUDED.brand_id, case_id = EXCLUDED.case_id,"
                        " embedding = EXCLUDED.embedding",
                        (c.doc_id, c.chunk_index, c.text, c.entity_class,
                         c.brand_id, c.case_id,
                         c.embedding, prov_id))

    def count_by_doc(self, doc_id: str) -> int:
        with pg_pool.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM chunks WHERE doc_id = %s", (doc_id,))
            return cur.fetchone()[0]

    def delete_by_doc(self, doc_id: str) -> None:
        with pg_pool.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE doc_id = %s", (doc_id,))
