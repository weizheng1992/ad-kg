"""POST /ingest/assertion（§9.4 / §11.2）：AIGC 断言写回——闭环后半边。

- provenance 恒为 conversation（authority 20），confidence 分级：
  ≥0.7 入图、0.4–0.7 进 review_queue、<0.4 丢弃（§12.1）
- 冲突仲裁（§12.2）：同 (subject, predicate, object) 已有更高 authority 的关系
  → 低者不覆盖，进 review_queue 人审

文档 → 案例三端点（§9.4/§9.5，web「案例生成」页背后）：定时同步只入 chunks，
本组端点补"文档 → 图谱实体"最后一跳——草稿（LLM 抽取 + L1 对齐，不写库）→
人工确认 → 服务端重校验入图（official_doc/60，仲裁保护主数据）。
"""
from __future__ import annotations

from datetime import datetime, timezone

import psycopg
import yaml
from fastapi import APIRouter, Header, HTTPException, Request
from pathlib import Path

from adkg.guards.http import get_graph
from adkg.models import Provenance, Relation
from adkg.pipeline.resolution import normalize_name

router = APIRouter()

ACCEPT, REVIEW = 0.7, 0.4
CASEGEN_ROLES = {"admin", "management", "optimizer", "ae"}     # 案例生成 = 内部操作角色


def _casegen_role(request: Request, body: dict,
                  authorization: str | None) -> tuple[str, str | None]:
    """认证 + 案例生成角色门（token 反查优先，dev 模式 body 兜底，fail-closed）；
    person 一并返回（token 路取绑定值——审计 user_id 用，2026-10-24 起）。"""
    from adkg.guards.http import resolve_identity
    role, person, _planner = resolve_identity(request, authorization, body=body)
    if role not in CASEGEN_ROLES:
        raise HTTPException(403, f"角色 {role} 无案例生成权限（允许：{sorted(CASEGEN_ROLES)}）")
    return role, person


@router.get("/ingest/docs")
def list_synced_docs(request: Request, q: str | None = None, role: str | None = None,
                     authorization: str | None = Header(default=None)) -> dict:
    """列已同步飞书文档：chunks 聚合 + ingest_job 最新版本；标题取 chunk#0 首行。
    内部角色门（§12.4，2026-10-23：标题含他牌投放月报/案例复盘，外部角色 403）。"""
    env = request.app.state.env
    from adkg.guards.http import resolve_identity
    role, _person, planner = resolve_identity(request, authorization, role=role,
                                              dev_default="management")   # dev 无角色默认管理视角
    if planner.perms["roles"].get(role, {}).get("external"):
        raise HTTPException(403, "外部角色不可见文档清单")
    return {"docs": synced_docs(env["ADKG_PG_DSN"], q)}


def synced_docs(pg_dsn: str, q: str | None = None) -> list[dict]:
    """已同步飞书文档清单（route 与 agent 工具共用）。"""
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT doc_id, count(*), min(text) FILTER (WHERE chunk_index = 0)"
                    " FROM chunks WHERE doc_id LIKE 'feishu:%' GROUP BY doc_id ORDER BY doc_id")
        rows = cur.fetchall()
        cur.execute("SELECT DISTINCT ON (source_id) source_id, version, updated_at"
                    " FROM ingest_job WHERE source_id LIKE 'feishu:%'"
                    " ORDER BY source_id, updated_at DESC")
        jobs = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    docs = []
    for doc_id, n, head in rows:
        title = next((ln.lstrip("#").strip() for ln in (head or "").splitlines()
                      if ln.strip()), "") or doc_id
        if q and q.lower() not in f"{title} {doc_id}".lower():
            continue
        version, updated = jobs.get(doc_id, (None, None))
        docs.append({"doc_id": doc_id, "title": title, "chunks": n,
                     "version": version,
                     "updated_at": updated.isoformat() if updated else None})
    return docs


@router.post("/ingest/case-draft")
def case_draft(request: Request, body: dict,
               authorization: str | None = Header(default=None)) -> dict:
    """已同步文档 → 案例草稿（LLM 抽取 + L1 对齐，只读不写）。"""
    _casegen_role(request, body, authorization)
    doc_id = str(body.get("doc_id") or "").strip()
    if not doc_id.startswith("feishu:"):
        raise HTTPException(422, "doc_id 必须是已同步飞书文档（feishu:doc:…，见 GET /ingest/docs）")
    env = request.app.state.env
    with psycopg.connect(env["ADKG_PG_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT text FROM chunks WHERE doc_id = %s ORDER BY chunk_index", (doc_id,))
        rows = cur.fetchall()
    if not rows:
        raise HTTPException(404, f"文档未同步或无内容：{doc_id}")

    from adkg.api.routes.ask import _llm
    llm = _llm(request)
    if llm is None:
        raise HTTPException(503, "LLM 不可用，无法抽取草稿（稍后重试，§7.2）")
    from adkg.models import load_schema
    from adkg.pipeline.case_gen import build_draft
    graph = get_graph(request)
    try:
        return build_draft(doc_id, "\n".join(r[0] for r in rows)[:6000], graph,
                           load_schema(),
                           lambda s, u: llm.chat_json(s, u, timeout=60, max_retries=0),
                           now=datetime.now(timezone.utc))   # 抽取显式单发限时（§7.2）
    except HTTPException:
        raise
    except Exception as e:                               # LLM/解析失败不编造草稿
        raise HTTPException(503, f"抽取失败请重试：{type(e).__name__}")


@router.post("/ingest/case-commit")
def case_commit(request: Request, body: dict,
                authorization: str | None = Header(default=None)) -> dict:
    """草稿确认入图：服务端重校验（不信客户端）→ 写实体/关系 → 别名注册 → 审计。"""
    env = request.app.state.env
    role, person = _casegen_role(request, body, authorization)
    draft = body.get("draft")
    if not isinstance(draft, dict):
        raise HTTPException(422, "draft 必填（/ingest/case-draft 的返回原样传回）")

    from adkg.models import load_schema
    from adkg.pipeline.case_gen import commit_draft
    graph = get_graph(request)
    try:
        result = commit_draft(draft, graph, load_schema(), now=datetime.now(timezone.utc))
    except ValueError as e:
        raise HTTPException(422, str(e))

    with psycopg.connect(env["ADKG_PG_DSN"]) as conn:
        with conn.cursor() as cur:
            for w in result.get("written", []):          # 新实体注册别名：后续 ETL/抽取 L1 可命中
                cur.execute("INSERT INTO entity_alias (source, external_id, internal_id)"
                            " VALUES ('name', %s, %s) ON CONFLICT DO NOTHING",
                            (normalize_name(str(w["name"])), w["id"]))
        # 审计收口（§9.1）：与别名注册同事务落账（外部 conn 复用），回滚同生共死
        from adkg.guards.audit import audit
        audit(env, role, person, "create_case", result["case_id"], "allow",
              f"case-commit from {draft.get('doc_id')}", conn=conn)

    return {"status": "written", **result}


@router.post("/ingest/assertion")
def ingest_assertion(request: Request, body: dict,
                     authorization: str | None = Header(default=None)) -> dict:
    env = request.app.state.env
    from adkg.guards.http import resolve_identity
    role, person, planner = resolve_identity(request, authorization, body=body)
    # 动作门 + 审计（§12.4，2026-10-23 检查：曾无门无账，client 可直写图关系）
    actions = planner.perms["roles"].get(role, {}).get("actions", [])
    if "write_assertion" not in actions:
        raise HTTPException(403, f"角色 {role} 无断言写入权限（actions 不含 write_assertion）")

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
    graph = get_graph(request)
    with graph.session() as s:
        prev = s.run(f"MATCH (a:Entity {{id: $s}})-[r:{predicate}]->(b:Entity {{id: $o}})"
                     " RETURN r.authority AS auth LIMIT 1", s=subject, o=obj).single()
    if prev and prev["auth"] is not None and prev["auth"] > prov.authority:
        push_review("conflict", {"relation": rel.model_dump(),
                                 "existing_authority": prev["auth"],
                                 "reason": "已有更高 authority 同边，低者进人审（§12.2）"})
        return {"status": "review", "reason": f"已有 authority={prev['auth']} 同边，不覆盖"}

    graph.upsert_relations([rel])
    from adkg.guards.audit import audit                      # 写图随写落账（§12.4）
    audit(env, role, person, "write_assertion", f"{subject} -{predicate}-> {obj}",
          "info", f"written, confidence={confidence}")
    return {"status": "written", "authority": prov.authority,
            "confidence": confidence}
