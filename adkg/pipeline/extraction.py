"""LLM 实体 / 关系抽取（§四 pipeline/extraction.py）。

设计要点：
- chat_json 依赖注入——单测塞假实现，线上是 llm.LLMClient.chat_json
- 类与谓词白名单来自 ontology/schema.yaml（真源在资产）
- 置信度三级分流：≥0.7 入图、0.4–0.7 进 review_queue、<0.4 丢弃（§12.1）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from adkg.models import Entity, Provenance, Relation
from adkg.pipeline.extraction_prompt import build_prompt

ACCEPT = 0.7
REVIEW = 0.4


@dataclass
class ExtractionResult:
    entities: list[Entity] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)
    review: list[dict[str, Any]] = field(default_factory=list)   # 0.4–0.7，待人审
    dropped: int = 0                                             # <0.4


class Extractor:
    def __init__(self, schema: dict, chat_json) -> None:
        self.schema = schema
        self.classes = set(schema["classes"])
        self.predicates = {r["predicate"] for r in schema["relations"]}
        self.chat_json = chat_json

    def extract(self, chunk_text: str, provenance: dict) -> ExtractionResult:
        system, user = build_prompt(self.schema, chunk_text)
        payload = self.chat_json(system, user)
        prov = Provenance(**provenance)
        result = ExtractionResult()

        for item in payload.get("entities", []):
            if item.get("class") not in self.classes:
                continue                                  # 白名单外直接滤（§六）
            try:
                result.entities.append(Entity(
                    entity_class=item["class"], entity_id=item["id"],
                    props=item.get("props", {}), provenance=prov))
            except ValidationError:
                continue                                  # id 前缀非法等 → 丢弃

        for item in payload.get("relations", []):
            if item.get("predicate") not in self.predicates:
                continue
            conf = float(item.get("confidence", 0))
            if conf < REVIEW:
                result.dropped += 1
                continue
            try:
                rel = Relation(source=item["source"], predicate=item["predicate"],
                               target=item["target"], provenance=prov, confidence=conf)
            except ValidationError:
                result.dropped += 1
                continue
            if conf >= ACCEPT:
                result.relations.append(rel)
            else:
                result.review.append({"relation": rel.model_dump(), "confidence": conf})
        return result
