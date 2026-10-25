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
        assert all(set(i) == {"id", "name", "stage", "lost_reason", "brand_id",
                              "brand_name", "owners", "stats"} for i in d["items"])
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


@pytest.mark.skipif(not _up(), reason="Postgres/Neo4j 不在线")
class TestCaseStage:
    """状态变更写操作（spec §15）：权限门 + 状态机裁决 + 拒因落图 + 审计。"""

    def _setup(self):
        from datetime import datetime
        from adkg.models import Entity, Provenance, Relation
        from adkg.store.graph import GraphStore
        import os
        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        prov = Provenance(source_type="system_of_record", source_id="pytest:stage",
                          fetched_at=datetime.now().astimezone())
        g.upsert_entities([Entity(entity_class="Case", entity_id="Case:PYTEST-ST",
                                  props={"name": "状态机测试案例", "stage": "proposal"},
                                  provenance=prov)])
        g.upsert_relations([Relation(source="Case:PYTEST-ST", predicate="for_brand",
                                     target="Brand:B01", provenance=prov)])

    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def test_权限门与状态机(self):
        self._setup()
        client = self._client()
        # management 无 update_stage 权限 → 403（permissions.yaml actions 动态判定）
        assert client.post("/cases/Case:PYTEST-ST/stage",
                           params={"role": "management", "user": "Person:chen"},
                           json={"to_stage": "live"}).status_code == 403
        # 非法迁移 proposal→closed → 409 + 审计 deny
        assert client.post("/cases/Case:PYTEST-ST/stage",
                           params={"role": "admin"},
                           json={"to_stage": "closed"}).status_code == 409
        # 合法迁移 proposal→live
        r = client.post("/cases/Case:PYTEST-ST/stage", params={"role": "admin"},
                        json={"to_stage": "live"})
        assert r.status_code == 200 and r.json()["stage"] == "live"
        # live→terminated 缺原因 → 409（ActionChecker 终态必填）
        assert client.post("/cases/Case:PYTEST-ST/stage", params={"role": "admin"},
                           json={"to_stage": "terminated"}).status_code == 409
        r = client.post("/cases/Case:PYTEST-ST/stage", params={"role": "admin"},
                        json={"to_stage": "terminated", "reason": "测试终止"})
        assert r.status_code == 200
        det = client.get("/cases/Case:PYTEST-ST", params={"role": "admin"}).json()
        assert det["case"]["stage"] == "terminated"
        assert det["case"]["terminate_reason"] == "测试终止"
        assert any(t["action"] == "update_stage" and t["verdict"] == "allow"
                   for t in det["timeline"])          # 流转记录即时可见

    def teardown_method(self):
        if not _up():
            return
        import os
        from adkg.store.graph import GraphStore
        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        with g.session() as s:
            s.run("MATCH (n:Entity {id: 'Case:PYTEST-ST'}) DETACH DELETE n")
