"""GET /graph/entity（§四 api/routes/graph.py）：实体、关系展开、来源。

供 web 图谱页与 smartServe 工具用；权限同 /ask（token 或 dev 模式，
PermissionPlan 可见集过滤）。
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.auth import AuthService

router = APIRouter()


@router.get("/graph/entity")
def graph_entity(request: Request, id: str, hops: int = 1,
                 role: str | None = None, user: str | None = None,
                 authorization: str | None = Header(default=None)) -> dict:
    env = request.app.state.env
    resolved = AuthService(env).resolve(authorization)
    if resolved:
        role = resolved[0]
    elif not (env.get("ADKG_DEV_AUTH") == "off" and role):
        raise HTTPException(401, "缺有效 service token")

    from adkg.api.routes.ask import _graph, _planner
    graph = _graph(request)
    plan = _planner(request).plan(role, person=user)
    visible = plan.visible_entity_ids
    allowed_classes = set(plan.metadata_filter.get("entity_class__in", []))

    with graph.session() as s:
        rec = s.run("MATCH (n:Entity {id: $id})"
                    " RETURN n.id AS id, n.class AS class, n.name AS name,"
                    " n.stage AS stage, n.authority AS authority", id=id).single()
        if not rec:
            raise HTTPException(404, f"实体 {id} 不存在")
        rows = s.run(
            "MATCH (a:Entity {id: $id})-[r]-(b:Entity) RETURN a.id AS src,"
            " type(r) AS rel, b.id AS dst, b.class AS cls, b.name AS name,"
            " r.confidence AS conf, r.prov_source AS psrc,"
            " r.authority AS auth LIMIT 100", id=id).data()

    edges, filtered = [], 0
    global_classes = {"Metric", "Guideline", "Channel"}
    for r in rows:
        if allowed_classes and r["cls"] not in allowed_classes and r["cls"] not in global_classes:
            filtered += 1
            continue
        if visible and r["dst"] not in visible and not (r["src"] in visible):
            filtered += 1
            continue
        edges.append(r)

    return {
        "entity": dict(rec),
        "neighbors": [{"id": r["dst"], "class": r["cls"], "name": r["name"],
                       "via": r["rel"], "confidence": r["conf"],
                       "provenance": {"source_type": r["psrc"], "authority": r["auth"]}}
                      for r in edges],
        "filtered": filtered,
        "role": role,
    }
