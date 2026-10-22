"""LLM 适配层纯函数测试（离线，不触网）。"""
import pytest

from adkg.llm import loads_json


class TestLoadsJson:
    def test_纯json直读(self):
        assert loads_json('{"a": 1}') == {"a": 1}

    def test_json后带尾随文本(self):
        """glm-4-flash 偶发输出 JSON + 换行说明文字（评测实录，§7.2 降级）。"""
        assert loads_json('{"verdict": true}\n以上是判断结果。') == {"verdict": True}

    def test_围栏包裹(self):
        assert loads_json('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}

    def test_值内花括号配平(self):
        assert loads_json('{"a": "x{y}z"} 尾随') == {"a": "x{y}z"}

    def test_无对象则照常抛错(self):
        with pytest.raises(Exception):
            loads_json("完全没有 JSON")


class TestChatJsonBudget:
    """交互路时延预算（§7.2）：收紧参数要原样下传 with_options，默认调用不换 client。"""

    def _client(self):
        from types import SimpleNamespace as NS

        from adkg.llm import LLMClient
        c = LLMClient.__new__(LLMClient)                    # 不触网：不走 __init__
        calls = []

        def _create(**kw):
            return NS(choices=[NS(message=NS(content='{"ok": 1}'))])

        def _with_options(**kw):
            calls.append(kw)
            return NS(chat=NS(completions=NS(create=_create)))

        c._client = NS(chat=NS(completions=NS(create=_create)),
                       with_options=_with_options, timeout=30, max_retries=3)
        c._model = "m"
        return c, calls

    def test_默认不换client(self):
        c, calls = self._client()
        assert c.chat_json("s", "u") == {"ok": 1}
        assert calls == []                                  # 默认 30s×3 原样走主 client

    def test_预算参数下传(self):
        c, calls = self._client()
        c.chat_json("s", "u", timeout=15, max_retries=0)
        assert calls == [{"timeout": 15, "max_retries": 0}]

    def test_只传其一另一保持默认(self):
        c, calls = self._client()
        c.chat_json("s", "u", timeout=8)
        assert calls == [{"timeout": 8, "max_retries": 3}]


def test_agent总结载荷瘦身_留正文去溯源():
    """_agent_answer prompt 去掉 ref/provenance（纯耗 token），保留 quote/props/rows
    与名称映射（§7.2 时延预算配套；响应面 evidence 不动）。"""
    from adkg.api.routes.ask import _agent_answer

    class _Cap:
        def chat_json(self, system, user, **kw):
            _Cap.last_user, _Cap.kw = user, kw
            return {"answer": "ok"}

    ev = [{"type": "doc", "ref": "chunk:d1#3", "quote": "信息流视频时长不超过30秒",
           "provenance": {"source_type": "official_doc", "authority": 60}},
          {"type": "entity", "ref": "Brand:B01", "props": {"name": "律动星球"},
           "provenance": {"source_type": "system_of_record", "authority": 100}},
          {"type": "fact", "rows": [{"creative_name": "大促静态 4s", "cpa": 48.78}],
           "sql": "SELECT ..."}]
    out = _agent_answer(_Cap(), "信息流视频时长规范", ev, {"Brand:B01": "律动星球"})
    assert out == "ok"
    assert "provenance" not in _Cap.last_user and "chunk:d1#3" not in _Cap.last_user
    assert "SELECT" not in _Cap.last_user
    assert "信息流视频时长不超过30秒" in _Cap.last_user      # vector 正文必须保留
    assert "律动星球" in _Cap.last_user and "48.78" in _Cap.last_user
    assert _Cap.kw == {"timeout": 35, "max_retries": 0}     # 限时单发（§7.2）

    def test_默认不换client(self, monkeypatch):
        c, calls = self._client(monkeypatch)
        c.chat_json("s", "u")
        assert calls == []                                  # 默认 30s×3 原样走主 client

    def test_预算参数下传(self, monkeypatch):
        c, calls = self._client(monkeypatch)
        c.chat_json("s", "u", timeout=15, max_retries=0)
        assert calls == [{"timeout": 15, "max_retries": 0}]

    def test_只传其一另一保持默认(self, monkeypatch):
        c, calls = self._client(monkeypatch)
        c.chat_json("s", "u", timeout=8)
        assert calls == [{"timeout": 8, "max_retries": 3}]
