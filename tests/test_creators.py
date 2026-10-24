"""达人库端点（spec §3）：类白名单可见性 + 合作历史行过滤收敛。

真图集成（库不在线跳过，同 test_stores_integration 门模式）；
测试自造实体（Creator:pytest-* / Case:PYTEST-*）用后清理。
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


@pytest.mark.skipif(not (_pg_up() and _neo4j_up()), reason="Postgres/Neo4j 不在线")
class TestCreatorsAPI:
    """ae 列表全量 / creative、client 类白名单 403 / 合作案例随锚点收敛。"""

    def _setup(self):
        from datetime import datetime
        from adkg.models import Entity, Provenance, Relation
        from adkg.store.graph import GraphStore
        env = os.environ
        graph = GraphStore(env["ADKG_NEO4J_URI"], env["ADKG_NEO4J_USER"],
                           env["ADKG_NEO4J_PASSWORD"])
        prov = Provenance(source_type="system_of_record", source_id="pytest:creators",
                          fetched_at=datetime.now().astimezone())
        # 锚点事实（种子图）：Person:li belongs_to_brand Brand:B01（gen_seed org_people）
        graph.upsert_entities([Entity(entity_class="Creator", entity_id="Creator:pytest-cr",
                                      props={"name": "测试达人", "platform": "douyin",
                                             "niches": "露营|测试", "followers": 100000,
                                             "quote_20s": 8000, "quote_image": 5000,
                                             "gmv_30d": 500000, "city": "杭州",
                                             "rating": 4.5}, provenance=prov)])
        # 两个合作案例：C1 在 li 的锚点子图内（B01），C2 挂别家品牌（B03）
        graph.upsert_entities([
            Entity(entity_class="Case", entity_id="Case:PYTEST-C1",
                   props={"name": "锚点内案例", "stage": "live"}, provenance=prov),
            Entity(entity_class="Case", entity_id="Case:PYTEST-C2",
                   props={"name": "锚点外案例", "stage": "closed"}, provenance=prov),
            Entity(entity_class="Case", entity_id="Case:PYTEST-C3",
                   props={"name": "未成单案例", "stage": "lost",
                          "lost_reason": "预算被竞品方案挤占"}, provenance=prov)])
        graph.upsert_relations([
            Relation(source="Case:PYTEST-C1", predicate="for_brand", target="Brand:B01",
                     provenance=prov),
            Relation(source="Case:PYTEST-C2", predicate="for_brand", target="Brand:B03",
                     provenance=prov),
            Relation(source="Case:PYTEST-C3", predicate="for_brand", target="Brand:B01",
                     provenance=prov)] +
            [Relation(source=f"Case:PYTEST-C{i}", predicate="collabs_with",
                      target="Creator:pytest-cr", provenance=prov) for i in (1, 2, 3)])
        return graph

    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def test_列表与类白名单(self):
        self._setup()
        client = self._client()
        r = client.get("/creators", params={"q": "测试达人", "role": "ae", "user": "Person:li"})
        assert r.status_code == 200
        assert any(i["id"] == "Creator:pytest-cr" for i in r.json()["items"])
        for bad in ("creative", "client"):
            r = client.get("/creators", params={"role": bad})
            assert r.status_code == 403, f"{bad} 应被类白名单拒绝"

    def test_合作历史随锚点收敛与lost_reason(self):
        self._setup()
        client = self._client()
        r = client.get("/creators/Creator:pytest-cr",
                       params={"role": "ae", "user": "Person:li"})
        assert r.status_code == 200
        d = r.json()
        ids = {c["id"] for c in d["collabs"]}
        assert "Case:PYTEST-C1" in ids and "Case:PYTEST-C3" in ids
        assert "Case:PYTEST-C2" not in ids          # 锚点外（B03）不可见
        assert d["collabs_filtered"] == 1
        lost = next(c for c in d["collabs"] if c["id"] == "Case:PYTEST-C3")
        assert lost["lost_reason"] == "预算被竞品方案挤占"
        # management 无行过滤：三个案例全见
        r = client.get("/creators/Creator:pytest-cr",
                       params={"role": "management", "user": "Person:chen"})
        assert len(r.json()["collabs"]) == 3

    def teardown_method(self):
        if not _neo4j_up():
            return
        from adkg.store.graph import GraphStore
        graph = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                           os.environ["ADKG_NEO4J_PASSWORD"])
        with graph.session() as s:
            s.run("MATCH (n:Entity) WHERE n.id STARTS WITH 'Creator:pytest-'"
                  " OR n.id STARTS WITH 'Case:PYTEST-' DETACH DELETE n")
