"""从种子图与事实数据生成评测题（Phase 6 扩集至 50，multi_hop ≥15）。

答案由数据决定（从图/SQL 查询回填），避免手写过拟合；生成的题与手写 20 题
合并去重后写入 eval/golden_set.jsonl。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

GOLDEN = ROOT / "eval" / "golden_set.jsonl"


def gen_multi_hop(graph) -> list[dict]:
    out = []
    with graph.session() as s:
        # 模板 A：某人负责的案例（期望=图查询结果）
        for r in s.run("MATCH (p:Entity)-[:responsible_for]->(c:Entity)"
                       " RETURN p.id AS p, p.name AS name, collect(c.id) AS cases").data():
            if not r["name"] or len(r["cases"]) < 1:
                continue
            out.append({"type": "multi_hop",
                        "question": f"{r['name']}负责哪些 Case？",
                        "expected_routes": ["graph"], "must_hit": ["Person", "Case"],
                        "expected_answer": {"points": [f"案例清单（含 {r['cases'][0]}）"],
                                            "must_entities": r["cases"][:2], "must_numbers": []},
                        "notes": "gen；role=management", "data_window": "2025-01..2025-12"})
        # 模板 B：案例属于哪个品牌、有哪些计划
        for r in s.run(
                "MATCH (c:Entity)-[:for_brand]->(b:Entity)"
                "<-[:belongs_to|external_for]-(:Entity)"
                "MATCH (cp:Entity)-[:belongs_to]->(c)"
                " RETURN c.id AS c, b.id AS b, collect(DISTINCT cp.id)[..2] AS cps"
                " LIMIT 6").data():
            out.append({"type": "multi_hop",
                        "question": f"{r['c']} 属于哪个品牌，有哪些计划？",
                        "expected_routes": ["graph"], "must_hit": ["Case", "Brand"],
                        "expected_answer": {"points": [f"品牌 {r['b']}"]},
                        "notes": "gen；role=management", "data_window": "2025-01..2025-12"})
        # 模板 C：某素材违反了什么规范
        for r in s.run("MATCH (c:Entity)-[:violates]->(g:Entity)"
                       " RETURN c.id AS c, collect(g.id)[..2] AS gs LIMIT 5").data():
            out.append({"type": "multi_hop",
                        "question": f"{r['c'].split(':')[1]} 违反了哪些规范？",
                        "expected_routes": ["graph"], "must_hit": ["Creative", "Guideline"],
                        "expected_answer": {"points": ["violates 边清单"],
                                            "must_entities": r["gs"][:1]},
                        "notes": "gen；role=management", "data_window": "2025-01..2025-12"})
        # 模板 D：某品牌下有哪些案例（客户视角越权变体）
        for r in s.run("MATCH (b:Entity)<-[:for_brand]-(c:Entity)"
                       " WHERE b.class='Brand' RETURN b.id AS b, count(c) AS n").data():
            out.append({"type": "multi_hop",
                        "question": f"{r['b']} 品牌下有哪些案例？",
                        "expected_routes": ["graph"], "must_hit": ["Brand", "Case"],
                        "expected_answer": {"points": [f"该品牌案例（共 {r['n']} 个）"]},
                        "notes": "gen；role=management", "data_window": "2025-01..2025-12"})
    return out


def gen_fact(pg_dsn: str) -> list[dict]:
    out = []
    with psycopg.connect(pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT creative_id, round(avg(cpa)::numeric,1) FROM unified_metrics"
                    " WHERE NOT unmatched GROUP BY 1 HAVING count(*)>=5"
                    " ORDER BY 2 DESC LIMIT 5")
        for cid, cpa in cur.fetchall():
            out.append({"type": "fact",
                        "question": f"{cid.split(':')[1]} 的平均 CPA 是多少？",
                        "expected_routes": ["text2sql"], "must_hit": ["Creative"],
                        "expected_answer": {"points": [f"avg_cpa ≈ {cpa}"]},
                        "notes": "gen；role=management", "data_window": "2025-01..2025-12"})
        cur.execute("SELECT platform, round(sum(cost)::numeric,0) FROM unified_metrics"
                    " GROUP BY 1 ORDER BY 1")
        rows = cur.fetchall()
        if len(rows) >= 2:
            out.append({"type": "fact", "question": "各平台的消耗合计分别是多少？",
                        "expected_routes": ["text2sql"], "must_hit": ["Metric"],
                        "expected_answer": {"points": [f"{p} 合计 ≈ {c}" for p, c in rows]},
                        "notes": "gen；role=management", "data_window": "2025-01..2025-12"})
    return out


def main() -> None:
    graph = GraphDatabase.driver(os.environ["ADKG_NEO4J_URI"],
                                 auth=(os.environ["ADKG_NEO4J_USER"],
                                       os.environ["ADKG_NEO4J_PASSWORD"]))
    generated = gen_multi_hop(graph) + gen_fact(os.environ["ADKG_PG_DSN"])
    graph.close()

    handwritten = [json.loads(ln) for ln in GOLDEN.read_text(encoding="utf-8").splitlines() if ln.strip()]
    seen_q = {h["question"] for h in handwritten}
    fresh = [g for g in generated if g["question"] not in seen_q]

    # 配额：multi_hop 至少 15（现有手写 5 → 再生成 ≥10），总数补到 50
    mh_have = sum(1 for h in handwritten if h["type"] == "multi_hop")
    mh_pool = [g for g in fresh if g["type"] == "multi_hop"]
    fact_pool = [g for g in fresh if g["type"] == "fact"]
    need_mh = max(0, 15 - mh_have)
    take = mh_pool[:need_mh] + fact_pool[: max(0, 50 - len(handwritten) - need_mh)]

    merged = handwritten + [{**g, "id": f"G{len(handwritten) + i + 1:02d}"} for i, g in enumerate(take)]
    GOLDEN.write_text("\n".join(json.dumps(m, ensure_ascii=False) for m in merged) + "\n",
                      encoding="utf-8")
    from collections import Counter
    dist = Counter(m["type"] for m in merged)
    print(f"扩集完成：{len(merged)} 题，分布 {dict(dist)}（新增 {len(take)}）")


if __name__ == "__main__":
    main()
