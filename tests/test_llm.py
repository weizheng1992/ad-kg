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
