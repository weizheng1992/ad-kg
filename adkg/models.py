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
    """

    metadata_filter: dict[str, Any] = Field(default_factory=dict)  # vector 路：下推进 SQL
    visible_entity_ids: frozenset[str] = Field(default_factory=frozenset)  # graph 路：Cypher 白名单
    sql_predicate: str = ""  # text2sql 路：系统拼进 WHERE，不信任生成的 SQL
    allowed_columns: list[str] = Field(default_factory=list)  # 视图/列白名单
    mask_rules: list[str] = Field(default_factory=list)  # assemble 出口脱敏（如 Person 姓名）


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
