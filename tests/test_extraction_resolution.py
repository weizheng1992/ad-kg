"""extraction / resolution 单元测试——LLM 与嵌入全部注入假实现，离线跑。

阈值口径：≥0.7 入图、0.4–0.7 进 review_queue、<0.4 丢弃（§12.1）；
对齐 L2 相似度阈值 τ 随嵌入模型在 seed 上标定（§7.4，初值 0.75）。
"""
import pytest

from adkg.models import load_schema
from adkg.pipeline.extraction import Extractor, ExtractionResult
from adkg.pipeline.resolution import normalize_name, resolve_by_alias, similar_candidates

SCHEMA = load_schema()


# ---------------------------------------------------------------- extraction
class TestExtractor:
    def _fake_chat(self, payload: dict):
        return lambda system, user: payload

    def test_合法输出被校验为模型实例(self):
        payload = {
            "entities": [
                {"class": "Brand", "id": "Brand:A", "props": {"category": "电商"}},
                {"class": "Case", "id": "Case:C-2025-118", "props": {"stage": "live"}},
            ],
            "relations": [
                {"source": "Case:C-2025-118", "predicate": "for_brand",
                 "target": "Brand:A", "confidence": 0.9},
            ],
        }
        result = Extractor(schema=SCHEMA, chat_json=self._fake_chat(payload)).extract(
            "chunk 文本", provenance={"source_type": "wiki", "source_id": "file:x.md",
                                      "fetched_at": "2026-10-19T00:00:00+08:00"})
        assert isinstance(result, ExtractionResult)
        assert [e.entity_id for e in result.entities] == ["Brand:A", "Case:C-2025-118"]
        assert result.entities[0].props["category"] == "电商"
        assert result.relations[0].predicate == "for_brand"

    def test_未知类与未知谓词被白名单滤掉(self):
        payload = {
            "entities": [
                {"class": "Brand", "id": "Brand:A", "props": {}},
                {"class": "Alien", "id": "Alien:X", "props": {}},          # 不在 12 类
            ],
            "relations": [
                {"source": "Brand:A", "predicate": "teleports_to",        # 不在关系表
                 "target": "Brand:A", "confidence": 0.9},
                {"source": "Case:C-1", "predicate": "nonexistent",
                 "target": "Brand:A", "confidence": 0.9},
            ],
        }
        result = Extractor(schema=SCHEMA, chat_json=self._fake_chat(payload)).extract(
            "t", provenance={"source_type": "wiki", "source_id": "f",
                             "fetched_at": "2026-10-19T00:00:00+08:00"})
        assert [e.entity_id for e in result.entities] == ["Brand:A"]
        assert result.relations == []

    def test_置信度三级分流(self):
        payload = {
            "entities": [],
            "relations": [
                {"source": "Creative:c1", "predicate": "violates",
                 "target": "Guideline:G-01", "confidence": 0.85},   # 入图
                {"source": "Creative:c2", "predicate": "violates",
                 "target": "Guideline:G-01", "confidence": 0.55},   # 人审
                {"source": "Creative:c3", "predicate": "violates",
                 "target": "Guideline:G-01", "confidence": 0.2},    # 丢弃
            ],
        }
        result = Extractor(schema=SCHEMA, chat_json=self._fake_chat(payload)).extract(
            "t", provenance={"source_type": "wiki", "source_id": "f",
                             "fetched_at": "2026-10-19T00:00:00+08:00"})
        assert [r.source for r in result.relations] == ["Creative:c1"]
        assert [r["relation"]["source"] for r in result.review] == ["Creative:c2"]
        assert result.dropped == 1


# ---------------------------------------------------------------- resolution L1/L2
class TestResolution:
    def test_名称归一_全半角_大小写_平台前后缀(self):
        assert normalize_name(" 抖音·素材A ") == normalize_name("抖音·素材a")
        assert normalize_name("【官】品牌B") == normalize_name("品牌B")     # 常见装饰前后缀
        assert normalize_name("Ａｐｐ　下载") == normalize_name("App 下载")  # 全角→半角

    def test_别名直接命中即接受(self):
        aliases = {("douyin", "dy_889"): "Creative:creative_992"}
        assert resolve_by_alias("douyin", "dy_889", aliases) == "Creative:creative_992"
        assert resolve_by_alias("douyin", "nope", aliases) is None

    def test_L2_相似候选按阈值过滤(self):
        import math

        def fake_embed(texts):
            # "品牌A 女装" 与已知名同向，与另一个近乎正交
            table = {"品牌A 女装": [1.0, 0.0], "别的": [0.0, 1.0]}
            return [table.get(t, [0.7, 0.7]) for t in texts]

        known = {"Brand:brand_a": "品牌A 女装", "Brand:brand_b": "别的"}
        cands = similar_candidates("品牌A 女装", known, embed=fake_embed, top_k=5,
                                   threshold=0.75)
        assert cands and cands[0][0] == "Brand:brand_a"
        assert cands[0][1] == pytest.approx(1.0)

        none = similar_candidates("全新词", known, embed=fake_embed, top_k=5,
                                  threshold=0.99)
        assert none == []                       # 相似度不够不硬配（§7.4）
