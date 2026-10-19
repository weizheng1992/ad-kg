"""assemble（§7.3 融合与排序 / §7.2 降级标注 / §12.6 脱敏出口）。

- evidence 按去重键合并（ref），路内顺序保留——RRF 简化为保序去重（v1）
- routes_used 各项带得分（评测可归因到路）
- degraded 列出缺席路；permission_applied 汇总召回层被滤条数
- mask_rules 含 person_name 时对文本做人名掩码（§12.6，实现留代码层的口子）
"""
from __future__ import annotations


def assemble(route_results: dict, plan, decision, *, person_names: list[str] | None = None) -> dict:
    evidence, seen = [], set()
    routes_used, degraded = [], []
    filtered_total = 0
    for step_id, result in route_results.items():
        route, score = result["route"], result.get("confidence", 0.5)
        routes_used.append({"route": route, "score": score})
        if result.get("degraded"):
            degraded.append(route)
            continue
        filtered_total += result.get("filtered", 0)
        for ev in result.get("evidence", []):
            key = ev.get("ref") or str(ev)[:80]
            if key in seen:
                continue
            seen.add(key)
            evidence.append(ev)

    if plan.mask_rules and "person_name" in plan.mask_rules and person_names:
        for ev in evidence:                                # 脱敏出口（§12.6）
            for field in ("ref", "quote"):
                if field in ev and isinstance(ev[field], str):
                    for name in person_names:
                        ev[field] = ev[field].replace(name, "＊＊")

    return {
        "intent": decision.intent,
        "evidence": evidence,
        "routes_used": routes_used,
        "permission_applied": filtered_total > 0,
        "degraded": degraded,
    }
