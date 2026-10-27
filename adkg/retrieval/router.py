"""router（§7.3）：意图识别 → RouterPlan（steps 带依赖与置信度）。

规则版是 §7.2 降级矩阵的兜底实现（意图关键词模板）；LLM 版接口同名同返回
（chat_json 注入，有 key 时由 API 层优先使用）。RouterPlan 是 models 一等类型，
ask 只解释执行——路由评测直接对 plan 断言（§7.3）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from adkg.models import RouteStep, RouterPlan
from adkg.retrieval.metrics import RANK_WORDS

_OPS = ("删除", "删掉", "暂停", "停掉", "下掉", "改回", "改成", "迁移",
        "停投", "关停", "关掉", "下线",
        # 预算操作族（2026-10-27 拍板：显式 deny——AdKG 是决策点不是执行点，
        # 预算调整请走投放平台；只收动宾复合词，裸"预算"是名词留检索路）
        "加预算", "调预算", "提预算", "减预算", "砍预算", "预算调")
# 操作词多为动宾两用（"关停的案例列表"是状态查询不是操作）——有检索标记即降检索路；
# 名词性标记（列表/清单/看看/查一下…）与被动/疑问标记同权重；不含"帮我/给我"
# （"帮我删掉"仍是祈使操作）
_RETRIEVAL_MARK = ("哪些", "谁", "多少", "吗", "被", "已", "怎么样", "状态",
                   "列表", "清单", "看看", "查一下", "查查", "拉一下", "导出", "明细")
# 排名词族（最X/排名）来自 metrics.RANK_WORDS 单一来源——text2sql 方向判定同源，
# 加词两端自动跟随（2026-10-24 收敛：曾三份拷贝漂移）
_FACT = ("多少", "消耗", "cpa", "ctr", "cvr", "roi") + RANK_WORDS + \
        ("成本", "转化", "趋势", "均值", "花钱", "烧钱", "销量", "订单", "成交",
         "gmv", "点击(?!率)", "曝光", "展现", "跑量", "爆量", "起量")   # 点击负向预见：点击率≠点击量
_GRAPH = ("谁", "哪些案例", "哪些品牌", "名下", "负责", "对接", "关系链", "多少个",
          "目标人群", "年龄段", "人群画像", "定向人群")   # 实体属性型问题走属性证据（§7.3）
_CONCEPT = ("规范", "要求", "时长", "规定", "vi", "广告法", "尺寸", "口径")
# 口径/定义类短语：问的是"这个词什么意思"而非数值——命中 _FACT 前先归 concept；
# 但带强聚合/方向词（"按新口径 CPA 最差"）仍是查数题，不得劫持；
# 定义尾（"排名是什么意思"）在场时主语词不算查数信号
_DEF = ("什么意思", "定义", "口径", "怎么算", "如何计算", "计算口径")
_DEF_EXCLUDE = RANK_WORDS + ("多少", "top", "趋势", "合计", "总共", "汇总")
_DEF_TAIL = ("什么意思", "怎么算", "怎么界定", "如何计算", "如何界定",
             "定义是什么", "口径是什么", "的定义", "的口径")
# 概念救实的硬聚合信号：规范词与指标词同现时，有这些才让位给 fact。
# 定语型指标词（跑量素材/爆量视频/花钱最多的素材）不作硬信号——选实体不是查数；
# 多少/最X 亦不拦（"logo 最小尺寸是多少"是概念题）——刻意不是 metrics.RANK_WORDS
# 全集：HIGH/LOW_WORDS 属定语型（尺寸/量级），只有好坏向（最差/最好）+排名算硬信号
_NUMSIG_HARD = ("排名", "最差", "最好", "消耗", "成本", "花费",
                "cpa", "ctr", "cvr", "roi", "趋势", "均值")
_ATTR = ("有没有关系", "为什么", "归因", "原因", "和.*规范", "违反")
# 违反 = 归因语义（查数 + 关联规范，§7.3 串行 g→t→v）：G15 "CPA 最差的素材违反了
# 哪些规范"曾落 fact 单路，violates 边永远进不了证据


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
    if _hits(q, _OPS) and not any(m in q for m in _RETRIEVAL_MARK) \
            and not _hits(q, _DEF_TAIL):
        # 定义尾在场永不判操作（"暂停是什么意思"是概念题，§7.3）
        return RouteDecision("operation", None, 0.95)
    if _hits(q, _ATTR) and (_hits(q, _FACT) or _hits(q, _CONCEPT)):
        return RouteDecision("attribution", _plan_for("attribution"), 0.85)
    if _hits(q, _DEF) and (_hits(q, _FACT) or _hits(q, _CONCEPT)) \
            and (not _hits(q, _DEF_EXCLUDE) or _hits(q, _DEF_TAIL)):
        return RouteDecision("concept", _plan_for("concept"), 0.85)
    if _hits(q, _CONCEPT) and _hits(q, _FACT) and not _hits(q, _NUMSIG_HARD):
        # 概念救实："logo 最小尺寸规范""跑量素材的时长要求"——规范词在场且无硬聚合信号
        return RouteDecision("concept", _plan_for("concept"), 0.85)
    if _hits(q, _FACT):
        # 锚词让贤（§7.3）：图锚词与指标词同现（"李昂名下消耗最高"）降置信交 LLM 裁决，
        # 杜绝人名/品牌锚点被 fact 单路静默丢弃
        conf = 0.75 if _hits(q, ("名下", "负责", "对接")) else 0.9
        return RouteDecision("fact", _plan_for("fact"), conf)
    if _hits(q, _GRAPH):
        return RouteDecision("graph", _plan_for("graph"), 0.85)
    if _hits(q, _CONCEPT):
        return RouteDecision("concept", _plan_for("concept"), 0.85)
    return RouteDecision("unknown", _plan_for("unknown"), 0.3)


_LLM_PROMPT = (
    "你是知识中台的检索路由器。只输出 JSON：{\"intent\": ..., \"confidence\": 0-1}。"
    "intent 六选一，判定标准：\n"
    "- fact：答案是需要查数值/报表的问题（多少钱、最差最好、排名、趋势、CPA/CTR）\n"
    "- graph：答案是跨实体的关系链或实体自身属性（谁负责什么、哪些案例、属于哪个品牌、违反了什么、预算/状态/目标人群年龄段等属性值）\n"
    "- concept：答案是文档规范/规定的原文（时长要求、VI 规定、广告法条款）\n"
    "- attribution：既要查数又要关联规范/关系做归因（效果差和规范有没有关系、为什么）\n"
    "- operation：要执行动作（删除/暂停/改状态）\n"
    "- unknown：以上都不像\n"
    "示例：“上月 CPA 最差的素材”→fact；“李昂名下有哪些案例”→graph；"
    "“轻食日记App 的目标人群是什么年龄段”→graph；"
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
