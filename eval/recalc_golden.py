"""golden set 库值锚点重算（老余项④，2026-10-27）。

背景：期望里的库值锚点（CPA 21.59、平台合计 558079、案例/规范实体 ID）此前
靠手工跟库改——G32-34 曾因数据形状变更漏改、漂移 2~3 倍翻车。本脚本按当前库
（PG / Neo4j 直查）重算锚点生成新期望，杜绝手工漏改。

使用时机：种子扩容 / 口径调整 / 数据重生成后跑一次；日常回归仍用 run_eval.py
对拍（评测对拍「系统输出 vs 期望」，期望只在库值变了才动，不为过评测而重算）。

    uv run python eval/recalc_golden.py        # dry-run：只展示 diff 不落盘
    uv run python eval/recalc_golden.py --yes  # 确认 diff 后写回 golden_set.jsonl

口径防漂移：聚合口径（汇总比分子分母）复用 metrics.agg_expr、窗口语义（上月=
自然月）复用 text2sql._window_of、点名素材解析复用 _named_creative_of——脚本
不自造口径，改口径只动 metrics.py 一处，本脚本自动跟随。窗口 top 题的
HAVING >=3 与 top_metric 模板同值（text2sql 侧改阈值需同步此处）。

只动含既有锚点的期望项（must_numbers 非空 / points 带 ≈ 数字 / 实体锚），纯
语义期望（越权题 / 操作题 / 概念题）不匹配任何重算器、原样跳过。幂等：当前库
下重跑零 diff。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

import psycopg  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402

from adkg.retrieval import text2sql  # noqa: E402
from adkg.retrieval.metrics import STAT_HAVING, agg_expr  # noqa: E402
from eval.common import apply_writeback, read_jsonl, show_changes  # noqa: E402

GOLDEN = ROOT / "eval" / "golden_set.jsonl"

# 锚点 token 形态（points 文本内替换用，与 §12.5 ID 规则一致）
_CASE_ID = r"(?:Case:)?C-\d{4}-\d{3}"
_BRAND_ID = r"Brand:B\d+"


def _has_number_anchor(item: dict) -> bool:
    """该题期望是否已带数值锚（must_numbers 或 points 里的 ≈ 数字）——只有
    本来就有数字锚的题才进数值重算，防把 G07「两行 cost 合计」这类纯语义
    要点升级成随库变的数字锚（升级=行为变更，须人工改题而不是脚本代劳）。"""
    ans = item.get("expected_answer", {})
    if ans.get("must_numbers"):
        return True
    return any(re.search(r"≈\s*\d+(?:\.\d+)?", p) for p in ans.get("points", []))


def _take(existing: list, fresh: list) -> list:
    """实体锚保持既有数量：库值重算只换值不扩面（must 判据是 any 命中，
    扩面会静默放宽断言）。fresh 需调用方先确定性排序。"""
    return fresh[:len(existing)] if existing else []


# ---------------------------------------------------------------- PG 数值锚点

def recalc_creative_cpa(cur, item: dict) -> dict | None:
    """单素材整体汇总比 CPA（fact：G08/G31-35）。证据形态按 (素材,平台) 分行
    （entity_metrics 模板），期望真值是素材整体上卷单值——评测锚定数据真值
    而非系统证据形状。points 只换 ≈ 后的数字，句式不动。"""
    slug = text2sql._named_creative_of(item["question"])
    if not slug or "cpa" not in item["question"].lower():
        return None
    cur.execute(f"SELECT {agg_expr('cpa')} AS cpa FROM unified_metrics"
                " WHERE NOT unmatched AND creative_id = %(id)s",
                {"id": f"Creative:{slug}"})
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    val = round(Decimal(row[0]), 2)                     # 期望文本形态 2 位小数
    ans = item["expected_answer"]
    upd = {"points": [re.sub(r"≈\s*[\d.]+", f"≈ {val}", p) for p in ans.get("points", [])]}
    if ans.get("must_numbers"):
        upd["must_numbers"] = [str(val)]
    return upd


def recalc_window_top(cur, item: dict) -> dict | None:
    """窗口 top CPA（fact：G06「上月 CPA 最差」）——最差+成本型=汇总比 CPA
    降序（§六方向反转），窗口/HAVING 与 top_metric 模板同口径。"""
    q = item["question"]
    if not any(w in q for w in ("最差", "最好", "最高")) or "cpa" not in q.lower():
        return None
    w = text2sql._window_of(q)
    if not w:
        return None                                     # 无窗口词的题不属本族
    cur.execute(f"SELECT creative_id, {agg_expr('cpa')} AS cpa FROM unified_metrics"
                " WHERE NOT unmatched AND date BETWEEN %(a)s AND %(b)s"
                f" GROUP BY 1 {STAT_HAVING}"
                " ORDER BY 2 DESC LIMIT 1", {"a": w[0], "b": w[1]})
    row = cur.fetchone()
    if not row or row[1] is None:
        return None
    val = round(Decimal(row[1]), 2)
    slug = row[0].split(":", 1)[1]
    m = re.search(r"上月|本月|上周|本周|昨天|今天|最近|过去", q)
    word = m.group(0) if m else f"{w[0]}~{w[1]} "       # 绝对年月窗等：退化用区间
    return {"must_entities": [row[0]], "must_numbers": [str(val)],
            "points": [f"素材清单按 cpa 汇总比降序，top1 = {slug}（{word}窗口 cpa {val}）"]}


def recalc_platform_cost(cur, item: dict) -> dict | None:
    """各平台消耗合计（fact：G36）——matched 全量 sum(cost) 按平台，整数形态
    与既有期望一致。平台集合随库变，points 整族重生成。"""
    q = item["question"]
    if "平台" not in q or not any(w in q for w in ("消耗", "成本", "花费")):
        return None
    cur.execute("SELECT platform::text AS p, round(sum(cost)::numeric, 0) AS c"
                " FROM unified_metrics WHERE NOT unmatched GROUP BY 1 ORDER BY 1")
    rows = cur.fetchall()
    if not rows:
        return None
    return {"points": [f"{p} 合计 ≈ {int(c)}（matched 口径）" for p, c in rows]}


# ---------------------------------------------------------------- Neo4j 实体锚点

def recalc_person_cases(s, item: dict) -> dict | None:
    """「{name}负责哪些 Case」——must_entities 换库内真锚（排序取前 N 保数量）。"""
    m = re.match(r"(.+?)负责哪些 Case", item["question"])
    if not m:
        return None
    ans = item["expected_answer"]
    if not ans.get("must_entities"):
        return None
    rows = s.run("MATCH (p:Entity {name: $n})-[:responsible_for]->(c:Entity)"
                 " RETURN c.id AS c ORDER BY c", {"n": m.group(1)}).data()
    if not rows:
        return None
    fresh = [r["c"] for r in rows]
    must = _take(ans["must_entities"], fresh)
    upd = {"must_entities": must}
    if ans.get("points"):
        # points 回显的案例 ID 换首锚；Case: 前缀按原 token 形态保留（句式不动）
        anchor = must[0].split(":", 1)[-1]
        upd["points"] = [re.sub(r"(Case:)?(C-\d{4}-\d{3})",
                                lambda m: (m.group(1) or "") + anchor, p)
                         for p in ans["points"]]
    return upd


def recalc_case_brand(s, item: dict) -> dict | None:
    """「Case:{id} 属于哪个品牌，有哪些计划」——points 品牌锚替换；must_entities
    里若锚计划（G03）按 belongs_to 重算。"""
    m = re.search(r"(Case:C-\d{4}-\d{3}) 属于哪个品牌", item["question"])
    if not m:
        return None
    ans = item["expected_answer"]
    brand = s.run("MATCH (c:Entity {id: $id})-[:for_brand]->(b:Entity)"
                  " RETURN b.id AS b ORDER BY b", {"id": m.group(1)}).data()
    plans = s.run("MATCH (cp:Entity)-[:belongs_to]->(c:Entity {id: $id})"
                  " RETURN cp.id AS cp ORDER BY cp", {"id": m.group(1)}).data()
    if not brand:
        return None
    upd = {}
    if ans.get("points"):
        upd["points"] = [re.sub(_BRAND_ID, brand[0]["b"], p) for p in ans["points"]]
    if ans.get("must_entities") and plans:
        must = _take([e for e in ans["must_entities"] if e.startswith("Campaign:")],
                     [r["cp"] for r in plans])
        if must:
            kept = [e for e in ans["must_entities"] if not e.startswith("Campaign:")]
            upd["must_entities"] = kept + must
    return upd


def recalc_creative_violates(s, item: dict) -> dict | None:
    """「{slug} 违反了哪些规范」——violates 目标按图重算。"""
    if "违反了哪些规范" not in item["question"]:
        return None
    ans = item["expected_answer"]
    if not ans.get("must_entities"):
        return None
    slug = text2sql._named_creative_of(item["question"])    # 两种叫法：creative_992 / C-…-cr1
    if not slug:
        return None
    cid = f"Creative:{slug}"
    rows = s.run("MATCH (c:Entity {id: $id})-[:violates]->(g:Entity)"
                 " RETURN g.id AS g ORDER BY g", {"id": cid}).data()
    if not rows:
        return None
    return {"must_entities": _take(ans["must_entities"], [r["g"] for r in rows])}


def recalc_product_attr(s, item: dict) -> dict | None:
    """「…目标人群…」（G37/38）——Product.target_age 属性值随本体/种子变。"""
    ans = item.get("expected_answer", {})
    if not any("target_age" in p for p in ans.get("points", [])):
        return None
    pid = next((e for e in ans.get("must_entities", []) if e.startswith("Product:")), None)
    if not pid:
        return None
    rows = s.run("MATCH (p:Entity {id: $id}) RETURN p.target_age AS ta", {"id": pid}).data()
    if not rows or not rows[0]["ta"]:
        return None
    ta = rows[0]["ta"]
    return {"points": [re.sub(r"target_age \d+-\d+", f"target_age {ta}", p)
                       for p in ans["points"]]}


# ---------------------------------------------------------------- 主流程

PG_RECALCERS = (recalc_creative_cpa, recalc_window_top, recalc_platform_cost)
GRAPH_RECALCERS = (recalc_person_cases, recalc_case_brand, recalc_creative_violates,
                   recalc_product_attr)


def recalc_item(cur, s, item: dict) -> dict | None:
    """依序试各重算器，首个命中即止；返回 expected_answer 的字段级更新。
    数值族前提：已有数字锚（防语义题升级）；实体族无此前提（锚本身就是要刷新的）。"""
    if _has_number_anchor(item):
        for fn in PG_RECALCERS:
            upd = fn(cur, item)
            if upd:
                return upd
    for fn in GRAPH_RECALCERS:
        upd = fn(s, item)
        if upd:
            return upd
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description="golden set 库值锚点重算")
    ap.add_argument("--yes", action="store_true", help="确认落盘（缺省 dry-run 只展示 diff）")
    args = ap.parse_args()

    items = read_jsonl(GOLDEN)
    graph = GraphDatabase.driver(os.environ["ADKG_NEO4J_URI"],
                                 auth=(os.environ["ADKG_NEO4J_USER"],
                                       os.environ["ADKG_NEO4J_PASSWORD"]))
    changes: list[tuple[dict, dict]] = []               # (原题, 新 expected_answer)
    recalced = 0
    with psycopg.connect(os.environ["ADKG_PG_RO_DSN"]) as conn, \
            conn.cursor() as cur, graph.session() as s:
        for it in items:
            upd = recalc_item(cur, s, it)
            if not upd:
                continue
            recalced += 1
            new_ans = {**it.get("expected_answer", {}), **upd}
            if new_ans != it.get("expected_answer", {}):
                changes.append((it, new_ans))

    graph.close()
    if not changes:
        print(f"golden {len(items)} 题：{recalced} 题锚点已按库重算、与当前库一致零变更，"
              f"其余纯语义不动（{'已确认' if args.yes else 'dry-run'}，无落盘必要）")
        return

    print(f"golden {len(items)} 题，{len(changes)} 题锚点漂移：\n")
    show_changes(changes)

    if not args.yes:
        print("\ndry-run 未落盘；确认后加 --yes 写回 golden_set.jsonl")
        return
    n = apply_writeback(items, changes, GOLDEN)
    print(f"\n已写回 {GOLDEN}（{n} 题）——回归验证：uv run python eval/run_eval.py")


if __name__ == "__main__":
    main()
