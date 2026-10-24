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
from adkg.retrieval.metrics import STAT_FAMILY, agg_expr

router = APIRouter()

_COLS = ("id", "name", "platform", "niches", "followers", "quote_20s",
         "quote_image", "gmv_30d", "city", "rating", "cases")


def _collab_stats(env: dict, plan, case_ids: list[str]) -> dict | None:
    """达人合作案例维度的汇总投放统计（spec §3）：unified_metrics 汇总比（§六
    铁律）+ 指标列白名单——与 /graph stats、/brands 同一口径与同一道闸。"""
    import psycopg
    from psycopg.rows import dict_row

    if not case_ids:
        return None
    predicate = f" AND {plan.sql_predicate}" if plan.sql_predicate else ""
    try:
        proj = ", ".join(f"{agg_expr(c)} AS {c}" for c in STAT_FAMILY)
        with psycopg.connect(env["ADKG_PG_RO_DSN"], options="-c statement_timeout=3000",
                             row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {proj}, string_agg(DISTINCT platform::text, ',') AS platforms,"
                " count(DISTINCT date) AS days, min(date)::text AS first_day,"
                " max(date)::text AS last_day FROM unified_metrics"
                " WHERE NOT unmatched AND case_id = ANY(%(ids)s)" + predicate,
                {"ids": case_ids})
            row = cur.fetchone()
    except psycopg.Error:
        return None                                          # 统计失败不阻塞详情（§7.2 降级）
    if not row or row["days"] == 0:
        return None
    return {k: v for k, v in row.items()
            if k not in STAT_FAMILY or k in plan.allowed_columns}


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
    visible_cases = [c for c in collabs if not visible or c["id"] in visible]
    if plan.allow_properties:                               # 外部角色属性白名单（§12.4）
        visible_cases = [{"id": c["id"], "name": c["name"], "stage": c["stage"]}
                         for c in visible_cases]
    stats = _collab_stats(request.app.state.env, plan, [c["id"] for c in visible_cases])
    return {
        "creator": {"id": rec["id"], "name": rec["name"], "platform": rec["platform"],
                    "niches": (rec["niches"] or "").split("|") if rec["niches"] else [],
                    "followers": rec["followers"], "quote_20s": rec["quote_20s"],
                    "quote_image": rec["quote_image"], "gmv_30d": rec["gmv_30d"],
                    "city": rec["city"], "rating": rec["rating"]},
        # 行过滤：锚点角色只见自己子图内的合作（spec §3）；无行过滤角色（management/finance）全见
        "collabs": visible_cases,
        "collabs_filtered": len(collabs) - len(visible_cases),
        "products": products,
        "stats": stats,
    }
