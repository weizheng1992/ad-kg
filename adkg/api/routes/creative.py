"""素材草稿（§9.4 / §9.7「素材灵感」）：商品知识 × 最好相关案例素材 × 创意规范 → 素材草稿。

证据三路全带 provenance 且过权限（PermissionPlan 过滤，§12.4）：
- 商品知识：vector 路（商品 chunks，含同步文档的卖点/尺码/材质）
- 参考素材：text2sql top 口径（"最好"=成本型 ASC，§六）→ creative_contexts 挂回品牌，
  只留同类目品牌的最好素材作参考
- 创意规范：guidelines_with_thresholds（结构化阈值，前 3 秒钩子必须满足）

产出是灵感/草稿件：投放前须过 /guideline/check 机判与人工审（响应里明示）。
"""
from __future__ import annotations

import json
from fastapi import APIRouter, Header, HTTPException, Request

from adkg.guards.http import require_casegen_role
from adkg.retrieval.creative_evidence import best_creatives_for, related_brand_ids, \
    scoped_brands

router = APIRouter()

_SYSTEM_PROMPT = (
    "你是广告创意助手。基于【商品知识】【参考素材（同类目最好案例）】【创意规范】，"
    "为指定品牌的商品生成素材草稿。只输出 JSON："
    '{"creatives": [{"title", "format", "platform", "hook_3s", "script", "copy", "based_on"}]}。'
    "要求：hook_3s 是前 3 秒钩子，必须满足创意规范的结构化阈值；script 是分镜脚本"
    "（每镜一行：画面 / 口播 / 字幕，全脚本 ≤120 字）；copy 是投放文案（标题 + 正文，≤60 字）；"
    "based_on 列出参考的证据编号（如 [\"#1\",\"#3\"]）；"
    "只依据证据生成，证据没覆盖的卖点不要编；规范红线绝不写进脚本。"
)


@router.get("/creative/brands")
def creative_brands(request: Request, role: str | None = None, user: str | None = None,
                    authorization: str | None = Header(default=None)) -> dict:
    """品牌清单（素材生成的选择器数据源）——案例生成角色门 + 可见 Brand 裁剪（§12.4，
    2026-10-23 检查：曾对所有角色返回全量品牌+类目）。"""
    from adkg.guards.http import resolve_identity
    from adkg.guards.rbac import CASEGEN_ROLES
    role, user, planner = resolve_identity(request, authorization, role=role, user=user,
                                           dev_default="management")  # dev 无角色默认管理视角
    if role not in CASEGEN_ROLES:
        raise HTTPException(403, f"角色 {role} 无素材生成权限（允许：{sorted(CASEGEN_ROLES)}）")
    plan = planner.plan(role, person=user)
    from adkg.guards.http import get_graph
    graph = get_graph(request)
    with graph.session() as s:
        brands = s.run("MATCH (b:Entity {class:'Brand'})"
                       " RETURN b.id AS id, b.name AS name, b.category AS category"
                       " ORDER BY b.id").data()
    return {"brands": scoped_brands(brands, plan, graph)}


@router.post("/creative/draft")
def creative_draft(request: Request, body: dict,
                   authorization: str | None = Header(default=None)) -> dict:
    """生成素材草稿：n 条 {标题/形式/前3秒钩子/分镜/文案}，证据与规范随响应返回。"""
    env = request.app.state.env
    role, person = require_casegen_role(request, body, authorization)

    brand_id = str(body.get("brand_id") or "").strip()
    if not brand_id.startswith("Brand:"):
        raise HTTPException(422, "brand_id 必填且为 Brand:{slug} 形态（见 GET /creative/brands）")
    product = str(body.get("product") or "").strip()
    platform = str(body.get("platform") or "douyin").strip()
    try:
        n = max(1, min(int(body.get("n") or 3), 5))
    except (TypeError, ValueError):
        n = 3

    from adkg.guards.http import get_graph, get_llm, get_planner
    llm = get_llm(request)
    if llm is None:
        raise HTTPException(503, "LLM 不可用，无法生成（稍后重试，§7.2）")
    planner = get_planner(request)
    plan = planner.plan(role, person=person)
    graph = get_graph(request)

    # 证据 1：品牌本体 + 同类目品牌集合（相关案例的"相关"口径）
    try:
        related = related_brand_ids(graph, brand_id)
    except LookupError as e:
        raise HTTPException(404, str(e))
    with graph.session() as s:
        brand = s.run("MATCH (b:Entity {id:$id})"
                      " RETURN b.id AS id, b.name AS name, b.category AS category",
                      id=brand_id).single()

    # 证据 2：最好素材（模板口径，成本型 ASC）→ 图上下文过滤同类目
    from adkg.retrieval import vector_search
    references = best_creatives_for(graph, plan, env["ADKG_PG_RO_DSN"], related)

    # 证据 3：商品知识 chunks（vector 路，权限过滤下推）
    knowledge = vector_search.search(product or f"{brand['name']} 商品卖点",
                                     plan, env["ADKG_PG_DSN"], embed_fn=llm.embed)

    # 证据 4：创意规范（结构化阈值进 prompt）
    guidelines = graph.guidelines_with_thresholds()

    evidence = {"商品知识": knowledge.get("evidence", [])[:4],
                "参考素材": [{k: r.get(k) for k in
                              ("creative_id", "cpa", "ctr", "cost", "case_id", "brand_id")}
                             for r in references],
                "创意规范": guidelines}
    try:
        generate = getattr(llm, "chat_json_slow", None) or llm.chat_json   # 大证据 prompt 用长超时档
        payload = generate(_SYSTEM_PROMPT, _user_prompt(brand, product, platform, n, evidence))
        drafts = [d for d in payload.get("creatives", []) if isinstance(d, dict)][:n]
    except Exception as e:                               # 生成失败不编造（§7.2）
        raise HTTPException(503, f"生成失败请重试：{type(e).__name__}")
    if not drafts:
        raise HTTPException(503, "生成结果为空，请重试或补充商品信息")

    from adkg.guards.audit import audit                  # 审计写入收口（§9.1）
    audit(env, role, person, "creative_draft", f"{brand_id} {product or '-'}",
          "info", f"n={len(drafts)}")
    return {"brand": dict(brand), "product": product, "platform": platform,
            "drafts": drafts,
            "evidence": {"商品知识": knowledge.get("evidence", [])[:6],
                         "参考素材": references},
            "guidelines": guidelines,
            "knowledge_degraded": knowledge.get("degraded", False),
            "notice": "素材草稿为灵感件：投放前须过 /guideline/check 机判与人工审"}


def _user_prompt(brand: dict, product: str, platform: str, n: int, evidence: dict) -> str:
    return (json.dumps({
        "品牌": brand, "商品": product or "该品牌全部商品", "平台": platform, "条数": n,
        "商品知识": evidence["商品知识"],
        "参考素材（同类目最好案例）": evidence["参考素材"],
        "创意规范": evidence["创意规范"],
    }, ensure_ascii=False, default=str))

