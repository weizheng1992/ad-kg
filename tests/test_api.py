"""/ask 端到端（TestClient + dev 认证 + 真库）：路由、三路、越权、操作指引、401。"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from adkg.api.main import create_app


def _client(**env_overrides) -> TestClient:
    env = {k: v for k, v in os.environ.items() if k.startswith(("ADKG_", "POSTGRES", "NEO4J"))}
    env.update(env_overrides)
    return TestClient(create_app(env))


@pytest.fixture(scope="module")
def client() -> TestClient:
    return _client()


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestAsk:
    def test_关系链问法_管理角色(self, client):
        r = client.post("/ask", json={"question": "李昂负责哪些 Case？",
                                      "role": "management", "user": "Person:chen"})
        assert r.status_code == 200
        body = r.json()
        assert body["intent"] == "graph"
        refs = " ".join(e["ref"] for e in body["evidence"])
        assert "Person:li" in refs and "responsible_for" in refs
        assert any(rt["route"] == "graph" for rt in body["routes_used"])

    def test_事实问法_topcpa(self, client):
        r = client.post("/ask", json={"question": "上月 CPA 最差的素材有哪些？",
                                      "role": "management", "user": "Person:chen"})
        body = r.json()
        assert body["intent"] == "fact"
        fact = next(e for e in body["evidence"] if e["type"] == "fact")
        assert fact["rows"] and "cpa" in fact["rows"][0]

    def test_客户越权_他牌案例被滤(self, client):
        r = client.post("/ask", json={"question": "Case:C-2025-006 的关系",
                                      "role": "client", "user": "Person:client_a"})
        body = r.json()
        refs = " ".join(e.get("ref", "") for e in body["evidence"])
        assert "C-2025-006" not in refs                     # B06 的案例，零可见（画面 4）

    def test_操作类返回指引不进检索(self, client):
        r = client.post("/ask", json={"question": "帮我删掉这个素材",
                                      "role": "optimizer", "user": "Person:li"})
        body = r.json()
        assert body.get("action") == "guidance" and body["endpoint"] == "/actions/check"
        assert "evidence" not in body

    def test_graph步宕机降级不炸整问(self, client, monkeypatch):
        # 备忘⑬（2026-10-27 修）：graph 步异常该路缺席、其余路照常（§7.2 缺席
        # 不如降级）——曾裸调用，Neo4j 宕机 ServiceUnavailable 穿透为整问 500
        import adkg.retrieval.graph_search as gs

        def _boom(*a, **k):
            raise RuntimeError("simulated neo4j down")
        monkeypatch.setattr(gs, "search", _boom)
        r = client.post("/ask", json={"question": "李昂名下有哪些 live 案例",
                                      "role": "management", "user": "Person:chen"})
        assert r.status_code == 200
        assert "graph" in r.json()["degraded"]

    def test_生产模式无token返回401(self):
        c = _client(ADKG_DEV_AUTH="on")
        assert c.post("/ask", json={"question": "x", "role": "management"}).status_code == 401

    def test_dev模式未知角色401不500(self, client):
        """dev 认证放行 body role，但未知角色必须 fail-closed 401（部署实测 500 教训）。"""
        r = client.post("/ask", json={"question": "x", "role": "hacker"})
        assert r.status_code == 401

    def test_真token认证(self, client):
        r = client.post("/ask", json={"question": "消耗多少"},
                        headers={"Authorization": "Bearer change-me-management"})
        assert r.status_code == 200 and r.json()["intent"] == "fact"


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestGraphEntity:
    def test_实体展开带权限过滤(self, client):
        r = client.get("/graph/entity", params={
            "id": "Person:li", "role": "optimizer", "user": "Person:li"})
        body = r.json()
        assert body["entity"]["id"] == "Person:li"
        assert any(n["via"] == "responsible_for" for n in body["neighbors"])

    def test_客户不见他品牌邻居(self, client):
        r = client.get("/graph/entity", params={
            "id": "Brand:B06", "role": "client", "user": "Person:client_a"})
        assert r.status_code == 404                   # B04 之外直接 404（§12.4 主实体闸，
                                                        # 2026-10-23 前是 200+空邻居）

    def test_不存在实体返回404(self, client):
        assert client.get("/graph/entity", params={
            "id": "Brand:NOPE", "role": "management"}).status_code == 404


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestPermissionGates:
    """2026-10-23 §12.4 fail-closed 六缺口修复的 API 面回归。"""

    def test_graph_entity_越类与越权404(self, client):
        r = client.get("/graph/entity", params={"id": "Product:P01", "role": "finance",
                                                "user": "Person:zhou"})
        assert r.status_code == 404                        # finance classes=[Case,Brand] 越类
        r2 = client.get("/graph/entity", params={"id": "Brand:B06", "role": "client",
                                                 "user": "Person:client_a"})
        assert r2.status_code == 404                       # 他牌 Brand 越可见集
        r3 = client.get("/graph/entity", params={"id": "Brand:B04", "role": "client",
                                                 "user": "Person:client_a"})
        assert r3.status_code == 200

    def test_ingest_assertion_动作门(self, client):
        r = client.post("/ingest/assertion", json={
            "role": "client", "user": "Person:client_a", "subject": "Brand:B04",
            "predicate": "for_brand", "object": "Case:C-2025-003", "confidence": 0.9})
        assert r.status_code == 403                        # actions=[read] 无 write_assertion

    def test_ingest_docs_外部403(self, client):
        r = client.get("/ingest/docs", params={"role": "client", "user": "Person:client_a"})
        assert r.status_code == 403
        r2 = client.get("/ingest/docs", params={"role": "management"})
        assert r2.status_code == 200

    def test_creative_brands_外部403_内部裁剪(self, client):
        r = client.get("/creative/brands", params={"role": "client", "user": "Person:client_a"})
        assert r.status_code == 403
        r2 = client.get("/creative/brands", params={"role": "optimizer", "user": "Person:li"})
        assert r2.status_code == 200 and r2.json()["brands"]   # 只见可见 Brand（非空）

    def test_ask_row_filter缺person零证据(self, client):
        r = client.post("/ask", json={"question": "各案例的消耗", "role": "optimizer"})
        assert r.status_code == 200
        ev = r.json()["evidence"]                          # deny-all（§12.4 fail-closed）
        assert all(not e.get("rows") for e in ev)          # 事实行恒空
        assert not any(e["type"] in ("entity", "doc") for e in ev)   # 图/文档路零证据
