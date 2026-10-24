"""财务结算中心（spec §5）：角色门 + 结算字段 + 达人成本聚合。

真图集成（库不在线跳过）；消费种子图（10 例 live/closed 带毛利率）。
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
class TestSettlementsAPI:
    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def test_角色门只放行management与finance(self):
        client = self._client()
        for role in ("management", "finance"):
            r = client.get("/settlements", params={"role": role, "user": "Person:chen"})
            assert r.status_code == 200, f"{role} 应放行"
        for role in ("ae", "optimizer", "creative", "client"):
            r = client.get("/settlements", params={"role": role})
            assert r.status_code == 403, f"{role} 应被角色门拒绝"

    def test_结算字段与达人成本(self):
        client = self._client()
        d = client.get("/settlements", params={"role": "finance", "user": "Person:zhou"}).json()
        assert d["total"] > 0
        item = next(i for i in d["items"] if i["case_id"] == "Case:C-2025-013")
        assert item["settlement_status"] == "paid"           # closed → paid（gen_seed）
        assert 0 < float(item["gross_margin"]) < 1
        assert item["creator_count"] >= 1                    # live/closed 挂品类达人
        assert item["creator_cost"] > 0
        assert d["summary"]["budget_total"] > 0

    def test_状态过滤(self):
        client = self._client()
        d = client.get("/settlements", params={"role": "management", "user": "Person:chen",
                                               "status": "paid"}).json()
        assert d["items"] and all(i["settlement_status"] == "paid" for i in d["items"])
