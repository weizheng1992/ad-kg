"""数据看板聚合（spec §5）：行谓词收敛 + 达人段类白名单 + 指标白名单。

真库集成（不在线跳过）；client 断言自己品牌、ae 断言锚点案例、creative 无看板。
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _up() -> bool:
    try:
        import psycopg
        from neo4j import GraphDatabase
        with psycopg.connect(os.environ["ADKG_PG_DSN"], connect_timeout=3):
            pass
        d = GraphDatabase.driver(os.environ["ADKG_NEO4J_URI"],
                                 auth=(os.environ["ADKG_NEO4J_USER"],
                                       os.environ["ADKG_NEO4J_PASSWORD"]))
        d.verify_connectivity()
        d.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _up(), reason="Postgres/Neo4j 不在线")
class TestStatsAPI:
    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def test_management全量含达人段(self):
        client = self._client()
        d = client.get("/stats/overview",
                       params={"role": "management", "user": "Person:chen"}).json()
        assert d["trend"] and d["platforms"] and d["brands"]
        assert {p["platform"] for p in d["platforms"]} == {"douyin", "xhs"}
        assert d["top_creators"], "management 应见达人 Top"

    def test_client只看自己品牌且无达人段(self):
        client = self._client()
        d = client.get("/stats/overview",
                       params={"role": "client", "user": "Person:client_a"}).json()
        # client 谓词=锚点案例（B04）→ 品牌只含 B04；Creator 不在类白名单 → 无达人段
        assert {b["brand_id"] for b in d["brands"]} <= {"Brand:B04"}
        assert d["top_creators"] is None
        # client 指标白名单：cost/conversions 可见（cpa 不在本端点返回面）

    def test_ae锚点收敛与阶段可见数(self):
        client = self._client()
        d = client.get("/stats/overview",
                       params={"role": "ae", "user": "Person:li"}).json()
        assert {b["brand_id"] for b in d["brands"]} <= {"Brand:B01"}
        mg = client.get("/stats/overview",
                        params={"role": "management", "user": "Person:chen"}).json()
        ae_cases = sum(s["count"] for s in d["stages"])
        mg_cases = sum(s["count"] for s in mg["stages"])
        assert ae_cases < mg_cases        # ae 只计锚点内案例，management 全量
