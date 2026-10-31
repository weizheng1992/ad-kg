"""评测判据单一来源（2026-10-31 夜检：num_ok 曾双源且已分叉——agent 侧剥千分位/
懂 % 语义，golden 侧不懂；分叉即口径漂移实证）。golden（run_eval）与 agent
（agent_eval）两评测面的数值容差共用本模块，改口径只动一处。"""
from __future__ import annotations

import re

TOL_ABS = 0.06                # 容差 ±max(0.06, 1%)——四舍五入/整数化形态不误杀


def num_ok(texts: str | list[str], must_numbers: list) -> bool:
    """数值硬断言：每个期望数字在任一文本里数值可达。容差 ±max(0.06, 1%)；
    先剥千分位逗号（1,001,609.41 会被劈成三个 token）；百分号标注的数按 /100
    候选参与匹配（"CTR 1.64%" 语义 = 0.0164——精确限定 % 后缀，不撒网）。"""
    if not must_numbers:
        return True
    if isinstance(texts, str):
        texts = [texts]
    for n in must_numbers:
        target = float(n)
        tol = max(TOL_ABS, abs(target) * 0.01)
        if not any(_hit(t, target, tol) for t in texts):
            return False
    return True


_NUM_RE = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"


def _hit(text: str, target: float, tol: float) -> bool:
    """数字提取两难：千分位 1,001,609.41 要整体读、分句逗号 6297，2026 要分开
    读（整串剥逗号曾把相邻两数粘成巨数 62972026——2026-10-31 A29 实弹）。正则
    按「3 位分组优先」消歧：半角逗号只在合法千分位组里被消费；全角逗号（中文
    分句符）从不剥。百分号标注的数按 /100 候选参与匹配（精确限定 % 后缀）。"""
    found = [float(x.replace(",", "")) for x in re.findall(_NUM_RE, text)]
    found += [float(x.replace(",", "")) / 100 for x in
              re.findall(f"({_NUM_RE})\\s*[%％]", text)]
    return any(abs(f - target) <= tol for f in found)
