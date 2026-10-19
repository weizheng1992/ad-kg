"""对齐抽取（§7.4 L1 落地）：飞书文档 → LLM 抽取 → 实体按 name/id 对齐到既有节点
→ 只写两端都命中的关系（conversation/20）——加密关联且零噪声。

未对齐的实体直接丢弃（不建新节点）；这与抽取回归的教训一致：
未经对齐的抽取产物会污染检索。
用法：uv run python scripts/enrich_aligned.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from adkg.llm import LLMClient                    # noqa: E402
from adkg.models import load_schema               # noqa: E402
from adkg.pipeline.extraction import Extractor    # noqa: E402
from adkg.store.graph import GraphStore           # noqa: E402


def align(graph, cls: str, slug: str, name: str) -> str | None:
    """L1：id 精确 → name 精确 → name 包含，命中返回本体 id。"""
    with graph.session() as s:
        eid = s.run("MATCH (n:Entity {id: $id}) RETURN n.id AS id LIMIT 1",
                    id=f"{cls}:{slug}").single()
        if eid:
            return eid["id"]
        if name:
            row = s.run("MATCH (n:Entity) WHERE n.class=$cls AND (n.name=$name OR n.name CONTAINS $name)"
                    " RETURN n.id AS id LIMIT 1", cls=cls, name=name).single()
            if row:
                return row["id"]
    return None


def main() -> None:
    llm = LLMClient()
    schema = load_schema()
    extractor = Extractor(schema, llm.batch_chat_json)
    triples = {(r["source"], r["predicate"], r["target"]) for r in schema["relations"]}
    graph = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
    pg = os.environ["ADKG_PG_DSN"]

    with psycopg.connect(pg) as conn, conn.cursor() as cur:
        cur.execute("SELECT doc_id, chunk_index, text FROM chunks"
                    " WHERE doc_id LIKE 'feishu:%' ORDER BY doc_id, chunk_index")
        chunks = cur.fetchall()
    print(f"待抽取 {len(chunks)} 块（飞书）")

    written = dropped_unaligned = 0
    for doc_id, idx, text in chunks:
        result = extractor.extract(text, {
            "source_type": "conversation", "source_id": f"aligned:{doc_id}#{idx}",
            "fetched_at": "2026-10-19T00:00:00+08:00"})
        aligned_rels = []
        for rel in result.relations:
            src_cls, _, src_slug = rel.source.partition(":")
            dst_cls, _, dst_slug = rel.target.partition(":")
            src = align(graph, src_cls, src_slug, "") or _align_by_mention(graph, rel.source, text)
            dst = align(graph, dst_cls, dst_slug, "") or _align_by_mention(graph, rel.target, text)
            if src and dst and (src.split(":")[0], rel.predicate,
                                dst.split(":")[0]) in triples:
                rel.source, rel.target = src, dst
                aligned_rels.append(rel)
            else:
                dropped_unaligned += 1
        graph.upsert_relations(aligned_rels)
        written += len(aligned_rels)
    print(f"对齐写入 {written} 条关系；未对齐丢弃 {dropped_unaligned} 条（实体不在图中）")
    print(f"图规模：{graph.counts()}")
    graph.close()


def _align_by_mention(graph, raw_id: str, text: str) -> str | None:
    """裸 slug（creative_992 / G-01 / B04）在文本中出现才认，防 LLM 编造。"""
    slug = raw_id.split(":")[-1]
    if slug and slug in text:
        with graph.session() as s:
            row = s.run("MATCH (n:Entity) WHERE n.id ENDS WITH $suffix RETURN n.id AS id LIMIT 1",
                        suffix=f":{slug}").single()
            if row:
                return row["id"]
    return None


if __name__ == "__main__":
    main()
