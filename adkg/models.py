"""层间唯一数据契约（README §四：层与层只通过明确的数据模型交互）。

不变量对应 README §十二：
- Provenance 四元组强制，authority 由 source_type 查表派生（§12.1 / §12.2）
- Fact.confidence 恒为 1（§12.1）；creative_id 未换算上即 unmatched，不进跨平台对比（§12.5）
- 实体 ID {class}:{slug} 平台无关（§12.5）
- RouterPlan 步骤依赖只能指向更早的步骤（§7.3 串行计划）
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class SourceType(str, Enum):
    """provenance 来源类型；authority 五级与之一一对应（§12.2）。

    CRM / 案例系统 / 组织系统等内部主数据源归 system_of_record。
    """

    SYSTEM_OF_RECORD = "system_of_record"
    PLATFORM_API = "platform_api"
    OFFICIAL_DOC = "official_doc"
    WIKI = "wiki"
    CONVERSATION = "conversation"


def _load_authority_ladder() -> dict[SourceType, int]:
    """从 ontology/authority.yaml 加载——唯一语义真源在资产，不在代码。"""
    path = Path(__file__).resolve().parents[1] / "ontology" / "authority.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {SourceType(k): int(v) for k, v in data["ladder"].items()}


AUTHORITY_LADDER: dict[SourceType, int] = _load_authority_ladder()


def load_schema() -> dict:
    """加载 ontology/schema.yaml（类 / 关系 / 约束 / 动作词表）。"""
    path = Path(__file__).resolve().parents[1] / "ontology" / "schema.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def global_classes() -> frozenset[str]:
    """schema 驱动的全局类（global_class: true：不挂锚点、不参与 row_filter，§12.4）。
    graph_search 与 /graph/entity 的类豁免共用——{Metric, Guideline, Channel} 字面量
    曾两处硬编码，schema 加全局类会静默漂移（2026-10-24 收敛）。"""
    return frozenset(c for c, cfg in load_schema()["classes"].items()
                     if cfg.get("global_class"))


class CaseStage(str, Enum):
    """Case 状态机（§六）：proposal→live｜lost，live→closed｜terminated，终态不可逆。"""

    PROPOSAL = "proposal"
    LIVE = "live"
    CLOSED = "closed"
    LOST = "lost"
    TERMINATED = "terminated"


class RouteType(str, Enum):
    GRAPH = "graph"
    VECTOR = "vector"
    TEXT2SQL = "text2sql"


class Provenance(BaseModel):
    """来源四元组，任何入库必带（§12.1）。"""

    source_type: SourceType
    source_id: str = Field(min_length=1)
    fetched_at: datetime
    authority: int | None = None  # 由 source_type 查表派生，不单独配置
    source_url: str | None = None
    version: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _derive_authority(self) -> "Provenance":
        expected = AUTHORITY_LADDER[self.source_type]
        if self.authority is None:
            self.authority = expected
        elif self.authority != expected:
            raise ValueError(
                f"authority 由 source_type 查表得出（{self.source_type.value}={expected}），"
                f"不接受手给值 {self.authority}"
            )
        return self


class Entity(BaseModel):
    """图节点。entity_id 格式 {class}:{slug}，平台无关（§12.5）。"""

    entity_class: str
    entity_id: str
    props: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance

    @model_validator(mode="after")
    def _check_id_prefix(self) -> "Entity":
        prefix = f"{self.entity_class}:"
        if not self.entity_id.startswith(prefix):
            raise ValueError(f"实体 id 必须以 {prefix} 开头（{{class}}:{{slug}}）")
        return self


class Relation(BaseModel):
    """图关系，带置信度；violates 等断言来自低 authority 的 conversation。"""

    source: str
    predicate: str
    target: str
    provenance: Provenance
    confidence: float = Field(default=1.0, ge=0, le=1)


class Chunk(BaseModel):
    """向量层 chunk；class / brand_id / case_id 是权限下推的元数据列（§八）。"""

    doc_id: str
    chunk_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    entity_class: str | None = None
    brand_id: str | None = None
    case_id: str | None = None
    embedding: list[float] | None = None
    provenance: Provenance


class Fact(BaseModel):
    """素材粒度事实行（platform × campaign × creative × day，§八——一行一素材一平台一天）。

    creative_local_id 是平台 ID；creative_id 是经 entity_alias 换算后的本体 ID，
    换算不上（None）即 unmatched，不进跨平台对比。维度列由 etl_facts 物化。
    """

    platform: str
    date: date
    campaign_local_id: str
    creative_local_id: str
    creative_id: str | None = None
    campaign_id: str | None = None
    case_id: str | None = None
    brand_id: str | None = None
    metrics: dict[str, float]
    provenance: Provenance
    confidence: float = Field(default=1.0, frozen=True)  # 事实表恒为 1（§12.1）

    @property
    def unmatched(self) -> bool:
        return self.creative_id is None


class PermissionPlan(BaseModel):
    """permissions.yaml 的翻译产物（§7.3）：三路与 assemble 出口只消费本对象。

    深模块 guards/permission.py 的输出接口——翻译收口在一处，越权测试只打这里。
    执行侧五方法（2026-10-28 收口，§12.4 出口唯一执行点）：端点不再手推
    「我被拒了吗 / 这个类可见吗 / 哪些字段能出门」——此前 ~8 个 route 各抄一份，
    语义已漂（403/404 不一致、client 的 Case.lost_reason 详情路丢失）。
    """

    metadata_filter: dict[str, Any] = Field(default_factory=dict)  # vector 路：下推进 SQL
    visible_entity_ids: frozenset[str] = Field(default_factory=frozenset)  # graph 路：Cypher 白名单
    global_classes: frozenset[str] = Field(default_factory=global_classes)  # 类白名单豁免的全局类（schema 驱动，graph 路消费）
    sql_predicate: str = ""  # text2sql 路：系统拼进 WHERE，不信任生成的 SQL
    allowed_columns: list[str] = Field(default_factory=list)  # 视图/列白名单
    deny_properties: frozenset[str] = Field(default_factory=frozenset)  # graph 路证据的属性黑名单（Class.prop）
    allow_properties: frozenset[str] = Field(default_factory=frozenset)  # 同出口的属性白名单（外部角色，空=不限）
    mask_rules: list[str] = Field(default_factory=list)  # assemble 出口脱敏（如 Person 姓名）
    deny_all: bool = False  # 行权限 fail-closed（§12.4）：person 缺失/无效时三路全拒（graph/vector 零证据、text2sql 恒假谓词）

    # ------------------------------------------------- 执行侧：类/行门
    def _deny(self, code: int, msg: str) -> None:
        from fastapi import HTTPException                  # 惰性：models 保持纯域层
        raise HTTPException(code, msg)

    def gate(self, cls: str, *, not_found: bool = False,
             anchor_ok: bool = False) -> None:
        """列表端点类门（fail-closed）：deny_all 或类不在白名单即拒。

        anchor_ok：锚点角色（可见集非空）豁免类闸——client 类白名单无 Brand，
        但 external_for 路径上的品牌可见（/brands 列表语义，同 /graph/entity 锚点豁免）。
        not_found：详情面用 404（不泄露存在性）；列表端点默认 403（调用方据此隐菜单）。
        """
        code = 404 if not_found else 403
        if self.deny_all:
            self._deny(code, "行权限未生效（缺有效身份），拒绝读取")
        if cls not in set(self.metadata_filter.get("entity_class__in", [])):
            if anchor_ok and self.visible_entity_ids:
                return                                     # 锚点角色只看自己那一片
            self._deny(code, f"类 {cls} 不在当前角色白名单")

    def gate_detail(self, cls: str, eid: str, *, label: str = "实体",
                    not_found: bool = False) -> None:
        """详情端点门：deny_all → 锚点外（全局类豁免）→ 类白名单（锚点内豁免）。

        次序钉死：先可见集后类闸——client 查他牌 Brand 应得锚点外 404，而不是
        类闸 403（/brands 详情与 /graph/entity 的既有语义，2026-10-28 统一）。
        可见集失败恒 404（存在性隐藏）；deny_all 与类闸按 not_found 取 403/404
        （/brands 详情 403 面，/graph/entity 404 面）。
        """
        code = 404 if not_found else 403
        if self.deny_all:
            self._deny(code, "行权限未生效（缺有效身份），拒绝读取")
        if self.visible_entity_ids and eid not in self.visible_entity_ids \
                and cls not in self.global_classes:
            self._deny(404, f"{label}不在当前身份可见范围（锚点外）")
        allowed = set(self.metadata_filter.get("entity_class__in", []))
        if cls not in allowed and cls not in self.global_classes \
                and eid not in self.visible_entity_ids:
            self._deny(code, f"类 {cls} 不在当前角色白名单")

    def require_visible(self, eid: str, *, label: str = "实体") -> None:
        """行可见集单点校验（写端点等无类闸场景）：锚点外 404，不泄露存在性。"""
        if self.visible_entity_ids and eid not in self.visible_entity_ids:
            self._deny(404, f"{label}不在当前身份可见范围（锚点外）")

    # ------------------------------------------------- 执行侧：集合与属性
    def filter_visible(self, items: list[dict], key: str = "id") -> list[dict]:
        """行可见集过滤（visible_entity_ids 的列表执行点）：无行过滤全量放行。"""
        if not self.visible_entity_ids:
            return items
        return [i for i in items if i.get(key) in self.visible_entity_ids]

    def project(self, props: dict, cls: str) -> dict:
        """属性出口过滤（§12.4 唯一执行点）：外部角色按 allow_properties 白名单
        （fail-closed，schema 新增属性默认不可见），内部按 deny_properties 黑名单。
        props 键为裸属性名；身份/呈现键（id、brand_id 等）由调用方自行保留——
        本方法只裁 Class 属性。"""
        if self.allow_properties:
            allow = {p.split(".", 1)[1] for p in self.allow_properties
                     if p.startswith(f"{cls}.")}
            return {k: v for k, v in props.items() if k in allow}
        denied = {d.split(".", 1)[1] for d in self.deny_properties
                  if d.startswith(f"{cls}.")}
        return {k: v for k, v in props.items() if k not in denied}


class RouteStep(BaseModel):
    """路由计划一步；confidence 是该路的意图置信度，params 携带所需上下文。"""

    step_id: str = Field(min_length=1)
    route: RouteType
    depends_on: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    params: dict[str, Any] = Field(default_factory=dict)


class RouterPlan(BaseModel):
    """路由计划（§7.3）：steps 带依赖与置信度、fallback 标志；ask.py 只解释执行。"""

    steps: list[RouteStep] = Field(min_length=1)
    fallback: bool = False  # True = 置信度低，三路全跑由 assemble 去重

    @model_validator(mode="after")
    def _deps_point_earlier(self) -> "RouterPlan":
        seen: set[str] = set()
        for step in self.steps:
            if step.step_id in seen:
                raise ValueError(f"步骤 id 重复：{step.step_id}")
            for dep in step.depends_on:
                if dep not in seen:
                    raise ValueError(f"依赖只能指向更早的步骤：{step.step_id} → {dep}")
            seen.add(step.step_id)
        return self
