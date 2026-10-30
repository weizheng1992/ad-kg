"""agent 场景数值锚点重算（wayfinder 图「agent 真实化评测」T1）。

协议与 recalc_golden.py 一致：dry-run 出 diff、--yes 落盘、幂等；只动带
anchor 字段的场景——锚点种类显式声明（{"kind": ...}）而非问句启发式，新题型
要新锚先在此登记。聚合口径复用 metrics.agg_expr + NOT unmatched（与 golden
重算同源，改口径只动 metrics.py 一处）；窗口语义复用 text2sql._window_of。

    uv run python eval/recalc_agent.py        # dry-run：只展示 diff 不落盘
    uv run python eval/recalc_agent.py --yes  # 确认 diff 后写回场景文件
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

import psycopg  # noqa: E402

from adkg.retrieval import text2sql  # noqa: E402
from adkg.retrieval.metrics import agg_expr  # noqa: E402

SCENARIOS = ROOT / "eval" / "agent_scenarios.jsonl"


def anchor_window_top_cpa(cur, sc: dict) -> dict | None:
    """窗口 top CPA（成本型=汇总比降序，HAVING 与 top_metric 模板同值）——
    must_entities/must_numbers 换库值；points 语义句由题作者维护不动。"""
    w = text2sql._window_of(sc["question"])
    if not w:
        return None
    cur.execute(f"SELECT creative_id, {agg_expr('cpa')} AS cpa FROM unified_metrics"
                " WHERE NOT unmatched AND date BETWEEN %(a)s AND %(b)s"
                " GROUP BY 1 HAVING count(DISTINCT date) >= 3"
                " ORDER BY 2 DESC LIMIT 1", {"a": w[0], "b": w[1]})
    row = cur.fetchone()
    if not row or row[1] is None:
        return None
    return {"must_entities": [row[0]], "must_numbers": [str(round(Decimal(row[1]), 2))]}


def anchor_creative_cpa(cur, sc: dict) -> dict | None:
    """单素材整体汇总比 CPA（{"kind":"creative_cpa","creative_id": ...}）。"""
    cid = str((sc.get("anchor") or {}).get("creative_id") or "")
    if not cid.startswith("Creative:"):
        return None
    cur.execute(f"SELECT {agg_expr('cpa')} AS cpa FROM unified_metrics"
                " WHERE NOT unmatched AND creative_id = %(id)s", {"id": cid})
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return {"must_numbers": [str(round(Decimal(row[0]), 2))]}


def anchor_platform_cost(cur, sc: dict) -> dict | None:
    """各平台消耗合计（matched sum(cost)，整数形态同 golden）；window=auto 时
    从问句取窗（T3：上月平台拆分）。"""
    spec = sc.get("anchor") or {}
    where, params = "WHERE NOT unmatched", {}
    if spec.get("window") == "auto":
        w = text2sql._window_of(sc["question"])
        if w:
            where += " AND date BETWEEN %(a)s AND %(b)s"
            params = {"a": w[0], "b": w[1]}
    cur.execute(f"SELECT platform::text AS p, round(sum(cost)::numeric, 0) AS c"
                f" FROM unified_metrics {where} GROUP BY 1 ORDER BY 1", params)
    rows = cur.fetchall()
    if not rows:
        return None
    suffix = "（matched 口径）" if not params else f"（{params['a']}~{params['b']} 窗）"
    return {"points": [f"{p} 合计 ≈ {int(c)}{suffix}" for p, c in rows]}


def anchor_platform_metric(cur, sc: dict) -> dict | None:
    """单平台指标聚合均值（T3）：{"kind","metric","platform","window":"auto"?}——
    agg_expr 单源，平台+窗口过滤（G09「抖音平台平均 CTR」同族）。"""
    spec = sc.get("anchor") or {}
    metric, platform = str(spec.get("metric") or ""), str(spec.get("platform") or "")
    if not metric or not platform:
        return None
    where, params = "WHERE NOT unmatched AND platform = %(p)s", {"p": platform}
    if spec.get("window") == "auto":
        w = text2sql._window_of(sc["question"])
        if w:
            where += " AND date BETWEEN %(a)s AND %(b)s"
            params.update({"a": w[0], "b": w[1]})
    cur.execute(f"SELECT {agg_expr(metric)} FROM unified_metrics {where}", params)
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return {"must_numbers": [str(round(Decimal(row[0]), 2))]}


def anchor_window_top_metric(cur, sc: dict) -> dict | None:
    """泛化窗口 top（T3）：{"kind","metric","order":"desc|asc","platform"?}——
    口径同 window_top_cpa（_window_of + HAVING≥3），metric 走 agg_expr 单源，
    order=desc 取最高（ctr 最好/cpa 最差），asc 取最低（成本型"最好"=越低越好）；
    platform 过滤可选（"小红书那边"类问法的库值真值）。"""
    spec = sc.get("anchor") or {}
    metric, order = str(spec.get("metric") or ""), str(spec.get("order") or "desc")
    if not metric or order not in ("desc", "asc"):
        return None
    w = text2sql._window_of(sc["question"])
    if not w:
        return None
    platform = spec.get("platform")
    where = "WHERE NOT unmatched AND date BETWEEN %(a)s AND %(b)s"
    if platform:
        where += " AND platform = %(p)s"
    cur.execute(f"SELECT creative_id, {agg_expr(metric)} AS v FROM unified_metrics"
                f" {where} GROUP BY 1 HAVING count(DISTINCT date) >= 3"
                f" ORDER BY 2 {order.upper()} LIMIT 1",
                {"a": w[0], "b": w[1], "p": platform})
    row = cur.fetchone()
    if not row or row[1] is None:
        return None
    return {"must_entities": [row[0]], "must_numbers": [str(round(Decimal(row[1]), 2))]}


def anchor_sum_metric(cur, sc: dict) -> dict | None:
    """和值锚（T3）：{"kind","metrics":[...],"window":"auto"?}——matched 全量
    sum(metric)；window=auto 时从问句取窗（_window_of，无窗词则全量）。
    多指标按声明顺序落 must_numbers。"""
    spec = sc.get("anchor") or {}
    metrics = spec.get("metrics") or []
    if not metrics:
        return None
    where, params = "WHERE NOT unmatched", {}
    if spec.get("window") == "auto":
        w = text2sql._window_of(sc["question"])
        if w:
            where += " AND date BETWEEN %(a)s AND %(b)s"
            params = {"a": w[0], "b": w[1]}
    nums = []
    for m in metrics:
        cur.execute(f"SELECT sum({m}) FROM unified_metrics {where}", params)
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        nums.append(str(round(Decimal(row[0]), 0)))
    return {"must_numbers": nums}


ANCHORS = {"window_top_cpa": anchor_window_top_cpa,
           "creative_cpa": anchor_creative_cpa,
           "platform_cost": anchor_platform_cost,
           "window_top_metric": anchor_window_top_metric,
           "sum_metric": anchor_sum_metric,
           "platform_metric": anchor_platform_metric}


def main() -> None:
    ap = argparse.ArgumentParser(description="agent 场景数值锚点重算")
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--yes", action="store_true", help="确认落盘（缺省 dry-run 只展示 diff）")
    args = ap.parse_args()

    rows = [json.loads(line) for line in
            args.scenarios.read_text(encoding="utf-8").splitlines() if line.strip()]
    changes: list[tuple[dict, dict]] = []
    with psycopg.connect(os.environ["ADKG_PG_RO_DSN"]) as conn, conn.cursor() as cur:
        for sc in rows:
            kind = (sc.get("anchor") or {}).get("kind")
            if not kind:
                continue                          # 无锚场景（casegen/纯语义）原样跳过
            fn = ANCHORS.get(kind)
            if fn is None:
                sys.exit(f"{sc['id']} 未知锚点种类 {kind}（已登记：{sorted(ANCHORS)}）——"
                         "新锚先在 ANCHORS 登记，口径不许散抄")
            upd = fn(cur, sc)
            if not upd:
                continue
            new_ans = {**sc.get("expected_answer", {}), **upd}
            if new_ans != sc.get("expected_answer", {}):
                changes.append((sc, new_ans))

    if not changes:
        print(f"场景 {len(rows)} 条：带锚场景与当前库一致零变更"
              f"（{'已确认' if args.yes else 'dry-run'}，无落盘必要）")
        return

    print(f"场景 {len(rows)} 条，{len(changes)} 条锚点漂移：\n")
    for sc, new_ans in changes:
        old = sc.get("expected_answer", {})
        print(f"  {sc['id']} [{sc['type']}] {sc['question']}")
        for k in ("points", "must_entities", "must_numbers"):
            if new_ans.get(k) != old.get(k):
                print(f"    {k}: {old.get(k)}\n      → {new_ans.get(k)}")

    if not args.yes:
        print("\ndry-run 未落盘；确认后加 --yes 写回场景文件")
        return
    for sc, new_ans in changes:
        sc["expected_answer"] = new_ans
    args.scenarios.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"\n已写回 {args.scenarios}（{len(changes)} 条）——回归验证："
          "uv run python eval/agent_eval.py")


if __name__ == "__main__":
    main()
