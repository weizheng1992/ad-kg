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
        assert fact["rows"] and "avg_cpa" in fact["rows"][0]

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

    def test_生产模式无token返回401(self):
        c = _client(ADKG_DEV_AUTH="on")
        assert c.post("/ask", json={"question": "x", "role": "management"}).status_code == 401

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
        assert r.json()["neighbors"] == []            # B04 之外的子图零邻居

    def test_不存在实体返回404(self, client):
        assert client.get("/graph/entity", params={
            "id": "Brand:NOPE", "role": "management"}).status_code == 404
