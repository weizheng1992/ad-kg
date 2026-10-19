"""graph 路（§7.3）：实体定位 → 邻域展开 → PermissionPlan 可见集过滤。

只消费 plan、不读权限矩阵（翻译收口在 permission.py）。
返回 evidence 列表（关系带 provenance）+ 命中的实体 ID 集（归因串行时
作 text2sql 步的条件，§7.3 串行依赖）。
"""
from __future__ import annotations

import re

_ID_PATTERNS = [re.compile(r"[A-Za-z]+:[A-Za-z0-9_\-]+")]     # {class}:{slug} 形态


def search(question: str, plan, graph, *, hops: int = 1, limit: int = 50) -> dict:
    with graph.session() as s:
        # 实体定位：问题里出现完整本体 ID，或包含节点 name
        ids = set()
        for pat in _ID_PATTERNS:
            ids |= set(pat.findall(question))
        named = s.run(
            "MATCH (n:Entity) WHERE n.name IS NOT NULL AND $q CONTAINS n.name"
            " RETURN n.id AS id", q=question).data()
        ids |= {r["id"] for r in named}
        if not ids:
            return {"evidence": [], "entity_ids": [], "filtered": 0}

        allowed_classes = set(plan.metadata_filter.get("entity_class__in", []))
        visible = plan.visible_entity_ids               # 空 = 不约束（无 row_filter 角色）
        rows = s.run(
            """
            UNWIND $ids AS eid
            MATCH (a:Entity {id: eid})-[r]-(b:Entity)
            WHERE (a.class IN $classes OR b.class IN $classes)
            RETURN a.id AS src, type(r) AS rel, b.id AS dst,
                   r.confidence AS conf, r.prov_source AS psrc,
                   r.prov_source_id AS psid, r.authority AS auth
            LIMIT $limit
            """, ids=list(ids), classes=sorted(allowed_classes), limit=limit * 2).data()

    global_classes = {"Metric", "Guideline", "Channel"}
    evidence, kept_ids, filtered = [], set(ids), 0
    for r in rows:
        ends = {r["src"], r["dst"]}
        if visible and not (ends & visible) and not any(
                e.split(":")[0] in global_classes for e in ends):
            filtered += 1                                # 级联收窄的出口执行点
            continue
        evidence.append({
            "type": "relation",
            "ref": f"({r['src']})-[:{r['rel']}]->({r['dst']})",
            "confidence": r["conf"],
            "provenance": {"source_type": r["psrc"], "source_id": r["psid"],
                           "authority": r["auth"]},
        })
        kept_ids |= ends
    entity_ids = sorted(kept_ids & visible) if visible else sorted(kept_ids)
    return {"evidence": evidence[:limit], "entity_ids": entity_ids, "filtered": filtered}
