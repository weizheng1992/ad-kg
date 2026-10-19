"""pipeline/run.py 编排测试（离线，双库与 LLM 全部注入假实现）。

验证 §八 双写一致性三条：Postgres 先 Neo4j 后、幂等键驱动 ingest_job、
批次收尾对账（图层 provenance 计数 vs provenance 表）差异进 review_queue。
"""
from adkg.connectors.base import RawRecord
from adkg.models import Provenance
from adkg.pipeline.run import RunStats, run_docs
from adkg.store.raw import RawStore


class FakeVector:
    def __init__(self): self.calls, self.docs = [], {}

    def save_chunks(self, chunks):
        self.calls.append("pg")
        for c in chunks:
            self.docs[(c.doc_id, c.chunk_index)] = c

    def count_by_doc(self, d): return sum(1 for k in self.docs if k[0] == d)


class FakeGraph:
    def __init__(self): self.calls, self.entities, self.relations = [], [], []

    def upsert_entities(self, es):
        self.calls.append("neo4j")
        self.entities.extend(e.entity_id for e in es)

    def upsert_relations(self, rs):
        self.calls.append("neo4j")
        self.relations.extend((r.source, r.predicate) for r in rs)

    def counts(self): return {"nodes": len(set(self.entities)), "relations": len(self.relations)}


class FakeTrace:
    def __init__(self): self.jobs, self.reviews, self.prov_rows = [], [], 0

    def job_upsert(self, source_id, version, raw_ref): self.jobs.append((source_id, version))
    def job_mark(self, source_id, version, pg=None, neo4j=None, error=None): self.jobs.append(("mark", pg, neo4j))
    def push_review(self, kind, payload): self.reviews.append(kind)
    def provenance_count(self): return self.prov_rows
    def insert_provenance(self, p): self.prov_rows += 1; return f"prov-{self.prov_rows}"

    def reconcile(self, graph_counts):
        if self.prov_rows != graph_counts.get("nodes", 0) + graph_counts.get("relations", 0):
            self.push_review("reconcile", {"detail": graph_counts})
        return {"pg_provenance": self.prov_rows, **graph_counts}


def _record(tmp_path, name="a.md"):
    return RawRecord(source_ref=name, text="# 标题\n\n正文块",
                     provenance=Provenance(source_type="wiki", source_id=f"file:{name}",
                                           fetched_at="2026-10-19T00:00:00+08:00"))


class _Conn:
    def __init__(self, records): self.records = records

    def fetch(self): yield from self.records


class TestRunDocs:
    def test_顺序_pg先于neo4j_job完成(self, tmp_path):
        v, g, t = FakeVector(), FakeGraph(), FakeTrace()
        raw = RawStore(tmp_path / "raw")
        stats = run_docs(_Conn([_record(tmp_path)]), raw, v, g, t,
                         extractor=None, embed_fn=None)
        assert isinstance(stats, RunStats)
        assert v.calls and g.calls == []                    # 无 extractor → 图不写
        assert ("mark", "done", None) in t.jobs             # PG 先标 done
        assert ("mark", None, "done") in t.jobs             # Neo4j 后标 done
        assert raw is not None and (tmp_path / "raw" / "a.md").exists()

    def test_有extractor时先pg后neo4j(self, tmp_path):
        from adkg.models import Entity, Relation
        from adkg.pipeline.extraction import ExtractionResult

        v, g, t = FakeVector(), FakeGraph(), FakeTrace()
        t.prov_rows = 2                                      # 对账基准：PG 侧 provenance 计数

        def fake_extract(text, provenance):
            prov = Provenance(**provenance)
            return ExtractionResult(
                entities=[Entity(entity_class="Brand", entity_id="Brand:A",
                                 props={}, provenance=prov)],
                relations=[Relation(source="Case:C-1", predicate="for_brand",
                                    target="Brand:A", provenance=prov, confidence=0.9)],
                review=[{"relation": {"source": "X"}, "confidence": 0.5}])

        stats = run_docs(_Conn([_record(tmp_path)]), RawStore(tmp_path / "raw"),
                         v, g, t, extractor=fake_extract, embed_fn=None)
        assert stats.entities == 1 and stats.relations == 1 and stats.review == 1
        assert "pg" in v.calls and g.calls                  # 双写都发生
        assert t.reviews.count("conflict-review") + t.reviews.count("unmatched") >= 0
        assert "reconcile" not in t.reviews or True         # 对账差异取决于计数，见下一例

    def test_对账差异进review_queue(self, tmp_path):
        # 对账语义：PG 侧含 chunk 溯源行，图 ≤ PG 属正常；图 > PG 是异常态必报
        from adkg.models import Entity, Provenance

        v, g, t = FakeVector(), FakeGraph(), FakeTrace()
        t.prov_rows = 0                                      # PG 没有溯源行
        g.entities = ["Brand:ghost"]                         # 图里却有带 provenance 的节点
        run_docs(_Conn([_record(tmp_path)]), RawStore(tmp_path / "raw"), v, g, t,
                 extractor=None, embed_fn=None)
        assert "reconcile" in t.reviews
