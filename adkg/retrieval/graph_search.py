"""graph 路（§7.3）：实体定位 → 1–2 跳邻域 → PermissionPlan 可见集过滤。

只消费 plan、不读权限矩阵（翻译收口在 permission.py）。
返回 evidence（关系带 provenance）+ 命中实体 ID 集（归因串行时作
text2sql 步的条件，§7.3 串行依赖）。
"""
from __future__ import annotations

import re

_ID_PATTERN = re.compile(r"[A-Za-z]+:[A-Za-z0-9_\-]+")        # {class}:{slug} 完整形态
_SLUG_PATTERN = re.compile(r"[Gg]-\d{2}|creative_\w+|[A-Za-z]+_\d+\w*")  # 裸 slug


def search(question: str, plan, graph, *, limit: int = 50) -> dict:
    with graph.session() as s:
        # 实体定位：① 完整本体 ID ② 节点 name ③ 裸 slug 后缀匹配
        ids = set(_ID_PATTERN.findall(question))
        ids |= {r["id"] for r in s.run(
            "MATCH (n:Entity) WHERE n.name IS NOT NULL AND $q CONTAINS n.name"
            " RETURN n.id AS id", q=question).data()}
        for token in _SLUG_PATTERN.findall(question)[:4]:
            ids |= {r["id"] for r in s.run(
                "MATCH (n:Entity) WHERE n.id ENDS WITH $suffix RETURN n.id AS id LIMIT 5",
                suffix=f":{token}").data()}
        if not ids:
            return {"evidence": [], "entity_ids": [], "filtered": 0}

        allowed_classes = set(plan.metadata_filter.get("entity_class__in", []))
        visible = plan.visible_entity_ids               # 空 = 不约束（无 row_filter 角色）
        # 一跳：任一端在类白名单
        rows = s.run(
            """
            UNWIND $ids AS eid
            MATCH (a:Entity {id: eid})-[r]-(b:Entity)
            WHERE a.class IN $classes OR b.class IN $classes
            RETURN a.id AS src, type(r) AS rel, b.id AS dst,
                   r.confidence AS conf, r.prov_source AS psrc,
                   r.prov_source_id AS psid, r.authority AS auth
            LIMIT $limit
            """, ids=list(ids), classes=sorted(allowed_classes), limit=limit).data()
        # 两跳补：锚点与中间点都不在白名单、终点在（如 client: Person→Brand→Case）
        if not rows:
            for r2row in s.run(
                """
                UNWIND $ids AS eid
                MATCH (a:Entity {id: eid})-[r1]-(m:Entity)-[r2]-(b:Entity)
                WHERE NOT (a.class IN $classes OR m.class IN $classes)
                  AND b.class IN $classes
                RETURN a.id AS src, m.id AS mid, type(r1) AS rel1,
                       type(r2) AS rel2, b.id AS dst,
                       r2.confidence AS conf, r2.prov_source AS psrc,
                       r2.prov_source_id AS psid, r2.authority AS auth
                LIMIT $limit
                """, ids=list(ids), classes=sorted(allowed_classes), limit=limit).data():
                rows.append({"src": r2row["src"],
                             "ref": (f"({r2row['src']})-[:{r2row['rel1']}]->({r2row['mid']})"
                                     f"-[:{r2row['rel2']}]->({r2row['dst']})"),
                             "conf": r2row["conf"], "psrc": r2row["psrc"],
                             "psid": r2row["psid"], "auth": r2row["auth"],
                             "dst": r2row["dst"]})

    global_classes = {"Metric", "Guideline", "Channel"}
    evidence, kept_ids, filtered = [], set(ids), 0
    for r in rows:
        ref = r.get("ref") or f"({r['src']})-[:{r['rel']}]->({r['dst']})"
        ends = {r["src"], r["dst"]}
        if visible and not (ends & visible) and not any(
                e.split(":")[0] in global_classes for e in ends):
            filtered += 1                                # 级联收窄的出口执行点
            continue
        evidence.append({
            "type": "relation",
            "ref": ref,
            "confidence": r["conf"],
            "provenance": {"source_type": r["psrc"], "source_id": r["psid"],
                           "authority": r["auth"]},
        })
        kept_ids |= ends
    entity_ids = sorted(kept_ids & visible) if visible else sorted(kept_ids)
    return {"evidence": evidence[:limit], "entity_ids": entity_ids, "filtered": filtered}
