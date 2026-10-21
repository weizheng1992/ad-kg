"""飞书云文档增量同步（Phase 2b / §7.2 定时增量）：按 revision 入库，新版本 supersedes 旧版本。

用法：uv run python scripts/sync_feishu.py <doc_token> [<doc_token> ...]
  或在 .env 配 FEISHU_DOCS=token1,token2 后直接运行（launchd 定时跑同一入口）

每轮先查 ingest_job 幂等：(source_id, version) 两段都已 done 的 revision 直接跳过；
新 revision 才走 raw 落盘 → chunk 入 PG（doc_id 不带 revision，冲突更新，检索面恒最新版）
→ 本地嵌入当场生成 → 图里 DocVersion 节点 + supersedes 指向上一版
（历史版本在 raw 的 @rev 键与 DocVersion 链里，不删除）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from adkg.connectors.feishu import FeishuConnector           # noqa: E402
from adkg.llm import LLMClient                               # noqa: E402
from adkg.models import Entity, Relation                     # noqa: E402
from adkg.pipeline.run import run_docs, version_of           # noqa: E402
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
    folders = [f.strip() for f in os.environ.get("FEISHU_FOLDER", "").split(",") if f.strip()]
    if not tokens and not folders:
        sys.exit("用法：sync_feishu.py <doc_token>... 或在 .env 配 FEISHU_DOCS / FEISHU_FOLDER"
                 "（共享文件夹模式：应用加为文件夹协作者，自动列目录逐篇同步）")

    conn = FeishuConnector(os.environ["FEISHU_APP_ID"], os.environ["FEISHU_APP_SECRET"],
                           tokens, folder_tokens=folders)
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
    trace = TraceStore(pg)
    vector = VectorStore(pg)
    # 跳过判据：ingest_job 双 done 且 chunks 仍有该文档块——自愈 TRUNCATE 后
    # ingest_job 残留 done、检索面已丢的错位（此时自动重灌）
    pending = [r for r in records
               if not (trace.job_done(r.provenance.source_id, version_of(r))
                       and vector.count_by_doc(r.provenance.source_id) > 0)]
    skipped = len(records) - len(pending)
    if not pending:
        print(f"飞书同步：{len(records)} 篇全部为已同步版本（幂等跳过），本轮无操作")
        graph.close()
        return
    stats = run_docs(_Iter(pending), RawStore(ROOT / "data" / "raw"),
                     VectorStore(pg), graph, trace,
                     extractor=None, embed_fn=LLMClient().embed)
    n_dv = upsert_docversions(graph, pending)
    print(f"飞书同步：新增 {stats.docs}/{len(records)} 篇（跳过 {skipped} 篇已同步版本）"
          f"→ {stats.chunks} 块；DocVersion {n_dv} 个（含 supersedes 链）")
    print(f"对账：{graph.counts()}")            # 版本链写入后再对账
    graph.close()


class _Iter:
    def __init__(self, records): self.records = records

    def fetch(self): yield from self.records


if __name__ == "__main__":
    main()
