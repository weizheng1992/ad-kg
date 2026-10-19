"""实体对齐消歧（§7.4 四级漏斗，Phase 2a 实现前两级）。

L1 规则归一：名称清洗（全半角 / 大小写 / 常见装饰前后缀）+ entity_alias 直接命中；
L2 相似候选：嵌入 top-k，阈值 τ 随嵌入模型在 seed 上标定（初值 0.75）。
LLM 判别（L3）与人审（L4）在 Phase 2b。
"""
from __future__ import annotations

import math
import re
import unicodedata

_DECORATIONS = re.compile(r"^[【\[（(·\s]+|[】\]）)·\s]+$")
_DECOR_TOKENS = ("【官】", "【官方】", "（官）", "官_", "官方:")

# 全角→半角 + 大小写归一 + 去装饰前后缀
def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKC", name).strip().casefold()
    for token in _DECOR_TOKENS:
        s = s.removeprefix(token)
    return _DECORATIONS.sub("", s)


def resolve_by_alias(source: str, external_id: str,
                     aliases: dict[tuple[str, str], str]) -> str | None:
    """L1：entity_alias 命中即接受（§7.4 表）。"""
    return aliases.get((source, external_id))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-12
    nb = math.sqrt(sum(y * y for y in b)) or 1e-12
    return dot / (na * nb)


def similar_candidates(name: str, known: dict[str, str], embed, *,
                       top_k: int = 5, threshold: float = 0.75) -> list[tuple[str, float]]:
    """L2：与已知实体名算相似度，≥τ 的进 L3/LLM 判别；不足则空（不硬配）。"""
    if not known:
        return []
    known_ids = list(known)
    vectors = embed([name] + [known[i] for i in known_ids])
    scored = [(known_ids[i], _cosine(vectors[0], vectors[i + 1]))
              for i in range(len(known_ids))]
    scored = [(i, s) for i, s in scored if s >= threshold]
    return sorted(scored, key=lambda t: -t[1])[:top_k]
