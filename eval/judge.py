"""LLM judge（§11.3）：按要点打分——正确 = 要点命中 + 数字一致 + 引用可溯源。

走 batch 通道（glm-4-flash）；调用失败返回 None，评测层回退规则判据（§7.2）。
"""
from __future__ import annotations

import json

JUDGE_PROMPT = (
    "你是评测裁判。给你【问题】【期望要点】【检索证据】，判断每个要点是否被证据"
    "支撑（证据须含可溯源信息：关系边/事实行/文档引用）。只输出 JSON："
    '{"points_hit": ["命中的要点", ...], "verdict": true/false, "reason": "一句话"}。'
    "注意：证据里没有的信息判未命中；数字要与证据一致；不要脑补。"
)


def judge_item(chat_json, question: str, points: list[str],
               evidence: list[dict]) -> dict | None:
    if not points:
        return None
    trimmed = [{k: (v[:3] if isinstance(v, list) else v) for k, v in ev.items()}
               for ev in evidence[:8]]
    try:
        payload = chat_json(
            JUDGE_PROMPT,
            json.dumps({"问题": question, "期望要点": points, "检索证据": trimmed},
                       ensure_ascii=False, default=str))
    except Exception:                                   # 通道/解析失败 → 回退规则判据（§7.2）
        return None
    if not isinstance(payload, dict) or "verdict" not in payload:
        return None
    return {"verdict": bool(payload.get("verdict")),
            "points_hit": payload.get("points_hit", []),
            "reason": str(payload.get("reason", ""))[:200]}
