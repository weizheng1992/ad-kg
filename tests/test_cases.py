"""案例全生命周期端点（spec §13.2）：列表批量指标 + 详情六段收敛。

真库集成（不在线跳过）；ae 锚点分页（全量取出→行过滤→Python 分页）、
deny_properties 出口、client 属性白名单 + 品牌锚点豁免、内容/流转段。
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
class TestCasesAPI:
    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def test_ae锚点列表与属性出口(self):
        client = self._client()
        r = client.get("/cases", params={"role": "ae", "user": "Person:li", "size": 10})
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 4                                    # B01 锚点案例（含新批次 021/045）
        assert {i["brand_id"] for i in d["items"]} == {"Brand:B01"}
        assert all("gross_margin" not in i and "bd_budget" not in i for i in d["items"])

    def test_client属性白名单与品牌锚点豁免(self):
        client = self._client()
        d = client.get("/cases", params={"role": "client", "user": "Person:client_a"}).json()
        assert d["total"] > 0
        assert {i["brand_id"] for i in d["items"]} == {"Brand:B04"}
        assert all(set(i) == {"id", "name", "stage", "brand_id", "brand_name",
                              "owners", "stats"} for i in d["items"])
        det = client.get("/cases/Case:C-2025-011",
                         params={"role": "client", "user": "Person:client_a"}).json()
        assert det["brand"]["id"] == "Brand:B04"                  # 类白名单无 Brand，锚点豁免
        assert det["owners"] == []                                 # 外部角色姓名掩码（§12.6）

    def test_详情六段(self):
        client = self._client()
        d = client.get("/cases/Case:C-2025-005",
                       params={"role": "management", "user": "Person:chen"}).json()
        assert d["case"]["stage"] == "live" and d["case"]["gross_margin"] == "0.25"
        assert d["docs"], "案例内容（chunks）应在场"
        assert d["creators"] and any("铲屎官" in c["name"] for c in d["creators"])
        assert d["stats"] and "cost" in d["stats"] and "cpa" in d["stats"]
        assert d["stage_flow"]["current"] == "live"
        assert d["timeline"] == []                                 # 种子无审计——诚实空
        assert any(c["metrics"] for c in d["creatives"])

    def test_状态筛选与拒因在场(self):
        client = self._client()
        d = client.get("/cases", params={"role": "management", "user": "Person:chen",
                                         "stage": "lost"}).json()
        assert d["items"] and all(i["stage"] == "lost" for i in d["items"])
        assert any(i["lost_reason"] for i in d["items"])
