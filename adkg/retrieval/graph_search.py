"""graph 路（§7.3）：实体定位 → 1–2 跳邻域 → PermissionPlan 可见集过滤。

只消费 plan、不读权限矩阵（翻译收口在 permission.py）。
返回 evidence（关系带 provenance）+ 命中实体 ID 集（归因串行时作
text2sql 步的条件，§7.3 串行依赖）。
"""
from __future__ import annotations

import re

_ID_PATTERN = re.compile(r"[A-Za-z]+:[A-Za-z0-9_\-]+")        # {class}:{slug} 完整形态
_SLUG_PATTERN = re.compile(
    r"[Gg]-\d{2}|creative_\w+|[A-Za-z]+_\d+\w*"               # 规范 slug / 平台素材号
    r"|C-\d{4}-\d{3}(?:-cp\d)?(?:-cr\d)?")                    # 案例-计划-素材短链（案例号本体的 slug 段）


def search(question: str, plan, graph, *, limit: int = 50, person: str | None = None) -> dict:
    if getattr(plan, "deny_all", False):
        return {"evidence": [], "entity_ids": [], "filtered": 0}   # fail-closed（§12.4）
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
        if not ids and person and any(w in question for w in ("我", "咱", "本人", "自己")):
            # "我的品牌/我们的案例"——锚点即本人（§9.1）。仅限第一人称指代：无锚点的
            # 全局问题（G14"效果差的素材和规范有关系吗"）曾被静默圈到提问者本人，
            # 归因串行把 CPA 榜也收窄成其品牌子集（entity_ids_from: g），全图最差
            # 素材（带 violates 边）进不了证据——检索启发式不是权限边界，权限仍由
            # PermissionPlan 的 visible/谓词保证
            ids.add(person)
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
        # 三跳定向：品牌/案例/计划 → targets → 人群包（§六 targets N:M）——
        # "定向了哪些人群"类问题的直达链路；可见性过滤与一跳同闸（client 看不到
        # 其可见案例之外品牌的人群包，fail-closed）
        if "人群" in question or "定向" in question or "Audience" in allowed_classes:
            for r3 in s.run(
                """
                UNWIND $ids AS eid
                MATCH (a:Entity {id: eid})
                CALL (a) {
                    MATCH (a)<-[:for_brand]-(:Entity {class:'Case'})
                          <-[:belongs_to]-(:Entity {class:'Campaign'})
                          -[:targets]->(b:Entity {class:'Audience'})
                    RETURN b, 'brand' AS via
                    UNION
                    MATCH (a)<-[:belongs_to]-(:Entity {class:'Campaign'})
                          -[:targets]->(b:Entity {class:'Audience'})
                    RETURN b, 'case' AS via
                    UNION
                    MATCH (a)-[:belongs_to]->(:Entity {class:'Campaign'})
                          -[:targets]->(b:Entity {class:'Audience'})
                    RETURN b, 'campaign' AS via
                }
                RETURN a.id AS src, b.id AS dst, via,
                       b.prov_source AS psrc, b.prov_source_id AS psid,
                       b.authority AS auth LIMIT $limit
                """, ids=list(ids), limit=limit).data():
                via_ref = {
                    "brand": "({src})<-[:for_brand]-(:Case)<-[:belongs_to]-(:Campaign)-[:targets]->({dst})",
                    "case": "({src})<-[:belongs_to]-(:Campaign)-[:targets]->({dst})",
                    "campaign": "({src})-[:belongs_to]->(:Campaign)-[:targets]->({dst})",
                }[r3["via"]]
                rows.append({"src": r3["src"],
                             "ref": via_ref.format(src=r3["src"], dst=r3["dst"]),
                             "conf": None, "psrc": r3["psrc"], "psid": r3["psid"],
                             "auth": r3["auth"], "dst": r3["dst"]})
        # 命中实体自身属性作证据项（属性型问题如 target_age 由此可答）；
        # 属性黑名单 deny_properties 在此唯一执行（§7.3 权限下推）
        prop_rows = s.run(
            "UNWIND $ids AS eid MATCH (n:Entity {id: eid})"
            " RETURN n.id AS id, n.class AS cls, n.prov_source AS psrc,"
            " n.prov_source_id AS psid, n.authority AS auth, properties(n) AS props",
            ids=sorted(ids)).data()

    global_classes = plan.global_classes             # schema 驱动（§12.4，models 单一来源）
    evidence, kept_ids, filtered = [], set(ids), 0
    # entity 证据项：可见集 + 属性白名单（外部，fail-closed）/ 黑名单（内部）双过滤
    # （prov_* 与 authority 是溯源不是业务属性；§12.6 人名对外掩码在此兜底；
    #   属性出口过滤收口 plan.project——2026-10-28 与 CRUD 端点同一实现）
    for pr in prop_rows:
        cls = pr["cls"] or pr["id"].split(":")[0]
        allowed_classes = plan.metadata_filter.get("entity_class__in", [])
        if allowed_classes and cls not in allowed_classes and cls not in global_classes:
            continue                                     # 类白名单：属性证据不越类（§12.4）
        if visible and pr["id"] not in visible and cls not in global_classes:
            continue
        props = plan.project({k: v for k, v in (pr["props"] or {}).items()
                              if not k.startswith("prov_")
                              and k not in ("id", "class", "authority")}, cls)
        if "person_name" in plan.mask_rules and cls == "Person" and "name" in props:
            props["name"] = "＊＊"
        evidence.append({
            "type": "entity",
            "ref": pr["id"],
            "props": props,
            "provenance": {"source_type": pr["psrc"], "source_id": pr["psid"],
                           "authority": pr["auth"]},
        })
    for r in rows:
        ref = r.get("ref") or f"({r['src']})-[:{r['rel']}]->({r['dst']})"
        ends = {r["src"], r["dst"]}
        end_classes = {e.split(":")[0] for e in ends}
        if visible and not (ends & visible) and not end_classes <= global_classes:
            filtered += 1                                # 级联收窄的出口执行点（全局类
            continue                                     # 豁免仅限两端皆全局类，防越权边经
                                                           # Guideline/Metric 泄漏存在性）
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
