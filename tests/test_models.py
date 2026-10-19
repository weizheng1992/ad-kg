"""models.py 不变量测试——README §十二 的硬约定落在类型层。

约定来源：
- provenance 四元组强制、authority 由 source_type 查表 → §12.1 / §12.2
- 事实表 confidence 恒为 1 → §12.1
- 实体 ID {class}:{slug} → §12.5
- RouterPlan 步骤依赖只能引用更早的步骤 → §7.3
"""
import pytest
from pydantic import ValidationError

from adkg.models import (
    AUTHORITY_LADDER,
    CaseStage,
    Chunk,
    Entity,
    Fact,
    Provenance,
    Relation,
    RouterPlan,
    RouteStep,
    SourceType,
)


class TestProvenance:
    def test_缺任一必填即拒绝(self):
        ok = dict(source_type="platform_api", source_id="douyin:report:1",
                  fetched_at="2026-01-02T03:00:00+08:00")
        # 完整三元组 + 派生 authority 可入库
        p = Provenance(**ok)
        assert p.authority == 80
        # 缺任何一个都拒绝（四元组强制）
        for k in ("source_type", "source_id", "fetched_at"):
            with pytest.raises(ValidationError):
                Provenance(**{key: v for key, v in ok.items() if key != k})

    def test_authority_由查表派生_手给错值拒绝(self):
        p = Provenance(source_type="official_doc", source_id="feishu:doc:x",
                       fetched_at="2026-01-01T00:00:00+08:00")
        assert p.authority == AUTHORITY_LADDER[SourceType.OFFICIAL_DOC] == 60
        with pytest.raises(ValidationError, match="authority"):
            Provenance(source_type="official_doc", source_id="feishu:doc:x",
                       fetched_at="2026-01-01T00:00:00+08:00", authority=80)

    def test_source_type_枚举外拒绝(self):
        with pytest.raises(ValidationError):
            Provenance(source_type="wechat", source_id="x",
                       fetched_at="2026-01-01T00:00:00+08:00")


class TestEntityAndRelation:
    def test_实体id必须是_class_slug前缀(self):
        prov = Provenance(source_type="system_of_record", source_id="case_sys:1",
                          fetched_at="2026-01-01T00:00:00+08:00")
        e = Entity(entity_class="Case", entity_id="Case:C-2026-008",
                   props={"stage": "live"}, provenance=prov)
        assert e.props["stage"] == CaseStage.LIVE
        with pytest.raises(ValidationError, match="开头"):
            Entity(entity_class="Case", entity_id="Creative:c1", props={}, provenance=prov)

    def test_case_stage_枚举与终态(self):
        assert {s.value for s in CaseStage} == {"proposal", "live", "closed", "lost", "terminated"}

    def test_relation_置信度越界拒绝(self):
        prov = Provenance(source_type="conversation", source_id="aigc:1",
                          fetched_at="2026-01-01T00:00:00+08:00")
        r = Relation(source="Creative:creative_992", predicate="violates",
                     target="Guideline:G-03", provenance=prov, confidence=0.91)
        assert r.confidence == 0.91
        with pytest.raises(ValidationError):
            Relation(source="Creative:creative_992", predicate="violates",
                     target="Guideline:G-03", provenance=prov, confidence=1.5)


class TestChunkAndFact:
    def test_chunk_携带权限下推元数据列(self):
        c = Chunk(doc_id="feishu:doc:x", chunk_index=0, text="前 3 秒须出现品牌标识",
                  entity_class="Guideline", provenance=Provenance(
                      source_type="official_doc", source_id="feishu:doc:x",
                      fetched_at="2026-01-01T00:00:00+08:00"))
        assert c.brand_id is None and c.case_id is None  # 元数据列可空，检索时按角色过滤

    def test_fact_confidence_恒为_1_未对齐即_unmatched(self):
        prov = Provenance(source_type="platform_api", source_id="douyin:report:1",
                          fetched_at="2026-01-02T03:00:00+08:00")
        f = Fact(platform="douyin", date="2025-12-01",
                 campaign_local_id="dy_c1", creative_local_id="dy_889",
                 metrics={"cost": 120.5, "impressions": 30000}, provenance=prov)
        assert f.confidence == 1.0
        assert f.creative_id is None and f.unmatched  # entity_alias 没换算上 → 不进跨平台对比
        assert f.date.isoformat() == "2025-12-01"     # 素材粒度含日期维（§八）


class TestRouterPlan:
    def _prov(self):
        return Provenance(source_type="conversation", source_id="x:1",
                          fetched_at="2026-01-01T00:00:00+08:00")

    def test_依赖只能引用更早步骤(self):
        ok = RouterPlan(steps=[
            RouteStep(step_id="g", route="graph", depends_on=[], confidence=0.93),
            RouteStep(step_id="t", route="text2sql", depends_on=["g"],
                      params={"entity_ids_from": "g"}),
            RouteStep(step_id="v", route="vector", depends_on=["t"]),
        ], fallback=False)
        assert [s.step_id for s in ok.steps] == ["g", "t", "v"]
        assert ok.steps[0].confidence == 0.93           # §7.3 steps 带依赖与置信度

    def test_引用未来步骤拒绝_重复id拒绝(self):
        with pytest.raises(ValidationError, match="更早"):
            RouterPlan(steps=[
                RouteStep(step_id="g", route="graph", depends_on=["t"]),
                RouteStep(step_id="t", route="text2sql", depends_on=[]),
            ], fallback=False)
        with pytest.raises(ValidationError, match="重复"):
            RouterPlan(steps=[
                RouteStep(step_id="g", route="graph", depends_on=[]),
                RouteStep(step_id="g", route="vector", depends_on=[]),
            ], fallback=False)
