"""评测骨架（README §7.1 Phase 1）：读 golden_set 并报告分布。

跑分逻辑（三路 vs 双路 / 双路+Text2SQL 消融，fact / multi_hop / concept 三子集）
在 Phase 4/6 接入——本骨架先锁两件事：
1. golden_set 存在且格式可解析（§12.3 的字段）
2. 五类分布可随时报告（Phase 0 列题时当场核对）
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "golden_set.jsonl"
REQUIRED_TYPES = {"multi_hop", "fact", "concept", "attribution", "operation"}


def load() -> list[dict]:
    if not GOLDEN.exists():
        sys.exit("eval/golden_set.jsonl 不存在——先落 Phase 0 的 20 题骨架")
    rows = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    bad = [r.get("id") for r in rows
           if not {"id", "type", "question", "expected_routes"} <= set(r)]
    if bad:
        sys.exit(f"缺 §12.3 必填字段的题：{bad}")
    unknown = {r["type"] for r in rows} - REQUIRED_TYPES
    if unknown:
        sys.exit(f"未知题型 {unknown}，合法值：{sorted(REQUIRED_TYPES)}")
    return rows


if __name__ == "__main__":
    rows = load()
    dist = Counter(r["type"] for r in rows)
    print(f"golden_set 共 {len(rows)} 题，分布：")
    for t in sorted(REQUIRED_TYPES):
        print(f"  {t:<12} {dist.get(t, 0)}")
    windows = sorted({r.get("data_window", "?") for r in rows})
    print(f"数据窗口：{windows}")
