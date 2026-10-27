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

        def chat_json_slow(self, system, user, *, timeout=180, **kw):
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

    def test_can_commit_case随动作门(self):
        # 备忘⑰联动收口：下发标志与 /ingest/case-commit 写门同源——
        # ae（有 create_case）True，optimizer（角色门过但无动作）False
        c = self._client([FINAL])
        assert self._post(c, role="ae", user="Person:li").json()["can_commit_case"] is True
        assert self._post(c, role="optimizer",
                          user="Person:li").json()["can_commit_case"] is False

    def test_空messages422与未认证401(self):
        assert self._client([FINAL]).post("/agent/chat", json={
            "messages": [], "role": "management"}).status_code == 422
        assert self._client([FINAL], ADKG_DEV_AUTH="on").post("/agent/chat", json={
            "messages": [{"role": "user", "content": "x"}]}).status_code == 401


ACTION_THINK = {"action": "list_brands", "args": {}, "think": "先看有哪些品牌"}


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestAgentStream:
    """SSE 事件契约（spec §6）：thought → tool_start → tool_result → reply → done。"""

    def _client(self, payloads):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        env = {k: v for k, v in os.environ.items() if k.startswith(("ADKG_", "NEO4J"))}
        c = TestClient(create_app(env))
        c.app.state.llm = _script_llm(*payloads)
        return c

    def test_事件序列与顺序(self):
        import json as _json
        c = self._client([ACTION_THINK, FINAL])
        with c.stream("POST", "/agent/chat/stream", json={
                "messages": [{"role": "user", "content": "给途野露营出案例草稿"}],
                "role": "management", "user": "Person:chen"}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            events = [_json.loads(line[6:]) for line in r.iter_lines()
                      if line.startswith("data: ")]
        types = [e["type"] for e in events]
        assert types[0] == "thought" and events[0]["text"] == "先看有哪些品牌"
        assert types.index("tool_start") < types.index("tool_result") < types.index("reply")
        assert types[-1] == "done"
        assert events[-1]["has_result"] is True and events[-1]["turns"] == 1
        # draft 事件在 reply 与 done 之间（case_seed 带 FINAL 的草稿）
        assert "draft" in types and types.index("reply") < types.index("draft") < types.index("done")

    def test_未认证401在流开始前(self):
        c = self._client([FINAL])
        c.app.state.env["ADKG_DEV_AUTH"] = "on"
        assert c.post("/agent/chat/stream",
                      json={"messages": [{"role": "user", "content": "x"}]}).status_code == 401


def _mock_platform_up() -> bool:
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:8100/", timeout=3)
        return True
    except Exception:
        return False


def _playwright_ok() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not (_mock_platform_up() and _playwright_ok() and
                        os.environ.get("ADKG_PG_DSN")),
                    reason="星图·模拟 / playwright / .env 不在线")
def test_浏览工具真实点击抓取入图():
    """Playwright 端到端：搜索→点击→抽取→截图子步→权威仲裁两分支。

    状态独立（复审修）：按抓取前库内权威分叉断言——种子 100 走仲裁分支
    （不覆盖 + review_queue 去重一跳），已被实弹覆盖成 80 则走幂等 MERGE 分支。
    """
    import json as j
    import os as _os
    from adkg.api.routes.platform_browser import fetch_creator_from_platform
    from adkg.store.graph import GraphStore

    class _Ctx:
        env = dict(_os.environ)
        graph = GraphStore(_os.environ["ADKG_NEO4J_URI"], _os.environ["ADKG_NEO4J_USER"],
                           _os.environ["ADKG_NEO4J_PASSWORD"])
        role, person = "management", "Person:chen"

    steps: list[dict] = []

    def _emit(kind, **kw):
        steps.append({"kind": kind, **kw})

    ctx = _Ctx()
    ctx.emit = _emit
    with ctx.graph.session() as s:
        rec0 = s.run("MATCH (n:Entity {id: 'Creator:cr11'}) RETURN n.authority AS a").single()
    pre_auth = rec0["a"] if rec0 else None

    result = fetch_creator_from_platform({"query": "铲屎官"}, ctx)
    out = j.loads(result)
    assert out["creator_id"] == "Creator:cr11"
    # 子步齐全且带截图（ZCode 式透明的证据）
    assert len([s_ for s_ in steps if s_["kind"] == "tool_step"]) >= 4
    assert any(s_.get("screenshot", "").startswith("data:image/jpeg") for s_ in steps)

    import psycopg
    with ctx.graph.session() as s:
        rec = s.run("MATCH (n:Entity {id: $id}) RETURN n.prov_source AS src, "
                    "n.name AS name", id="Creator:cr11").single()
    if pre_auth is not None and pre_auth > 80:
        # 仲裁分支：高权威在场不覆盖，冲突去重进 review_queue
        assert out["ingested"] is False and out.get("conflict_queued") is True
        assert rec["src"] == "system_of_record" and "铲屎官" in rec["name"]
        with psycopg.connect(_os.environ["ADKG_PG_DSN"]) as c, c.cursor() as cur:
            cur.execute("SELECT count(*) FROM review_queue WHERE kind = 'conflict'"
                        " AND status = 'open' AND payload->>'entity' = 'Creator:cr11'")
            assert cur.fetchone()[0] == 1          # 幂等重抓不重复挂账
    else:
        # 幂等 MERGE 分支（此前实弹已把节点覆盖成 platform_api/80）
        assert out["ingested"] is True
        assert rec["src"] == "platform_api" and "铲屎官" in rec["name"]
