"""图层适配器（§八）：节点与关系的 MERGE 写入——双写一致性的 Neo4j 侧。

一律 MERGE（幂等键 = 实体 id / 关系端点+谓词，§八）；provenance 内联在节点与关系上，
对账时按 provenance 计数与 Postgres 比对。
"""
from __future__ import annotations

from contextlib import contextmanager

from neo4j import GraphDatabase

from adkg.models import Entity, Relation


class GraphStore:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    @contextmanager
    def session(self):
        with self._driver.session() as s:
            yield s

    def close(self) -> None:
        self._driver.close()

    def authority_of(self, eid: str) -> int | None:
        """既有实体 authority（备忘⑯仲裁单源：case_gen 物化路与抽取写图共用）。"""
        with self.session() as s:
            row = s.run("MATCH (n:Entity {id: $id}) RETURN n.authority AS auth LIMIT 1",
                        id=eid).single()
            return row["auth"] if row else None

    def edge_authority(self, pred: str, src: str, dst: str) -> int | None:
        """既有同边 authority（关系级仲裁同上）。"""
        with self.session() as s:
            row = s.run(f"MATCH (a:Entity {{id: $s}})-[r:{pred}]->(b:Entity {{id: $o}})"
                        " RETURN r.authority AS auth LIMIT 1", s=src, o=dst).single()
            return row["auth"] if row else None

    def upsert_entities(self, entities: list[Entity]) -> None:
        with self.session() as s:
            for e in entities:
                s.run(
                    """
                    MERGE (n:Entity {id: $id})
                    SET n.class = $cls, n += $props,
                        n.prov_source = $src, n.prov_source_id = $sid,
                        n.prov_fetched_at = toString($at), n.authority = $auth
                    """,
                    id=e.entity_id, cls=e.entity_class, props=e.props,
                    src=e.provenance.source_type.value, sid=e.provenance.source_id,
                    at=e.provenance.fetched_at, auth=e.provenance.authority)

    def upsert_relations(self, relations: list[Relation]) -> None:
        with self.session() as s:
            for r in relations:
                s.run(
                    f"""
                    MATCH (a:Entity {{id: $src}}), (b:Entity {{id: $dst}})
                    MERGE (a)-[rel:{r.predicate}]->(b)
                    SET rel.confidence = $conf, rel.prov_source = $ps,
                        rel.prov_source_id = $psid, rel.authority = $auth
                    """,
                    src=r.source, dst=r.target, conf=r.confidence,
                    ps=r.provenance.source_type.value, psid=r.provenance.source_id,
                    auth=r.provenance.authority)

    def counts(self) -> dict[str, int]:
        """对账用（§八）：带 provenance 的节点 / 关系数。"""
        with self.session() as s:
            nodes = s.run("MATCH (n:Entity) WHERE n.prov_source IS NOT NULL "
                          "RETURN count(n) AS c").single()["c"]
            rels = s.run("MATCH ()-[r]->() WHERE r.prov_source IS NOT NULL "
                         "RETURN count(r) AS c").single()["c"]
        return {"nodes": nodes, "relations": rels}

    def creative_contexts(self, creative_ids: list[str]) -> dict[str, dict]:
        """etl_facts 物化维度列用（§八）：素材 → 所属计划/案例/品牌/商品。"""
        if not creative_ids:
            return {}
        with self.session() as s:
            rows = s.run(
                """
                UNWIND $ids AS cid
                OPTIONAL MATCH (c:Entity {id: cid})<-[:uses]-(cp:Entity)
                    -[:belongs_to]->(cs:Entity)
                OPTIONAL MATCH (cs)-[:for_brand]->(b:Entity)
                OPTIONAL MATCH (cs)-[:for_product]->(p:Entity)
                RETURN cid, head(collect(DISTINCT cp.id)) AS campaign_id,
                       head(collect(DISTINCT cs.id)) AS case_id,
                       head(collect(DISTINCT b.id))  AS brand_id,
                       head(collect(DISTINCT p.id))  AS product_id
                """, ids=creative_ids)
            return {r["cid"]: {"campaign_id": r["campaign_id"], "case_id": r["case_id"],
                               "brand_id": r["brand_id"],
                               "product_id": r["product_id"]} for r in rows}

    def creative_case_stage(self, creative_id: str) -> str | None:
        """action_check 用（§六）：素材 → 所属案例的 stage。"""
        with self.session() as s:
            rec = s.run(
                "MATCH (c:Entity {id: $cid})<-[:uses]-(cp:Entity)"
                "-[:belongs_to]->(cs:Entity) RETURN cs.stage AS stage LIMIT 1",
                cid=creative_id).single()
            return rec["stage"] if rec else None

    def guidelines_with_thresholds(self) -> list[dict]:
        """guideline/check 机判用：带结构化阈值的规范节点。"""
        with self.session() as s:
            return s.run(
                "MATCH (g:Entity) WHERE g.class='Guideline'"
                " RETURN g.id AS id, g.guideline_type AS gtype,"
                " g.max_duration_s AS max_duration_s").data()

    def responsible_for_creatives(self, creative_ids: list[str]) -> list[dict]:
        """事实行→图补 join（§7.3 归因串行的通用化）：素材 → 计划 → 案例 → 负责人。"""
        if not creative_ids:
            return []
        with self.session() as s:
            return s.run(
                """
                UNWIND $ids AS cid
                MATCH (c:Entity {id: cid})<-[:uses]-(cp:Entity)
                      -[:belongs_to]->(cs:Entity)<-[:responsible_for]-(p:Entity)
                RETURN cid, head(collect(DISTINCT cp.id)) AS campaign,
                       head(collect(DISTINCT cs.id)) AS case,
                       head(collect(DISTINCT p.id)) AS person,
                       head(collect(DISTINCT p.name)) AS person_name
                """, ids=creative_ids).data()

    def violations_of_creatives(self, creative_ids: list[str]) -> list[dict]:
        """事实行→图补 join（G15）：素材 → 违反的规范。规范是全局类，行权限天然豁免。"""
        if not creative_ids:
            return []
        with self.session() as s:
            return s.run(
                """
                UNWIND $ids AS cid
                MATCH (c:Entity {id: cid})-[:violates]->(g:Entity)
                RETURN cid, g.id AS gid, g.name AS guideline_name
                """, ids=creative_ids).data()

    def expand_to_creatives(self, ids: list[str]) -> list[str]:
        """实体集 → 素材集（§7.3 归因串行）：Brand/Product 反查 Case、Case 反查 Campaign
        再到 Creative；Creative 原样保留——entity_metrics 只认 creative_id 维度。"""
        if not ids:
            return []
        with self.session() as s:
            rows = s.run(
                """
                MATCH (e:Entity) WHERE e.id IN $ids
                OPTIONAL MATCH (e)<-[:for_brand|for_product]-(cs:Entity {class:'Case'})
                              <-[:belongs_to]-(cp:Entity)-[:uses]->(c1:Entity)
                OPTIONAL MATCH (e)<-[:belongs_to]-(cp2:Entity)-[:uses]->(c2:Entity)
                OPTIONAL MATCH (e)-[:uses]->(c3:Entity)
                WITH e, collect(DISTINCT c1.id) + collect(DISTINCT c2.id)
                     + collect(DISTINCT c3.id) AS cs
                RETURN e.id AS src, e.class AS cls,
                       CASE WHEN e.class = 'Creative' THEN cs + [e.id] ELSE cs END AS creatives
                """, ids=ids).data()
        out: set[str] = set()
        for r in rows:
            out.update(r["creatives"] or [])
        return sorted(out)
