"""飞书 connector 单元测试（离线，transport 注入假实现）+ 凭据连通性集成测试。"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from adkg.connectors.feishu import FeishuConnector


class FakeFeishu:
    """按路径返回预置响应，记录调用以验证 token 缓存。"""

    def __init__(self, *, code=0, docs=("doctoken1", "doctoken2"), empty_doc=False):
        self.calls: list[str] = []
        self.code = code
        self.docs = docs
        self.empty_doc = empty_doc

    def __call__(self, method, url, *, headers=None, json=None):
        self.calls.append(url)
        if url.endswith("/tenant_access_token/internal"):
            if self.code:
                return {"code": self.code, "msg": "app secret 不匹配"}
            return {"code": 0, "tenant_access_token": "t-fake", "expire": 7200}
        if "/raw_content" in url:
            token = url.split("/documents/")[1].split("/")[0]
            return {"code": 0, "data": {"content": "" if self.empty_doc else f"# 文档 {token}\n\n正文"}}
        if "/documents/" in url:
            token = url.split("/documents/")[1]
            return {"code": 0, "data": {"document": {"document_id": token,
                                                     "revision_id": 42, "title": "t"}}}
        raise AssertionError(f"未预期的请求 {url}")


class TestFeishuConnector:
    def test_产出带版本与回跳的记录(self):
        conn = FeishuConnector("id", "sec", ["doctoken1", "doctoken2"],
                               transport=FakeFeishu())
        records = list(conn.fetch())
        assert [r.provenance.version for r in records] == ["42", "42"]
        assert records[0].provenance.source_id == "feishu:doc:doctoken1"
        assert records[0].provenance.source_url == "https://feishu.cn/docx/doctoken1"
        assert records[0].text.startswith("# 文档")

    def test_token只取一次_跨文档复用(self):
        fake = FakeFeishu()
        list(FeishuConnector("id", "sec", ["a", "b", "c"], transport=fake).fetch())
        token_calls = [u for u in fake.calls if u.endswith("/tenant_access_token/internal")]
        assert len(token_calls) == 1                    # 缓存生效

    def test_空文档跳过(self):
        conn = FeishuConnector("id", "sec", ["doctoken1"], transport=FakeFeishu(empty_doc=True))
        assert list(conn.fetch()) == []

    def test_鉴权失败抛出带信息(self):
        conn = FeishuConnector("id", "sec", ["doctoken1"], transport=FakeFeishu(code=99991663))
        with pytest.raises(RuntimeError, match="99991663"):
            list(conn.fetch())


_CRED = bool(os.environ.get("FEISHU_APP_ID") and os.environ.get("FEISHU_APP_SECRET")
             and "change-me" not in os.environ.get("FEISHU_APP_ID", ""))


@pytest.mark.skipif(not _CRED, reason=".env 未配置飞书凭据")
class TestFeishuLive:
    def test_凭据可换tenant_token(self):
        conn = FeishuConnector(os.environ["FEISHU_APP_ID"],
                               os.environ["FEISHU_APP_SECRET"], [])
        tok = conn._tenant_token()
        assert tok.startswith("t-")
