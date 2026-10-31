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
from adkg.retrieval.metrics import STAT_HAVING, agg_expr  # noqa: E402
from eval.common import (apply_writeback, read_jsonl, show_changes)  # noqa: E402

SCENARIOS = ROOT / "eval" / "agent_scenarios.jsonl"


def _window_where(spec: dict, question: str) -> tuple[str, dict]:
    """window=="auto" → 从问句取窗（text2sql._window_of 单源）；无窗词则全量。
    返回 (where 追加片段, params)——平台/和值/均值三锚的取窗样板曾五处散抄。"""
    if spec.get("window") != "auto":
        return "", {}
    w = text2sql._window_of(question)
    if not w:
        return "", {}
    return " AND date BETWEEN %(a)s AND %(b)s", {"a": w[0], "b": w[1]}


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
    从问句取窗（T3：上月平台拆分）。points 与 must_numbers 同源双断言
    （T4 补：曾只填 points，A21 残留旧总量锚靠答案恰带总量侥幸过——收紧）。"""
    spec = sc.get("anchor") or {}
    wcond, params = _window_where(spec, sc["question"])
    where = "WHERE NOT unmatched" + wcond
    cur.execute(f"SELECT platform::text AS p, round(sum(cost)::numeric, 0) AS c"
                f" FROM unified_metrics {where} GROUP BY 1 ORDER BY 1", params)
    rows = cur.fetchall()
    if not rows:
        return None
    suffix = "（matched 口径）" if not params else f"（{params['a']}~{params['b']} 窗）"
    return {"points": [f"{p} 合计 ≈ {int(c)}{suffix}" for p, c in rows],
            "must_numbers": [str(int(c)) for _, c in rows]}


def anchor_platform_metric(cur, sc: dict) -> dict | None:
    """单平台指标聚合均值（T3）：{"kind","metric","platform","window":"auto"?}——
    agg_expr 单源，平台+窗口过滤（G09「抖音平台平均 CTR」同族）。"""
    spec = sc.get("anchor") or {}
    metric, platform = str(spec.get("metric") or ""), str(spec.get("platform") or "")
    if not metric or not platform:
        return None
    wcond, wparams = _window_where(spec, sc["question"])
    where = "WHERE NOT unmatched AND platform = %(p)s" + wcond
    params = {"p": platform, **wparams}
    cur.execute(f"SELECT {agg_expr(metric)} FROM unified_metrics {where}", params)
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return {"must_numbers": [str(round(Decimal(row[0]), 2))]}


def anchor_window_top_metric(cur, sc: dict) -> dict | None:
    """泛化窗口 top（T3）：{"kind","metric","order":"desc|asc","platform"?}——
    口径 = 原 window_top_cpa 特例（已并入，_window_of + STAT_HAVING 同一价），metric 走 agg_expr 单源，
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
                f" {where} GROUP BY 1 {STAT_HAVING}"
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
    wcond, params = _window_where(spec, sc["question"])
    where = "WHERE NOT unmatched" + wcond
    nums = []
    for m in metrics:
        cur.execute(f"SELECT sum({m}) FROM unified_metrics {where}", params)
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        nums.append(str(round(Decimal(row[0]), 0)))
    return {"must_numbers": nums}


def _metric_expr(metric: str) -> str:
    """比率型走 agg_expr 单源；和值型（conversions/cost/clicks/impressions）sum。"""
    if metric in ("cpa", "ctr", "cvr", "cpm", "roi"):
        return agg_expr(metric)
    return f"sum({metric})"


def anchor_creative_metric(cur, sc: dict) -> dict | None:
    """素材级指标双边锚（T4 双实体对比）：{"kind","creatives":[...],"metric",
    "window":"auto"?}——多素材按声明顺序落 must_numbers；比率型 agg_expr、
    和值型 sum（_metric_expr 单源）。"""
    spec = sc.get("anchor") or {}
    metric = str(spec.get("metric") or "cpa")
    ids = [c for c in (spec.get("creatives") or []) if str(c).startswith("Creative:")]
    if not ids:
        return None
    wcond, params = _window_where(spec, sc["question"])
    where = "WHERE NOT unmatched AND creative_id = %(id)s" + wcond
    nums = []
    for cid in ids:
        cur.execute(f"SELECT {_metric_expr(metric)} FROM unified_metrics {where}",
                    {**params, "id": cid})
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        nums.append(str(round(Decimal(row[0]), 2)))
    return {"must_numbers": nums}


def anchor_platform_metric_multi(cur, sc: dict) -> dict | None:
    """平台级指标双边锚（T4 双平台对比）：{"kind","platforms":[...],"metric",
    "window":"auto"?}——多平台按声明顺序落 must_numbers（单平台特例用
    platform_metric，双份形状曾合并考虑，读法不同留两 kind）。"""
    spec = sc.get("anchor") or {}
    metric = str(spec.get("metric") or "")
    platforms = [p for p in (spec.get("platforms") or []) if p]
    if not metric or not platforms:
        return None
    wcond, params = _window_where(spec, sc["question"])
    where = "WHERE NOT unmatched AND platform = %(p)s" + wcond
    nums = []
    for p in platforms:
        cur.execute(f"SELECT {_metric_expr(metric)} FROM unified_metrics {where}",
                    {**params, "p": p})
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        nums.append(str(round(Decimal(row[0]), 2)))
    return {"must_numbers": nums}


def anchor_period_sum(cur, sc: dict) -> dict | None:
    """双期间和值锚（T4 双期间对比）：{"kind","metric","windows":["2026-09",...]}——
    显式月份（_window_of 不认"上上月"，题面点名月份；月界=自然月，月内逐日
    覆盖口径与 window_top 的 STAT_HAVING 语义不同——期间和值不设 HAVING）。"""
    import calendar
    spec = sc.get("anchor") or {}
    metric, months = str(spec.get("metric") or ""), (spec.get("windows") or [])
    if not metric or not months:
        return None
    nums = []
    for m in months:
        y, mo = int(str(m)[:4]), int(str(m)[5:7])
        last = calendar.monthrange(y, mo)[1]
        cur.execute(f"SELECT sum({metric}) FROM unified_metrics"
                    " WHERE NOT unmatched AND date BETWEEN %(a)s AND %(b)s",
                    {"a": f"{y:04d}-{mo:02d}-01", "b": f"{y:04d}-{mo:02d}-{last:02d}"})
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        nums.append(str(round(Decimal(row[0]), 0)))
    return {"must_numbers": nums}


def anchor_brand_metric(cur, sc: dict) -> dict | None:
    """品牌级指标双边锚（T4 双品牌对比）：{"kind","brands":[...],"metric",
    "window":"auto"?}——unified_metrics 自带 brand_id（brand 粒度 native 可达；
    双实体素材级对比不可达——缺口⑥，2026-10-31 A24 原题实证后改写至此）。"""
    spec = sc.get("anchor") or {}
    metric = str(spec.get("metric") or "")
    brands = [b for b in (spec.get("brands") or []) if str(b).startswith("Brand:")]
    if not metric or not brands:
        return None
    wcond, params = _window_where(spec, sc["question"])
    where = "WHERE NOT unmatched AND brand_id = %(b)s" + wcond
    nums = []
    for b in brands:
        cur.execute(f"SELECT {_metric_expr(metric)} FROM unified_metrics {where}",
                    {**params, "b": b})
        row = cur.fetchone()
        if not row or row[0] is None:
            return None
        nums.append(str(round(Decimal(row[0]), 0)))
    return {"must_numbers": nums}


# window_top_cpa 已并入 window_top_metric（metric=cpa/order=desc 全同形——A01 已迁，
# 2026-10-31 收口：特例 kind 曾与泛化版双份维护）
ANCHORS = {"creative_cpa": anchor_creative_cpa,
           "platform_cost": anchor_platform_cost,
           "window_top_metric": anchor_window_top_metric,
           "sum_metric": anchor_sum_metric,
           "platform_metric": anchor_platform_metric,
           "creative_metric": anchor_creative_metric,
           "platform_metric_multi": anchor_platform_metric_multi,
           "period_sum": anchor_period_sum,
           "brand_metric": anchor_brand_metric}


def main() -> None:
    ap = argparse.ArgumentParser(description="agent 场景数值锚点重算")
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--yes", action="store_true", help="确认落盘（缺省 dry-run 只展示 diff）")
    args = ap.parse_args()

    rows = read_jsonl(args.scenarios)
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
    show_changes(changes)

    if not args.yes:
        print("\ndry-run 未落盘；确认后加 --yes 写回场景文件")
        return
    n = apply_writeback(rows, changes, args.scenarios)
    print(f"\n已写回 {args.scenarios}（{n} 条）——回归验证："
          "HF_HUB_OFFLINE=1 uv run python eval/agent_eval.py")


if __name__ == "__main__":
    main()
