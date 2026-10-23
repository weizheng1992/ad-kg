"""素材草稿（/creative/brands · /creative/draft）：prompt 组装单测 + 端点链路。

生成链路端点测试注入 FakeLLM（app.state.llm 预置即命中 ask._llm 的缓存分支），
证据组装走真库（text2sql 模板 + vector 路 + 图上下文），生成内容用假实现固定。
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


class FakeLLM:
    def __init__(self):
        self.last_system = self.last_user = ""
        self.slow_used = False

    def chat_json(self, system: str, user: str, **kw) -> dict:   # kw=ask 交互路时延预算
        self.last_system, self.last_user = system, user
        return {"creatives": [{"title": "户外老爹鞋 15s", "format": "信息流视频",
                               "platform": "douyin", "hook_3s": "前3秒品牌露出",
                               "script": "镜1：…", "copy": "标题+正文",
                               "based_on": ["#1"]}]}

    def chat_json_slow(self, system: str, user: str, *, timeout: int = 90, **kw) -> dict:
        self.slow_used = True                            # 大证据 prompt 应走长超时档
        return self.chat_json(system, user)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 512 for _ in texts]              # bge-small-zh-v1.5 维度


def _client(**overrides):
    from fastapi.testclient import TestClient

    from adkg.api.main import create_app
    env = {k: v for k, v in os.environ.items() if k.startswith(("ADKG_", "NEO4J"))}
    env.update(overrides)
    c = TestClient(create_app(env))
    c.app.state.llm = FakeLLM()                          # 预置即命中 ask._llm 缓存分支
    return c


def test_user_prompt含全部证据段():
    from adkg.api.routes.creative import _user_prompt
    u = _user_prompt({"id": "Brand:B05", "name": "途野露营", "category": "户外旅行"},
                     "冲锋衣", "douyin", 3,
                     {"商品知识": [{"ref": "chunk:1"}], "参考素材": [{"creative_id": "c1"}],
                      "创意规范": [{"id": "G-01"}]})
    assert "途野露营" in u and "冲锋衣" in u and "douyin" in u and '"条数": 3' in u
    assert "chunk:1" in u and "c1" in u and "G-01" in u


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestCreativeEndpoints:
    def test_brands列表(self):
        r = _client().get("/creative/brands")
        assert r.status_code == 200
        brands = r.json()["brands"]
        ids = {b["id"] for b in brands}
        assert "Brand:B05" in ids and any(b.get("category") for b in brands)

    def test_draft品牌缺失422与未知404(self):
        c = _client()
        assert c.post("/creative/draft", json={"role": "management"}).status_code == 422
        assert c.post("/creative/draft", json={
            "brand_id": "Brand:nope", "role": "management"}).status_code == 404

    def test_draft角色门403(self):
        r = _client().post("/creative/draft", json={
            "brand_id": "Brand:B05", "role": "client", "user": "Person:client_a"})
        assert r.status_code == 403

    def test_未认证401(self):
        c = _client(ADKG_DEV_AUTH="on")
        c.app.state.llm = FakeLLM()
        assert c.get("/creative/brands").status_code == 401

    def test_生成全链_证据与规范进prompt_草稿返回(self):
        c = _client()
        r = c.post("/creative/draft", json={
            "brand_id": "Brand:B05", "product": "冲锋衣", "n": 2,
            "role": "management", "user": "Person:chen"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["brand"]["name"] == "途野露营"
        assert len(body["drafts"]) == 1 and body["drafts"][0]["based_on"] == ["#1"]
        assert "机判与人工审" in body["notice"]
        fake = c.app.state.llm
        assert fake.slow_used and fake.last_system.startswith("你是广告创意助手")
        assert "冲锋衣" in fake.last_user and "G-0" in fake.last_user      # 规范进 prompt
        assert "参考素材" in fake.last_user
