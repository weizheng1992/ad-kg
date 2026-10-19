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
        """etl_facts 物化维度列用（§八）：素材 → 所属计划/案例/品牌。"""
        if not creative_ids:
            return {}
        with self.session() as s:
            rows = s.run(
                """
                UNWIND $ids AS cid
                OPTIONAL MATCH (c:Entity {id: cid})<-[:uses]-(cp:Entity)
                    -[:belongs_to]->(cs:Entity)
                OPTIONAL MATCH (cs)-[:for_brand]->(b:Entity)
                RETURN cid, head(collect(DISTINCT cp.id)) AS campaign_id,
                       head(collect(DISTINCT cs.id)) AS case_id,
                       head(collect(DISTINCT b.id))  AS brand_id
                """, ids=creative_ids)
            return {r["cid"]: {"campaign_id": r["campaign_id"], "case_id": r["case_id"],
                               "brand_id": r["brand_id"]} for r in rows}
