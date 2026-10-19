"""store 层集成测试：vector/chunks+provenance（Postgres）、graph（Neo4j）。

docker compose 起库后直连真库验证（§四 tests 注释的集成冒烟路）；库不在线则跳过。
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _pg_up() -> bool:
    try:
        import psycopg
        with psycopg.connect(os.environ["ADKG_PG_DSN"], connect_timeout=3):
            return True
    except Exception:
        return False


def _neo4j_up() -> bool:
    try:
        from neo4j import GraphDatabase
        d = GraphDatabase.driver(os.environ["ADKG_NEO4J_URI"],
                                 auth=(os.environ["ADKG_NEO4J_USER"],
                                       os.environ["ADKG_NEO4J_PASSWORD"]))
        d.verify_connectivity()
        d.close()
        return True
    except Exception:
        return False


pg_only = pytest.mark.skipif(not _pg_up(), reason="Postgres 不在线（docker compose up -d）")
neo4j_only = pytest.mark.skipif(not _neo4j_up(), reason="Neo4j 不在线")


# ---------------------------------------------------------------- Postgres
@pg_only
class TestVectorStore:
    def test_块与溯源写入_幂等重跑不重复(self):
        from adkg.models import Chunk, Provenance
        from adkg.store.vector import VectorStore
        import uuid

        store = VectorStore(os.environ["ADKG_PG_DSN"])
        doc = f"itest/{uuid.uuid4().hex[:8]}.md"
        prov = Provenance(source_type="official_doc", source_id=f"file:{doc}",
                          fetched_at="2026-10-19T00:00:00+08:00")
        chunks = [Chunk(doc_id=doc, chunk_index=0, text="前 3 秒须出现品牌标识",
                        entity_class="Guideline", provenance=prov),
                  Chunk(doc_id=doc, chunk_index=1, text="竖版 9:16", provenance=prov)]
        store.save_chunks(chunks)
        store.save_chunks(chunks)                 # 重跑（§二.5 全量重跑幂等）
        rows = store.count_by_doc(doc)
        assert rows == 2
        store.delete_by_doc(doc)                  # 清理

    def test_缺embedding可写(self):
        from adkg.models import Chunk, Provenance
        from adkg.store.vector import VectorStore
        import uuid

        store = VectorStore(os.environ["ADKG_PG_DSN"])
        doc = f"itest/{uuid.uuid4().hex[:8]}.md"
        prov = Provenance(source_type="wiki", source_id=f"file:{doc}",
                          fetched_at="2026-10-19T00:00:00+08:00")
        store.save_chunks([Chunk(doc_id=doc, chunk_index=0, text="无嵌入块", provenance=prov)])
        assert store.count_by_doc(doc) == 1
        store.delete_by_doc(doc)


# ---------------------------------------------------------------- Neo4j
@neo4j_only
class TestGraphStore:
    def test_实体MERGE幂等_属性更新(self):
        import os
        from adkg.models import Entity, Provenance
        from adkg.store.graph import GraphStore

        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        prov = Provenance(source_type="system_of_record", source_id="itest:1",
                          fetched_at="2026-10-19T00:00:00+08:00")
        eid = "Case:itest-c1"
        g.upsert_entities([Entity(entity_class="Case", entity_id=eid,
                                  props={"stage": "proposal"}, provenance=prov)])
        g.upsert_entities([Entity(entity_class="Case", entity_id=eid,
                                  props={"stage": "live"}, provenance=prov)])
        with g.session() as s:
            stage, cnt = s.run(
                "MATCH (n:Entity {id: $id}) RETURN n.stage AS stage, count(n) AS c",
                id=eid).single().values()
        assert stage == "live" and cnt == 1       # MERGE：更新不重复
        with g.session() as s:
            s.run("MATCH (n:Entity {id: $id}) DETACH DELETE n", id=eid)

    def test_关系MERGE_带置信度(self):
        import os
        from adkg.models import Entity, Provenance, Relation
        from adkg.store.graph import GraphStore

        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        prov = Provenance(source_type="conversation", source_id="itest:2",
                          fetched_at="2026-10-19T00:00:00+08:00")
        nodes = [Entity(entity_class="Creative", entity_id="Creative:itest-1",
                        props={}, provenance=prov),
                 Entity(entity_class="Guideline", entity_id="Guideline:itest-g",
                        props={}, provenance=prov)]
        g.upsert_entities(nodes)
        rel = Relation(source="Creative:itest-1", predicate="violates",
                       target="Guideline:itest-g", provenance=prov, confidence=0.91)
        g.upsert_relations([rel, rel])            # 双写幂等：MERGE
        with g.session() as s:
            rec = s.run(
                "MATCH (a:Entity {id: 'Creative:itest-1'})-[r:violates]"
                "->(b:Entity {id: 'Guideline:itest-g'}) RETURN r.confidence AS c").single()
        assert rec["c"] == 0.91
        with g.session() as s:
            s.run("MATCH (n:Entity) WHERE n.id STARTS WITH 'Guideline:itest-' "
                  "OR n.id STARTS WITH 'Creative:itest-' DETACH DELETE n")
