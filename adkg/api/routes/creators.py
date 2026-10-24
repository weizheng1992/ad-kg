"""GET /creators + /creators/{id}（spec §3）：达人库主数据端点。

可见性：Creator 是平台级主数据（schema 注记）——类白名单即可见，不走
row_filter 锚点收敛（ae/optimizer 的锚是案例子图，达人库是选人入口）；
client / creative 类白名单不含 Creator 即 403。合作历史（collabs_with）
仍按 plan.visible_entity_ids 收敛——锚点外的案例不出现在达人详情里。
带货商品（promotes → Product）另过类白名单：无 Product 权限的角色不返回该段。
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.http import get_graph, resolve_identity

router = APIRouter()

_COLS = ("id", "name", "platform", "niches", "followers", "quote_20s",
         "quote_image", "gmv_30d", "city", "rating", "cases")


def _require_creator(plan) -> None:
    if plan.deny_all:
        raise HTTPException(403, "行权限未生效（缺有效身份），拒绝读取")
    allowed = set(plan.metadata_filter.get("entity_class__in", []))
    if "Creator" not in allowed:
        raise HTTPException(403, "类 Creator 不在当前角色白名单")


@router.get("/creators")
def list_creators(request: Request, q: str = "", platform: str = "", niche: str = "",
                  min_followers: int = 0, max_quote: int = 0,
                  page: int = 1, size: int = 20,
                  role: str | None = None, user: str | None = None,
                  authorization: str | None = Header(default=None)) -> dict:
    role, user, planner = resolve_identity(request, authorization, role=role, user=user)
    plan = planner.plan(role, person=user)
    _require_creator(plan)
    size = max(1, min(size, 100))
    page = max(1, page)
    where = ("($q = '' OR n.name CONTAINS $q)"
             " AND ($platform = '' OR n.platform = $platform)"
             " AND ($niche = '' OR n.niches CONTAINS $niche)"
             " AND coalesce(n.followers, 0) >= $min_followers"
             " AND ($max_quote <= 0 OR coalesce(n.quote_20s, 0) <= $max_quote)")
    args = {"q": q.strip(), "platform": platform.strip(), "niche": niche.strip(),
            "min_followers": min_followers, "max_quote": max_quote,
            "skip": (page - 1) * size, "size": size}
    with get_graph(request).session() as s:
        items = s.run(
            f"MATCH (n:Entity {{class: 'Creator'}}) WHERE {where} "
            "OPTIONAL MATCH (c:Entity)-[:collabs_with]->(n) "
            "WITH n, count(DISTINCT c) AS cases "
            "ORDER BY n.followers DESC SKIP $skip LIMIT $size "
            "RETURN n.id AS id, n.name AS name, n.platform AS platform, n.niches AS niches, "
            "n.followers AS followers, n.quote_20s AS quote_20s, n.quote_image AS quote_image, "
            "n.gmv_30d AS gmv_30d, n.city AS city, n.rating AS rating, cases", **args).data()
        total = s.run(f"MATCH (n:Entity {{class: 'Creator'}}) WHERE {where} "
                      "RETURN count(n) AS total", **args).single()["total"]
    return {"items": [{**{k: it[k] for k in _COLS[:-1]},
                       "niches": (it["niches"] or "").split("|") if it["niches"] else [],
                       "cases": it["cases"]} for it in items],
            "total": total, "page": page, "size": size}


@router.get("/creators/{cid}")
def creator_detail(request: Request, cid: str,
                   role: str | None = None, user: str | None = None,
                   authorization: str | None = Header(default=None)) -> dict:
    role, user, planner = resolve_identity(request, authorization, role=role, user=user)
    plan = planner.plan(role, person=user)
    _require_creator(plan)
    visible = plan.visible_entity_ids
    with get_graph(request).session() as s:
        rec = s.run("MATCH (n:Entity {id: $id}) RETURN n.id AS id, n.name AS name, "
                    "n.platform AS platform, n.niches AS niches, n.followers AS followers, "
                    "n.quote_20s AS quote_20s, n.quote_image AS quote_image, "
                    "n.gmv_30d AS gmv_30d, n.city AS city, n.rating AS rating, "
                    "n.class AS class", id=cid).single()
        if not rec or rec["class"] != "Creator":
            raise HTTPException(404, f"达人 {cid} 不存在")
        collabs = s.run(
            "MATCH (c:Entity)-[:collabs_with]->(n:Entity {id: $id}) "
            "WHERE c.class = 'Case' "
            "RETURN c.id AS id, c.name AS name, c.stage AS stage, "
            "c.lost_reason AS lost_reason ORDER BY c.id", id=cid).data()
        products = []
        if "Product" in set(plan.metadata_filter.get("entity_class__in", [])):
            products = s.run(
                "MATCH (n:Entity {id: $id})-[:promotes]->(p:Entity) "
                "RETURN p.id AS id, p.name AS name, p.price AS price, "
                "p.spec AS spec, p.target_age AS target_age ORDER BY p.id", id=cid).data()
    return {
        "creator": {"id": rec["id"], "name": rec["name"], "platform": rec["platform"],
                    "niches": (rec["niches"] or "").split("|") if rec["niches"] else [],
                    "followers": rec["followers"], "quote_20s": rec["quote_20s"],
                    "quote_image": rec["quote_image"], "gmv_30d": rec["gmv_30d"],
                    "city": rec["city"], "rating": rec["rating"]},
        # 行过滤：锚点角色只见自己子图内的合作（spec §3）；无行过滤角色（management/finance）全见
        "collabs": [c for c in collabs if not visible or c["id"] in visible],
        "collabs_filtered": len(collabs) - sum(1 for c in collabs
                                               if not visible or c["id"] in visible),
        "products": products,
    }
