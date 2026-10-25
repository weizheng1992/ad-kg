"""客户页端点（spec §5）：锚点可见性 + 属性/指标白名单 + 商品段类闸。

真图集成（库不在线跳过）；直接消费种子图（B01–B08、li→B01、client_a→B04 external）。
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
class TestBrandsAPI:
    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def test_管理层全量与ae锚点收敛(self):
        client = self._client()
        r = client.get("/brands", params={"role": "management", "user": "Person:chen"})
        assert r.status_code == 200
        ids = {i["id"] for i in r.json()["items"]}
        assert {"Brand:B01", "Brand:B04"} <= ids
        # ae（li belongs_to_brand B01）：只见对接品牌
        r = client.get("/brands", params={"role": "ae", "user": "Person:li"})
        assert [i["id"] for i in r.json()["items"]] == ["Brand:B01"]

    def test_client锚点豁免类闸只看自己(self):
        client = self._client()
        r = client.get("/brands", params={"role": "client", "user": "Person:client_a"})
        assert r.status_code == 200
        assert [i["id"] for i in r.json()["items"]] == ["Brand:B04"]
        d = client.get("/brands/Brand:B04",
                       params={"role": "client", "user": "Person:client_a"}).json()
        # 外部属性白名单：案例只回 id/name/stage；商品段无 Product 类不返回
        assert all(set(c) == {"id", "name", "stage", "lost_reason"} for c in d["cases"])
        assert d["products"] == []
        # 指标白名单：cost 可见、cpa 不可见（§12.4 metrics_allow）
        assert d["stats"] and "cost" in d["stats"] and "cpa" not in d["stats"]
        assert client.get("/brands/Brand:B01",
                          params={"role": "client", "user": "Person:client_a"}).status_code == 404

    def test_optimizer无品牌锚点403(self):
        client = self._client()
        r = client.get("/brands", params={"role": "optimizer", "user": "Person:zhao"})
        assert r.status_code == 403
