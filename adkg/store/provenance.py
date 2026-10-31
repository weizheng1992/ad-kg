"""溯源层适配器（§八）：ingest_job 状态、review_queue、provenance 计数与对账。"""
from __future__ import annotations

import json


from adkg.store import pg_pool


class TraceStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def insert_provenance(self, prov) -> str:
        with pg_pool.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO provenance (source_type, source_id, fetched_at, authority,"
                " source_url, version, confidence) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (prov.source_type.value, prov.source_id, prov.fetched_at, prov.authority,
                 prov.source_url, prov.version, prov.confidence))
            return str(cur.fetchone()[0])

    def provenance_count(self) -> int:
        with pg_pool.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM provenance")
            return cur.fetchone()[0]

    def job_upsert(self, source_id: str, version: str, raw_ref: str) -> None:
        with pg_pool.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingest_job (source_id, version, raw_ref)"
                " VALUES (%s,%s,%s) ON CONFLICT (source_id, version) DO UPDATE"
                " SET raw_ref = EXCLUDED.raw_ref, updated_at = now()",
                (source_id, version, raw_ref))

    def job_done(self, source_id: str, version: str) -> bool:
        """(source_id, version) 两段都已 done 才算同步完成——定时增量的跳过判据（§7.2）。"""
        with pg_pool.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_status = 'done' AND neo4j_status = 'done'"
                " FROM ingest_job WHERE source_id = %s AND version = %s",
                (source_id, version))
            row = cur.fetchone()
            return bool(row and row[0])

    def job_mark(self, source_id: str, version: str, *, pg: str | None = None,
                 neo4j: str | None = None, error: str | None = None) -> None:
        with pg_pool.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE ingest_job SET"
                " pg_status = coalesce(%s, pg_status),"
                " neo4j_status = coalesce(%s, neo4j_status),"
                " error = %s, updated_at = now()"
                " WHERE source_id = %s AND version = %s",
                (pg, neo4j, error, source_id, version))

    def push_review(self, kind: str, payload: dict) -> None:
        with pg_pool.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO review_queue (kind, payload) VALUES (%s, %s)",
                (kind, json.dumps(payload, ensure_ascii=False, default=str)))

    def reconcile(self, graph_counts: dict[str, int]) -> dict[str, int]:
        """批次收尾对账（§八）：计数差异写 review_queue 人审，返回对比结果。

        批量溯源（一条 provenance 覆盖 N 实体）下不追求相等，差异供人 eyeball。
        """
        pg_n = self.provenance_count()
        graph_n = graph_counts.get("nodes", 0) + graph_counts.get("relations", 0)
        diff = {"pg_provenance": pg_n, **graph_counts}
        if pg_n != graph_n:
            self.push_review("reconcile", {"detail": diff})
        return diff
