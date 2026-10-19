"""流水线编排（§四 pipeline/run.py / §八 双写一致性）。

顺序铁律：raw（不可变）→ Postgres（chunks/provenance）→ Neo4j（MERGE）；
幂等键 = provenance 的 source_id + version（缺省取 fetched_at 日期）；
批次收尾对账：图层 provenance 计数 vs provenance 表，差异写 review_queue。

extractor / embed_fn 依赖注入：无 LLM key 时传 None——抽取按 §7.2 降级跳过，
块与溯源照常入库（向量留空，Phase 4 前补）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from adkg.connectors.base import Connector, RawRecord
from adkg.models import Chunk
from adkg.pipeline.chunking import chunk_markdown
from adkg.store.raw import RawStore


@dataclass
class RunStats:
    docs: int = 0
    chunks: int = 0
    entities: int = 0
    relations: int = 0
    review: int = 0
    dropped: int = 0
    reconcile: dict = field(default_factory=dict)


def _version_of(record: RawRecord) -> str:
    return record.provenance.version or record.provenance.fetched_at.date().isoformat()


def run_docs(connector: Connector, raw: RawStore, vector, graph, trace,
             extractor=None, embed_fn=None, max_chars: int = 500) -> RunStats:
    stats = RunStats()

    for record in connector.fetch():
        stats.docs += 1
        raw_rel, sha = raw.write(record.source_ref, record.text)
        version = _version_of(record)
        trace.job_upsert(record.provenance.source_id, version, f"{raw_rel}@{sha[:12]}")

        _, pieces = chunk_markdown(record.text, max_chars=max_chars)
        texts = [p.text for p in pieces]
        embeddings = embed_fn(texts) if embed_fn else [None] * len(texts)
        chunks = [Chunk(doc_id=record.provenance.source_id, chunk_index=p.chunk_index,
                        text=p.text, provenance=record.provenance,
                        embedding=e)
                  for p, e in zip(pieces, embeddings)]
        vector.save_chunks(chunks)                       # Postgres 先
        trace.job_mark(record.provenance.source_id, version, pg="done")
        stats.chunks += len(chunks)

        if extractor is not None:                        # Neo4j 后
            for piece in pieces:
                result = extractor(piece.text, record.provenance.model_dump())
                graph.upsert_entities(result.entities)
                graph.upsert_relations(result.relations)
                stats.entities += len(result.entities)
                stats.relations += len(result.relations)
                stats.dropped += result.dropped
                for item in result.review:
                    trace.push_review("conflict-review", item)
                    stats.review += 1
        trace.job_mark(record.provenance.source_id, version, neo4j="done")

    stats.reconcile = trace.reconcile(graph.counts())    # 批次收尾对账
    return stats
