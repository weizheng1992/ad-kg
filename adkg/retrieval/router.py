"""router（§7.3）：意图识别 → RouterPlan（steps 带依赖与置信度）。

规则版是 §7.2 降级矩阵的兜底实现（意图关键词模板）；LLM 版接口同名同返回
（chat_json 注入，有 key 时由 API 层优先使用）。RouterPlan 是 models 一等类型，
ask 只解释执行——路由评测直接对 plan 断言（§7.3）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from adkg.models import RouteStep, RouterPlan

_OPS = ("删除", "删掉", "暂停", "停掉", "下掉")
_FACT = ("多少", "消耗", "cpa", "ctr", "cvr", "roi", "最差", "最好", "排名",
         "成本", "转化", "趋势", "均值")
_GRAPH = ("谁", "哪些案例", "名下", "负责", "对接", "关系链", "多少个")
_CONCEPT = ("规范", "要求", "时长", "规定", "vi", "广告法", "尺寸", "口径")
_ATTR = ("有没有关系", "为什么", "归因", "原因", "和.*规范")


@dataclass(frozen=True)
class RouteDecision:
    intent: str                    # graph | fact | concept | attribution | operation | unknown
    plan: RouterPlan | None        # operation → None（API 层返回端点指引，§7.3）
    confidence: float


def _hits(q: str, kws: tuple[str, ...]) -> int:
    return sum(1 for k in kws if k in q or re.search(k, q))


def rule_route(question: str) -> RouteDecision:
    q = question.lower()
    if _hits(q, _OPS):
        return RouteDecision("operation", None, 0.95)
    if _hits(q, _ATTR) and (_hits(q, _FACT) or _hits(q, _CONCEPT)):
        plan = RouterPlan(steps=[
            RouteStep(step_id="g", route="graph", confidence=0.85),
            RouteStep(step_id="t", route="text2sql", depends_on=["g"],
                      confidence=0.85, params={"entity_ids_from": "g"}),
            RouteStep(step_id="v", route="vector", depends_on=["t"], confidence=0.8),
        ])
        return RouteDecision("attribution", plan, 0.85)
    if _hits(q, _FACT):
        plan = RouterPlan(steps=[RouteStep(step_id="t", route="text2sql", confidence=0.9)])
        return RouteDecision("fact", plan, 0.9)
    if _hits(q, _GRAPH):
        plan = RouterPlan(steps=[
            RouteStep(step_id="g", route="graph", confidence=0.85),
            RouteStep(step_id="v", route="vector", confidence=0.6),   # 辅助：补描述
        ])
        return RouteDecision("graph", plan, 0.85)
    if _hits(q, _CONCEPT):
        plan = RouterPlan(steps=[
            RouteStep(step_id="v", route="vector", confidence=0.85),
            RouteStep(step_id="g", route="graph", confidence=0.5),    # 辅助：定位规范节点
        ])
        return RouteDecision("concept", plan, 0.85)
    # 无命中：置信度低 → 三路全跑，assemble 去重兜底（§7.3）
    plan = RouterPlan(steps=[
        RouteStep(step_id="g", route="graph", confidence=0.3),
        RouteStep(step_id="t", route="text2sql", confidence=0.3),
        RouteStep(step_id="v", route="vector", confidence=0.3),
    ], fallback=True)
    return RouteDecision("unknown", plan, 0.3)


def llm_route(question: str, chat_json) -> RouteDecision:
    """LLM 版（有 key 时用）：同规则版的决策结构，意图与置信度由模型给。"""
    payload = chat_json(
        "你是检索路由器。只输出 JSON：{\"intent\": one of "
        "[graph,fact,concept,attribution,operation,unknown], \"confidence\": 0-1}。",
        question)
    intent = payload.get("intent", "unknown")
    conf = float(payload.get("confidence", 0.3))
    if intent == "operation":
        return RouteDecision("operation", None, conf)
    base = rule_route(_HINTS[intent] if intent in _HINTS else question)
    if base.intent == intent:
        return RouteDecision(intent, base.plan, conf)
    return RouteDecision(intent, rule_route("今天天气").plan, conf)   # 结构降级到全跑


_HINTS = {"graph": "谁 名下 案例", "fact": "多少 消耗",
          "concept": "规范 要求", "attribution": "为什么 规范 关系"}
