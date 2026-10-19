"""router（§7.3）：意图识别 → RouterPlan（steps 带依赖与置信度）。

规则版是 §7.2 降级矩阵的兜底实现（意图关键词模板）；LLM 版接口同名同返回
（chat_json 注入，有 key 时由 API 层优先使用）。RouterPlan 是 models 一等类型，
ask 只解释执行——路由评测直接对 plan 断言（§7.3）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from adkg.models import RouteStep, RouterPlan

_OPS = ("删除", "删掉", "暂停", "停掉", "下掉", "改回", "改成", "迁移")
_FACT = ("多少", "消耗", "cpa", "ctr", "cvr", "roi", "最差", "最好", "排名",
         "成本", "转化", "趋势", "均值")
_GRAPH = ("谁", "哪些案例", "哪些品牌", "名下", "负责", "对接", "关系链", "多少个")
_CONCEPT = ("规范", "要求", "时长", "规定", "vi", "广告法", "尺寸", "口径")
_ATTR = ("有没有关系", "为什么", "归因", "原因", "和.*规范")


@dataclass(frozen=True)
class RouteDecision:
    intent: str                    # graph | fact | concept | attribution | operation | unknown
    plan: RouterPlan | None        # operation → None（API 层返回端点指引，§7.3）
    confidence: float


def _hits(q: str, kws: tuple[str, ...]) -> int:
    return sum(1 for k in kws if k in q or re.search(k, q))


def _plan_for(intent: str) -> RouterPlan:
    """意图 → 计划（§7.3 表）；LLM 与规则路由共用同一映射，杜绝两套口径。"""
    if intent == "attribution":
        return RouterPlan(steps=[
            RouteStep(step_id="g", route="graph", confidence=0.85),
            RouteStep(step_id="t", route="text2sql", depends_on=["g"],
                      confidence=0.85, params={"entity_ids_from": "g"}),
            RouteStep(step_id="v", route="vector", depends_on=["t"], confidence=0.8),
        ])
    if intent == "fact":
        return RouterPlan(steps=[RouteStep(step_id="t", route="text2sql", confidence=0.9)])
    if intent == "graph":
        return RouterPlan(steps=[
            RouteStep(step_id="g", route="graph", confidence=0.85),
            RouteStep(step_id="v", route="vector", confidence=0.6),
        ])
    if intent == "concept":
        return RouterPlan(steps=[
            RouteStep(step_id="v", route="vector", confidence=0.85),
            RouteStep(step_id="g", route="graph", confidence=0.5),
        ])
    return RouterPlan(steps=[                                  # unknown：三路全跑兜底
        RouteStep(step_id="g", route="graph", confidence=0.3),
        RouteStep(step_id="t", route="text2sql", confidence=0.3),
        RouteStep(step_id="v", route="vector", confidence=0.3),
    ], fallback=True)


def rule_route(question: str) -> RouteDecision:
    q = question.lower()
    if _hits(q, _OPS):
        return RouteDecision("operation", None, 0.95)
    if _hits(q, _ATTR) and (_hits(q, _FACT) or _hits(q, _CONCEPT)):
        return RouteDecision("attribution", _plan_for("attribution"), 0.85)
    if _hits(q, _FACT):
        return RouteDecision("fact", _plan_for("fact"), 0.9)
    if _hits(q, _GRAPH):
        return RouteDecision("graph", _plan_for("graph"), 0.85)
    if _hits(q, _CONCEPT):
        return RouteDecision("concept", _plan_for("concept"), 0.85)
    return RouteDecision("unknown", _plan_for("unknown"), 0.3)


_LLM_PROMPT = (
    "你是知识中台的检索路由器。只输出 JSON：{\"intent\": ..., \"confidence\": 0-1}。"
    "intent 六选一，判定标准：\n"
    "- fact：答案是需要查数值/报表的问题（多少钱、最差最好、排名、趋势、CPA/CTR）\n"
    "- graph：答案是跨实体的关系链（谁负责什么、哪些案例、属于哪个品牌、违反了什么）\n"
    "- concept：答案是文档规范/规定的原文（时长要求、VI 规定、广告法条款）\n"
    "- attribution：既要查数又要关联规范/关系做归因（效果差和规范有没有关系、为什么）\n"
    "- operation：要执行动作（删除/暂停/改状态）\n"
    "- unknown：以上都不像\n"
    "示例：“上月 CPA 最差的素材”→fact；“李昂名下有哪些案例”→graph；"
    "“视频时长规范是什么”→concept；“效果差的素材和规范有关系吗”→attribution；"
    "“删掉这个素材”→operation"
)


def llm_route(question: str, chat_json) -> RouteDecision:
    """LLM 版（有 key 时用）：意图由模型判，计划与规则版共用 _plan_for——同一口径。"""
    payload = chat_json(_LLM_PROMPT, question)
    intent = payload.get("intent", "unknown")
    conf = float(payload.get("confidence", 0.3))
    if intent == "operation":
        return RouteDecision("operation", None, conf)
    return RouteDecision(intent, _plan_for(intent), conf)
