"""POST /ingest/assertion（§9.4 / §11.2）：AIGC 断言写回——闭环后半边。

- provenance 恒为 conversation（authority 20），confidence 分级：
  ≥0.7 入图、0.4–0.7 进 review_queue、<0.4 丢弃（§12.1）
- 冲突仲裁（§12.2）：同 (subject, predicate, object) 已有更高 authority 的关系
  → 低者不覆盖，进 review_queue 人审
"""
from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import yaml
from fastapi import APIRouter, Header, HTTPException, Request
from pathlib import Path

from adkg.guards.auth import AuthService
from adkg.models import Provenance, Relation

router = APIRouter()

ACCEPT, REVIEW = 0.7, 0.4


@router.post("/ingest/assertion")
def ingest_assertion(request: Request, body: dict,
                     authorization: str | None = Header(default=None)) -> dict:
    env = request.app.state.env
    resolved = AuthService(env).resolve(authorization)
    if not resolved and not (env.get("ADKG_DEV_AUTH") == "off" and body.get("role")):
        raise HTTPException(401, "缺有效 service token")

    subject, predicate = body.get("subject"), body.get("predicate")
    obj, confidence = body.get("object"), float(body.get("confidence", 0))
    if not (subject and predicate and obj):
        raise HTTPException(422, "subject / predicate / object 必填")

    rels = {r["predicate"] for r in yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "ontology" / "schema.yaml").read_text(
            encoding="utf-8"))["relations"]}
    if predicate not in rels:
        raise HTTPException(422, f"谓词 {predicate} 不在 schema 关系表")

    prov = Provenance(source_type="conversation", source_id=body.get("source_id", "api"),
                      fetched_at=datetime.now(timezone.utc).isoformat(),
                      confidence=confidence)
    rel = Relation(source=subject, predicate=predicate, target=obj,
                   provenance=prov, confidence=confidence)
    pg = env["ADKG_PG_DSN"]

    if confidence < REVIEW:
        return {"status": "dropped", "reason": f"confidence {confidence} < {REVIEW}（§12.1）"}

    def push_review(kind: str, payload: dict) -> None:
        import json
        with psycopg.connect(pg) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO review_queue (kind, payload) VALUES (%s, %s)",
                        (kind, json.dumps(payload, ensure_ascii=False, default=str)))

    if confidence < ACCEPT:
        push_review("low_confidence", {"relation": rel.model_dump(),
                                        "confidence": confidence})
        return {"status": "review", "reason": f"confidence ∈ [0.4, 0.7) → 人审（§12.1）"}

    # 冲突仲裁：已有更高 authority 的同边 → 低者不覆盖
    from adkg.api.routes.actions import _graph
    graph = _graph(request)
    with graph.session() as s:
        prev = s.run(f"MATCH (a:Entity {{id: $s}})-[r:{predicate}]->(b:Entity {{id: $o}})"
                     " RETURN r.authority AS auth LIMIT 1", s=subject, o=obj).single()
    if prev and prev["auth"] is not None and prev["auth"] > prov.authority:
        push_review("conflict", {"relation": rel.model_dump(),
                                 "existing_authority": prev["auth"],
                                 "reason": "已有更高 authority 同边，低者进人审（§12.2）"})
        return {"status": "review", "reason": f"已有 authority={prev['auth']} 同边，不覆盖"}

    graph.upsert_relations([rel])
    return {"status": "written", "authority": prov.authority,
            "confidence": confidence}
