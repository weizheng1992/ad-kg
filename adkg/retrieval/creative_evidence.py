"""素材生成的证据三件套（§9.4「素材灵感」）：权限过滤下的品牌/素材检索。

2026-10-28 自 api/routes/creative.py 下沉——它们是检索活（PermissionPlan 过滤 +
图查询 + text2sql 口径），不是 HTTP；agent 工具与 /creative/* 两个消费者共用，
route 层不再互相挖私有符号（§9.1 import 只向下）。
"""
from __future__ import annotations


def scoped_brands(brands: list[dict], plan, graph) -> list[dict]:
    """品牌按行权限裁剪：可见 Brand ∪ 可见案例所属品牌（optimizer 的路径不经过 Brand
    节点，但其案例属于品牌——生成素材需要品牌选择器，按案例归属放行）。"""
    if plan.deny_all:
        return []
    visible = plan.visible_entity_ids
    if not visible:
        return brands
    allowed = {i for i in visible if i.startswith("Brand:")}
    case_ids = [i for i in visible if i.startswith("Case:")]
    if case_ids:
        with graph.session() as s:
            allowed |= {r["b"] for r in s.run(
                "MATCH (c:Entity)-[:for_brand]->(b:Entity) WHERE c.id IN $cs"
                " RETURN DISTINCT b.id AS b", cs=case_ids).data()}
    return [b for b in brands if b["id"] in allowed]


def related_brand_ids(graph, brand_id: str) -> set[str]:
    """"相关案例"口径：本品牌 + 同类目品牌集合。"""
    with graph.session() as s:
        brand = s.run("MATCH (b:Entity {id:$id})"
                      " RETURN b.id AS id, b.name AS name, b.category AS category",
                      id=brand_id).single()
        if not brand:
            raise LookupError(f"品牌不存在：{brand_id}")
        row = s.run("MATCH (b:Entity {class:'Brand'}) WHERE b.category = $c"
                    " RETURN collect(b.id) AS ids", c=brand["category"]).single()
    return set(row["ids"] or []) | {brand_id}


def best_creatives_for(graph, plan, dsn_ro: str, related: set[str], k: int = 5) -> list[dict]:
    """同类目最好素材：模板口径（成本型 ASC，20 池——top5 常无同类目）+ 图上下文过滤。"""
    from adkg.retrieval import text2sql
    top = text2sql.run("CPA 最好的 20 个素材", plan, dsn_ro, None, generator=None)
    fact_rows = next((ev.get("rows") or [] for ev in top["evidence"]
                      if ev.get("type") == "fact"), [])
    ctx = graph.creative_contexts([r["creative_id"] for r in fact_rows
                                   if r.get("creative_id")])
    return [{**r, **ctx.get(r.get("creative_id"), {})} for r in fact_rows
            if ctx.get(r.get("creative_id"), {}).get("brand_id") in related][:k]
