"""对话式 agent（/agent/chat）：ReAct 循环 + 工具 + 草稿物化。

离线：脚本化 FakeLLM 两轮（先调工具再 final）——循环推进、未知工具容错、
case_seed 物化成可提交草稿（对齐复用 + 未对齐 Person 丢弃）。
端点：真库 skipif 门控（401 / 422 / 全链注入 FakeLLM）。
"""
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)

FINAL = {"final": {"answer": "基于图里的途野露营（户外旅行）给出案例草稿。",
                   "case_seed": {"brand_name": "途野露营", "product_names": ["星链Pro"],
                                 "case_name": "星链Pro 冬季投放", "stage": "proposal",
                                 "person_ids": ["Person:li", "Person:ghost"]},
                   "creative_drafts": None}}
ACTION = {"action": "list_brands", "args": {}}
ACTION_ASK = {"action": "ask_knowledge", "args": {"question": "上月 CPA 最差的素材有哪些？"}}
BAD_ACTION = {"action": "nope", "args": {}}


def _script_llm(*payloads):
    class _L:
        calls = 0

        def chat_json_slow(self, system, user, *, timeout=180):
            _L.calls += 1
            return payloads[min(_L.calls - 1, len(payloads) - 1)]

        def chat_json(self, system, user, **kw):            # /ask 内部（路由/总结）调用；kw=时延预算
            return {"answer": "已按证据回答", "decision": {"intent": "fact"}}

        def embed(self, texts):
            return [[0.0] * 512 for _ in texts]
    return _L()


def _graph():
    from tests.test_case_gen import FakeGraph
    return FakeGraph(entities={
        "Brand:B05": {"class": "Brand", "name": "途野露营", "authority": 100},
        "Person:li": {"class": "Person", "name": "李昂", "authority": 100},
    })


def test_materialize_draft对齐与丢弃():
    from adkg.models import load_schema
    from adkg.pipeline.case_gen import materialize_draft
    d = materialize_draft("agent", {"brand_name": "途野露营", "product_names": ["星链Pro"],
                                    "case_name": "星链Pro 冬季投放", "stage": "proposal",
                                    "person_ids": ["Person:li", "Person:ghost"]},
                          _graph(), load_schema(), now=NOW)
    assert d["brand"]["id"] == "Brand:B05" and d["brand"]["existing"]
    assert d["case"]["id"] == "Case:C-2026-001" and d["case"]["props"]["stage"] == "proposal"
    assert [p["id"] for p in d["persons"]] == ["Person:li"]          # ghost 不存在被丢
    assert any("Person:ghost" in w for w in d["warnings"])
    preds = {r["predicate"] for r in d["relations"]}
    assert {"for_brand", "for_product", "has_product", "responsible_for"} <= preds


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestAgentChat:
    def _client(self, payloads, **overrides):
        from fastapi.testclient import TestClient

        from adkg.api.main import create_app
        env = {k: v for k, v in os.environ.items() if k.startswith(("ADKG_", "NEO4J"))}
        env.update(overrides)
        c = TestClient(create_app(env))
        c.app.state.llm = _script_llm(*payloads)
        return c

    def _post(self, client, **kw):
        return client.post("/agent/chat", json={
            "messages": [{"role": "user", "content": "给途野露营出一个案例草稿"}],
            "role": "management", "user": "Person:chen", **kw})

    def test_两轮循环_工具轨迹与可提交草稿(self):
        c = self._client([ACTION, FINAL])
        r = self._post(c)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["trace"] and body["trace"][0]["tool"] == "list_brands"
        assert "途野露营" in body["reply"]
        d = body["case_draft"]
        assert d["brand"]["id"] == "Brand:B05" and d["brand"]["existing"]
        assert d["case"]["id"].startswith("Case:C-2026-")
        assert {rel["predicate"] for rel in d["relations"]} >= {"for_brand", "responsible_for"}

    def test_未知工具容错并继续循环(self):
        c = self._client([BAD_ACTION, FINAL])
        r = self._post(c)
        assert r.status_code == 200
        body = r.json()
        assert "未知工具" in body["trace"][0]["result"]
        assert body["case_draft"]["brand"]["id"] == "Brand:B05"

    def test_ask_knowledge工具走三路管线(self):
        c = self._client([ACTION_ASK, FINAL])
        r = self._post(c)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["trace"][0]["tool"] == "ask_knowledge"
        assert "已按证据回答" in body["trace"][0]["result"]

    def test_空messages422与未认证401(self):
        assert self._client([FINAL]).post("/agent/chat", json={
            "messages": [], "role": "management"}).status_code == 422
        assert self._client([FINAL], ADKG_DEV_AUTH="on").post("/agent/chat", json={
            "messages": [{"role": "user", "content": "x"}]}).status_code == 401
