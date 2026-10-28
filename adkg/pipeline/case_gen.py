"""文档 → 案例草稿（§9.4 / §9.5）：已同步飞书文档 → LLM 抽 Brand/Product/Case 草稿
→ L1 对齐既有实体 → 人工确认（/ingest/case-commit）才入图。

为什么有这一步：定时同步（sync_feishu）只入 chunks 不建实体；而铁律（§十二）是
"抽取产物必须先过对齐才能入图——未对齐直接入图会污染检索"（实测教训）。
所以全新实体不自动入图：草稿确认即人审，commit 服务端重校验后写入。
provenance 选型 official_doc（authority 60）——低于 system_of_record(100)，
冲突仲裁天然保护主数据；source_id=doc_id 让案例可溯源到文档。

关系不交给 LLM 抽：从草稿块（brand/product/case/persons）确定性构造
for_brand / for_product / has_product / responsible_for，少一类幻觉面。
"""
from __future__ import annotations

from datetime import datetime

from adkg.models import CaseStage, Entity, Provenance, Relation, SourceType
from adkg.pipeline.resolution import normalize_name

_SYSTEM_PROMPT = (
    "你是广告投放知识中台的案例抽取器。从【文档】中抽出一个品牌、它的全部商品、投放案例和提到的负责人，"
    '只输出 JSON：{"brand": {"name": "…", "props": {}}, "products": [{"name": "…", "props": {}}],'
    ' "case": {"name": "…", "stage": "proposal|live|closed|lost|terminated", "props": {}},'
    ' "persons": [{"name": "…", "org_role": "…"}]}。'
    "某块文档里没有就给 null / 空数组；商品有多个就全抽；props 只填文档明确给出的属性；不确定就不要编。"
)


def _collapse(name: str) -> str:
    """实体 id 的 slug 段：L1 归一化 + 内部空白折叠（中文保留，§12.5 平台无关）。"""
    return normalize_name(name).replace(" ", "-") or name.strip()


def build_draft(doc_id: str, doc_text: str, graph, schema: dict, chat_json, *,
                now: datetime) -> dict:
    """抽草稿（只读图，不写任何库）。返回可 JSON 化的草稿 dict。"""
    triples = {(r["source"], r["predicate"], r["target"]) for r in schema["relations"]}
    payload = chat_json(_SYSTEM_PROMPT, f"【文档】\n{doc_text}")
    if not isinstance(payload, dict):
        raise ValueError("LLM 返回不是 JSON 对象")
    warnings: list[str] = []

    def node(cls: str, raw) -> dict | None:
        """LLM 单对象块 → 草稿节点；缺名警告是 LLM 路特有（物化路种子由 agent 保证）。"""
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            if raw is not None:
                warnings.append(f"{cls} 缺名称，未纳入草稿")
            return None
        return _ensure_node(graph, schema, cls, str(raw["name"]).strip(), doc_id,
                            now=now, raw_props=raw.get("props"),
                            stage_raw=raw.get("stage"), warnings=warnings)

    brand = node("Brand", payload.get("brand"))
    case = node("Case", payload.get("case"))

    # 商品是数组（文档常列多商品）；兼容 LLM 偶发给单数 product 对象
    raw_products = payload.get("products")
    if raw_products is None and isinstance(payload.get("product"), dict):
        raw_products = [payload["product"]]
    products = [p for p in (node("Product", raw) for raw in raw_products or []) if p]

    persons: list[dict] = []
    for p in payload.get("persons") or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        pid = _align(graph, "Person", name)
        if pid:
            persons.append({"id": pid, "name": name, "aligned": True})
        else:
            warnings.append(f"负责人「{name}」未对齐到既有 Person，已丢弃（未对齐不入图）")

    relations = _wire(case, brand, products, persons, triples, warnings)
    return {"doc_id": doc_id, "case": case, "brand": brand, "products": products,
            "persons": persons, "relations": relations, "warnings": warnings}


def _wire(case, brand, products, persons, triples, warnings) -> list[dict]:
    """从草稿块确定性构造关系（schema 三元组校验兜底）。"""
    out = []
    candidates = []
    if case and brand:
        candidates.append(("for_brand", case["id"], brand["id"]))
    for p in products:
        if case and p:
            candidates.append(("for_product", case["id"], p["id"]))
        if brand and p:
            candidates.append(("has_product", brand["id"], p["id"]))
    for p in persons:
        if case:
            candidates.append(("responsible_for", p["id"], case["id"]))
    for pred, src, dst in candidates:
        if (src.split(":")[0], pred, dst.split(":")[0]) in triples:
            out.append({"source": src, "predicate": pred, "target": dst})
        else:                                            # schema 改动时的兜底，正常不触
            warnings.append(f"关系不在 schema 三元组，丢弃：({src})-[:{pred}]->({dst})")
    return out


def _props_of(schema: dict, cls: str, name: str, raw: dict | None) -> dict:
    """属性白名单过滤（schema properties ∪ name），fail-closed（§12.4）。"""
    allowed = set(schema["classes"][cls]["properties"]) | {"name"}
    props = {k: v for k, v in (raw or {}).items() if k in allowed and v not in (None, "")}
    props["name"] = name
    return props


def _align(graph, cls: str, name: str) -> str | None:
    """L1 对齐（同 scripts/enrich_aligned.align 口径）：规范 id 精确 → name 精确/包含。"""
    if not name:
        return None
    with graph.session() as s:
        row = s.run("MATCH (n:Entity {id: $id}) RETURN n.id AS id LIMIT 1",
                    id=f"{cls}:{_collapse(name)}").single()
        if row:
            return row["id"]
        row = s.run("MATCH (n:Entity) WHERE n.class=$cls"
                    " AND (n.name=$name OR n.name CONTAINS $name)"
                    " RETURN n.id AS id ORDER BY size(n.name) LIMIT 1",
                    cls=cls, name=name).single()
        return row["id"] if row else None


_STAGES = {s.value for s in CaseStage}                   # Case 状态机合法值（两路共用）


def _ensure_node(graph, schema: dict, cls: str, name: str, doc_id: str, *,
                 now: datetime, raw_props: dict | None = None,
                 stage_raw=None, warnings: list[str] | None = None) -> dict:
    """草稿节点单点实现（build_draft ↔ materialize_draft 原各闭包一份，同构收敛）：
    L1 对齐 → 建号 → 属性白名单（raw_props=None 即仅 name）→ Case 补 stage（非法回 proposal）。
    name 非空由调用方保证。差异保留：warnings 传入时非法 stage 记警告（LLM 路要给人看）；
    物化路不传 → 静默回 proposal（旧行为，种子来自 agent 不必回显）。
    """
    eid = _align(graph, cls, name)
    existing = eid is not None
    same_doc = False
    if not existing:
        if cls == "Case":                                # 案例走编号约定 + 同文档幂等复用
            eid, same_doc = case_id_for(graph, doc_id, now)
            existing = same_doc
        else:
            eid = f"{cls}:{_collapse(name)}"
    props = _props_of(schema, cls, name, raw_props)
    if cls == "Case":
        stage = str(stage_raw or "").strip().lower()
        if stage and stage not in _STAGES and warnings is not None:
            warnings.append(f"stage {stage!r} 不在状态机，回 proposal")
        props["stage"] = stage if stage in _STAGES else "proposal"
    return {"id": eid, "name": name, "props": props, "existing": existing,
            "same_doc": same_doc}


def materialize_draft(doc_id: str, seed: dict, graph, schema: dict, *,
                      now: datetime) -> dict:
    """agent 的结构化种子 → 标准草稿（对齐/建号/关系构造与 build_draft 同一套，服务端可信路径）。

    seed: {brand_name, product_names: [], case_name?, stage?, person_ids: []}
    Person 只收 id 且必须真实存在（未对齐不入图）；brand/product 只给名字，由本函数对齐或建号。
    """
    triples = {(r["source"], r["predicate"], r["target"]) for r in schema["relations"]}
    warnings: list[str] = []

    def node(cls: str, name: str) -> dict | None:
        name = str(name or "").strip()
        if not name:
            return None
        return _ensure_node(graph, schema, cls, name, doc_id, now=now,
                            stage_raw=seed.get("stage"))

    brand = node("Brand", seed.get("brand_name"))
    products = [p for p in (node("Product", n)
                            for n in seed.get("product_names") or []) if p]
    case = node("Case", seed.get("case_name"))
    if not any([brand, products, case]):
        raise ValueError("种子没有任何可入图实体（brand / products / case 全空）")

    persons = []
    for pid in seed.get("person_ids") or []:
        with graph.session() as s:
            row = s.run("MATCH (p:Entity {id:$id, class:'Person'})"
                        " RETURN p.id AS id, p.name AS name", id=str(pid)).single()
        if row:
            persons.append({"id": row["id"], "name": row["name"], "aligned": True})
        else:
            warnings.append(f"负责人 {pid} 不存在，已丢弃（未对齐不入图）")

    relations = _wire(case, brand, products, persons, triples, warnings)
    return {"doc_id": doc_id, "case": case, "brand": brand, "products": products,
            "persons": persons, "relations": relations, "warnings": warnings}


def case_id_for(graph, doc_id: str, now: datetime) -> tuple[str, bool]:
    """案例 id：同文档已生成过 → 复用（幂等）；否则当年最大序号 +1。返回 (id, 已存在)。"""
    with graph.session() as s:
        row = s.run("MATCH (n:Entity) WHERE n.class='Case' AND n.prov_source_id=$doc"
                    " RETURN n.id AS id LIMIT 1", doc=doc_id).single()
        if row:
            return row["id"], True
        prefix = f"Case:C-{now.year}-"
        seqs = [int(r["id"].rsplit("-", 1)[1]) for r in s.run(
            "MATCH (n:Entity) WHERE n.class='Case' AND n.id STARTS WITH $p"
            " RETURN n.id AS id", p=prefix).data()
            if r["id"].rsplit("-", 1)[1].isdigit()]
        return f"{prefix}{max(seqs, default=0) + 1:03d}", False


def commit_draft(draft: dict, graph, schema: dict, *, now: datetime) -> dict:
    """服务端重校验后入图（不信客户端 draft）：身份重推导 + 只写新实体与构造关系。

    信任面（2026-10-28 收口）：existing / same_doc / eid 一律不读客户端——
    身份按 build_draft 同款规则从图上重推导（L1 对齐 → Case 走 case_id_for
    幂等复用与建号 → 其余走确定性 slug），对齐命中不碰（主数据保护），对齐
    不中才写；对齐命中的 Case 仍作为 case_id 回跳锚。"同文档旧产物可刷新"
    由 case_id_for 的 prov_source_id==doc_id 判定给出，客户端无从伪造。
    仲裁（§12.2）：目标 id 已有更高 authority → 不覆盖，跳过并记 warning；
    端点被拦的关系一并跳过（防把边挂到没写进去的节点上）。
    warnings 只装服务端产生的警告——draft.warnings 是客户端回显字段，不采信。
    """
    triples = {(r["source"], r["predicate"], r["target"]) for r in schema["relations"]}
    case = draft.get("case") if isinstance(draft.get("case"), dict) else None
    doc_id = str(draft.get("doc_id") or "api")
    nodes = [("Case", case), ("Brand", draft.get("brand"))] + \
        [("Product", p) for p in draft.get("products") or []]
    if not any(isinstance(n, dict) and str(n.get("name") or "").strip() for _, n in nodes):
        raise ValueError("草稿没有任何可入图实体（case / brand / products 全空）")
    warnings: list[str] = []
    prov = Provenance(source_type=SourceType.OFFICIAL_DOC,
                      source_id=doc_id, fetched_at=now)

    entities, blocked, case_eid = [], set(), ""
    for cls, node in nodes:
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or "").strip()
        if not name:
            warnings.append(f"{cls} 缺名称，跳过")
            continue
        aligned = _align(graph, cls, name)                  # 身份重推导：L1 对齐优先
        if aligned:
            if cls == "Case":
                case_eid = aligned                          # 命中的既有案例仍是回跳锚
            continue                        # 对齐命中的既有实体不碰（主数据保护）
        if cls == "Case":                               # 幂等复用 / 顺位建号（服务端权威）
            eid, same_doc = case_id_for(graph, doc_id, now)
            if same_doc:
                case_eid = eid                  # 本文档旧产物按 prov_source_id 认定，可刷新
        else:
            eid = f"{cls}:{_collapse(name)}"
        prev = _node_authority(graph, eid)
        if prev is not None and prev > prov.authority:
            warnings.append(f"{eid} 已有 authority={prev} 的主数据，不覆盖（§12.2）")
            blocked.add(eid)
            continue
        if cls == "Case":
            case_eid = eid
        entities.append(Entity(entity_class=cls, entity_id=eid,
                               props=_props_of(schema, cls, name, node.get("props")),
                               provenance=prov))

    relations = []
    for rel in draft.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        src, pred, dst = str(rel.get("source") or ""), str(rel.get("predicate") or ""), \
            str(rel.get("target") or "")
        if (src.split(":")[0], pred, dst.split(":")[0]) not in triples:
            warnings.append(f"关系不在 schema 三元组，丢弃：({src})-[:{pred}]->({dst})")
            continue
        if src in blocked or dst in blocked:
            continue
        prev = _edge_authority(graph, pred, src, dst)
        if prev is not None and prev > prov.authority:
            warnings.append(f"({src})-[:{pred}]->({dst}) 已有 authority={prev} 同边，不覆盖")
            continue
        relations.append(Relation(source=src, predicate=pred, target=dst,
                                  provenance=prov, confidence=1.0))

    graph.upsert_entities(entities)
    graph.upsert_relations(relations)
    return {"case_id": case_eid,                          # 商品知识文档无案例时为空串
            "entities": len(entities), "relations": len(relations),
            "written": [{"id": e.entity_id, "name": e.props.get("name")} for e in entities],
            "warnings": warnings}


def _node_authority(graph, eid: str) -> int | None:
    with graph.session() as s:
        row = s.run("MATCH (n:Entity {id: $id}) RETURN n.authority AS auth LIMIT 1",
                    id=eid).single()
        return row["auth"] if row else None


def _edge_authority(graph, pred: str, src: str, dst: str) -> int | None:
    with graph.session() as s:
        row = s.run(f"MATCH (a:Entity {{id: $s}})-[r:{pred}]->(b:Entity {{id: $o}})"
                    " RETURN r.authority AS auth LIMIT 1", s=src, o=dst).single()
        return row["auth"] if row else None
