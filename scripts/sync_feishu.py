"""飞书云文档增量同步（Phase 2b）：按 revision 入库，新版本 supersedes 旧版本（§7.2）。

用法：uv run python scripts/sync_feishu.py <doc_token> [<doc_token> ...]
  或在 .env 配 FEISHU_DOCS=token1,token2 后直接运行

每篇文档：raw 落盘 → chunk 入 PG（doc_id 带 revision，历史版本共存不删）
→ 图里 DocVersion 节点 + supersedes 指向上一版。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from adkg.connectors.feishu import FeishuConnector           # noqa: E402
from adkg.models import Entity, Provenance, Relation         # noqa: E402
from adkg.pipeline.run import run_docs                       # noqa: E402
from adkg.store.graph import GraphStore                      # noqa: E402
from adkg.store.provenance import TraceStore                 # noqa: E402
from adkg.store.raw import RawStore                          # noqa: E402
from adkg.store.vector import VectorStore                    # noqa: E402


def upsert_docversions(graph: GraphStore, records) -> int:
    """为每篇文档建 DocVersion 节点，supersedes 指向图里已有的最新版。"""
    created = 0
    with graph.session() as s:
        for r in records:
            token = r.provenance.source_id.split("feishu:doc:")[1]
            rev = r.provenance.version or "0"
            dv_id = f"DocVersion:{token}@{rev}"
            prev = s.run(
                "MATCH (d:Entity) WHERE d.class='DocVersion' AND d.token = $token"
                " AND d.id <> $id RETURN d.id AS id ORDER BY d.revision DESC LIMIT 1",
                token=token, id=dv_id).single()
            props = {"token": token, "revision": rev}
            if r.provenance.source_url:
                props["url"] = r.provenance.source_url
            graph.upsert_entities([Entity(entity_class="DocVersion", entity_id=dv_id,
                                          props=props, provenance=r.provenance)])
            if prev:
                graph.upsert_relations([Relation(
                    source=dv_id, predicate="supersedes", target=prev["id"],
                    provenance=r.provenance)])
            created += 1
    return created


def main() -> None:
    tokens = sys.argv[1:] or [t.strip() for t in os.environ.get("FEISHU_DOCS", "").split(",") if t.strip()]
    if not tokens:
        sys.exit("用法：sync_feishu.py <doc_token>... 或在 .env 配 FEISHU_DOCS")

    conn = FeishuConnector(os.environ["FEISHU_APP_ID"], os.environ["FEISHU_APP_SECRET"], tokens)
    try:
        records = list(conn.fetch())
    except RuntimeError as e:
        sys.exit(f"{e}\n\n上线前置清单（飞书开放平台 → 你的应用）：\n"
                 "  1. 权限管理：开通「查看新版文档」docx:document:readonly（或云空间只读）\n"
                 "  2. 版本管理与发布：创建版本并发布\n"
                 "  3. 把目标文档共享给应用（文档右上角 …→ 添加文档应用）\n"
                 "  完成后重跑本脚本。")
    if not records:
        sys.exit("没有可同步的文档（空文档或 token 无效）")

    pg = os.environ["ADKG_PG_DSN"]
    graph = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
    stats = run_docs(_Iter(records), RawStore(ROOT / "data" / "raw"),
                     VectorStore(pg), graph, TraceStore(pg),
                     extractor=None, embed_fn=None)
    n_dv = upsert_docversions(graph, records)
    print(f"飞书同步：{stats.docs} 篇 → {stats.chunks} 块；DocVersion {n_dv} 个（含 supersedes 链）")
    print(f"对账：{graph.counts()}")            # 版本链写入后再对账
    graph.close()


class _Iter:
    def __init__(self, records): self.records = records

    def fetch(self): yield from self.records


if __name__ == "__main__":
    main()
