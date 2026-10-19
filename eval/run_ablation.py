"""消融基线（README §10.3 / §1.2）：multi_hop 增益归因于图谱。

三配置对比（同一 plan、同一嵌入）：
- vec_only      ≈ 双路 RAG 的检索路（向量）
- vec_sql       ≈ 双路 RAG + Text2SQL（最便宜的拼装方案）
- full          = AdKG 全路（+ 图谱）
判据：must_entities 命中（硬）+ judge 要点（glm-4-flash，温度 0）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from adkg.guards.permission import PermissionPlanner          # noqa: E402
from adkg.llm import LLMClient                                # noqa: E402
from adkg.retrieval import text2sql, vector_search            # noqa: E402
from adkg.store.graph import GraphStore                       # noqa: E402
from adkg.retrieval.graph_search import search as graph_search  # noqa: E402
from eval.judge import judge_item                             # noqa: E402


def run_config(name: str, item: dict, plan, env, llm, graph) -> dict:
    q = item["question"]
    evidence: list[dict] = []
    if name in ("vec_only", "vec_sql"):
        evidence += vector_search.search(q, plan, env["ADKG_PG_DSN"],
                                         embed_fn=llm.embed)["evidence"]
    if name == "vec_sql":
        evidence += text2sql.run(q, plan, env["ADKG_PG_RO_DSN"])["evidence"]
    if name == "full":
        evidence += graph_search(q, plan, graph)["evidence"]
        evidence += text2sql.run(q, plan, env["ADKG_PG_RO_DSN"])["evidence"]
        evidence += vector_search.search(q, plan, env["ADKG_PG_DSN"],
                                         embed_fn=llm.embed)["evidence"]
    blob = json.dumps(evidence, ensure_ascii=False, default=str)
    must = item.get("expected_answer", {}).get("must_entities", [])
    hard = bool(evidence) and all(m in blob for m in must)
    points = item.get("expected_answer", {}).get("points", [])
    judged = judge_item(llm.batch_chat_json, q, points, evidence) if points else None
    return {"hard": hard, "judge": (judged or {}).get("verdict"),
            "evidence_n": len(evidence)}


def main() -> None:
    items = [json.loads(l) for l in (ROOT / "eval" / "golden_set.jsonl")
             .read_text(encoding="utf-8").splitlines() if l.strip()]
    multi_hop = [i for i in items if i["type"] == "multi_hop"]
    fact = [i for i in items if i["type"] == "fact"]

    env = dict(os.environ)
    llm = LLMClient()
    graph = GraphStore(env["ADKG_NEO4J_URI"], env["ADKG_NEO4J_USER"],
                       env["ADKG_NEO4J_PASSWORD"])
    planner = PermissionPlanner(ROOT / "ontology" / "permissions.yaml", graph=graph)
    plan = planner.plan("management")

    print(f"{'配置':<12}{'multi_hop 命中(硬/judge)':<24}{'fact 命中(硬/judge)'}")
    for name in ("vec_only", "vec_sql", "full"):
        stats = {}
        for subset_name, subset in (("multi_hop", multi_hop), ("fact", fact)):
            hard = judge = 0
            for item in subset:
                r = run_config(name, item, plan, env, llm, graph)
                hard += r["hard"]
                judge += 1 if r["judge"] else (1 if r["hard"] and not item.get(
                    "expected_answer", {}).get("points") else 0)
            stats[subset_name] = (hard, judge, len(subset))
        mh, fa = stats["multi_hop"], stats["fact"]
        print(f"{name:<12}{mh[0]}/{mh[2]} 硬 · {mh[1]}/{mh[2]} judge      "
              f"{fa[0]}/{fa[2]} 硬 · {fa[1]}/{fa[2]} judge")
    graph.close()


if __name__ == "__main__":
    main()
