"""agent 场景评测（README §12.3 agent 场景集 / wayfinder 图「agent 真实化评测」T1）。

与 run_eval.py（golden 单问一答打 /ask）互补的第二评测面：真实措辞场景打
/agent/chat ReAct 全链路——真实 LLM 多轮工具、真实角色权限，不 mock 不降级。

判据三件：
- judge 要点：复用 eval/judge.py，证据 = reply + trace 工具结果（agent 面无独立
  证据结构，工具轨迹就是证据）
- must_numbers 数值锚：容差 ±max(0.06, 1%) 同 golden；锚点重算走 recalc_agent.py
- 场景断言：casegen 走生命周期——draft 字段 → /ingest/case-commit → 图上落点
  （建号/关系/authority/别名）→ 清理不留脏数据（--keep 保留观察）

验收口径（图内拍板）：每型分别 ≥90% 且数值锚全中、连续 --rounds 轮全达标
（casegen 按断言全过计=100%）；降级（degraded）进报告清单不静默算过。
报告落 eval/runs/agent-{stamp}.json（gitignored）。

用法：
    HF_HUB_OFFLINE=1 uv run python eval/agent_eval.py                # 全部场景 2 轮
    uv run python eval/agent_eval.py --types stat,casegen --rounds 1  # 选型快跑
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from eval.judge import judge_item  # noqa: E402

load_dotenv(ROOT / ".env")

SCENARIOS = ROOT / "eval" / "agent_scenarios.jsonl"
AGENT_TYPES = {"query", "stat", "comparison", "casegen"}
GATE_RATE = 0.9                                     # 题型达标线（casegen 恒 1.0）
_CASE_ID = re.compile(r"^Case:C-\d{4}-\d{3}$")


def load(path: Path = SCENARIOS) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        missing = {"id", "type", "question", "role", "user"} - set(r)
        if missing:
            sys.exit(f"{r.get('id', '?')} 缺必填字段 {sorted(missing)}")
        if r["type"] not in AGENT_TYPES:
            sys.exit(f"{r['id']} 未知题型 {r['type']}（合法：{sorted(AGENT_TYPES)}）")
        if r["type"] == "casegen" and not isinstance(r.get("expect_draft"), dict):
            sys.exit(f"{r['id']} casegen 场景缺 expect_draft（brand_name/stage）")
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        sys.exit("场景 id 重复")
    return rows


# ------------------------------------------------------------------ 判据件

def num_ok(blob: str, must_numbers: list) -> bool:
    """数值硬断言（与 run_eval 同容差）：期望数字在文本里数值可达——
    容差 ±max(0.06, 1%)，四舍五入/整数化形态不误杀。"""
    if not must_numbers:
        return True
    found = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", blob)]
    return all(any(abs(f - float(n)) <= max(0.06, abs(float(n)) * 0.01) for f in found)
               for n in must_numbers)


def evidence_of(reply: str, trace: list[dict]) -> list[dict]:
    """agent 面证据 = reply + 工具结果；reply 窗口 1600（枚举型答案的品牌/案例清单
    可超 800，截短会造成"答案对但 judge 看不见"的评测者伪影——2026-10-30 A12 实弹）。"""
    evs = [{"ref": "agent:reply", "quote": reply[:1600]}]
    evs += [{"ref": f"tool:{i}:{t.get('tool')}", "quote": str(t.get("result") or "")[:600]}
            for i, t in enumerate(trace)]
    return evs


def degraded_of(trace: list[dict]) -> list[str]:
    """工具结果里的 degraded 清单（缺席路标注不静默）：能 parse 的结果抽 degraded
    字段——结果可能是数组（list_brands 等返回 JSON 列表），只对 dict 取字段。"""
    out: list[str] = []
    for t in trace:
        try:
            d = json.loads(t.get("result") or "{}")
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict) and d.get("degraded"):
            out.append(f"{t.get('tool')}:{d['degraded']}")
    return out


def draft_checks(case_draft: dict | None, expect: dict) -> dict[str, bool]:
    """casegen 第一段断言：草稿在场 + 关键字段符合期望（服务端已对齐/建号）。"""
    if not isinstance(case_draft, dict):
        return {"draft": False}
    checks: dict[str, bool] = {"draft": True}
    case = case_draft.get("case") or {}
    checks["case_id_format"] = bool(_CASE_ID.match(str(case.get("id") or "")))
    brand = case_draft.get("brand") or {}
    if expect.get("brand_name"):
        checks["brand"] = str(brand.get("name") or "").strip() == expect["brand_name"]
    if expect.get("stage"):
        checks["stage"] = (case.get("props") or {}).get("stage") == expect["stage"]
    return checks


# -------------------------------------------------------------- casegen 图断言

def _neo4j():
    from neo4j import GraphDatabase
    return GraphDatabase.driver(os.environ["ADKG_NEO4J_URI"],
                                auth=(os.environ["ADKG_NEO4J_USER"],
                                      os.environ["ADKG_NEO4J_PASSWORD"]))


def graph_checks(case_id: str, written: list[dict]) -> dict[str, bool]:
    """casegen 第二段断言：图上落点——全部 written 节点在场、authority 非空、
    案例关键关系按 schema 方向（for_brand/for_product=Case 出边；
    responsible_for=Person→Case 入边；has_product 是 Brand→Product 不在本断言）。"""
    ids = [w["id"] for w in written]
    classes = {w["id"].split(":", 1)[0] for w in written}
    with _neo4j().session() as s:
        nodes = s.run("MATCH (e:Entity) WHERE e.id IN $ids"
                      " RETURN e.id AS id, e.authority AS a", ids=ids).data()
        out_rels = s.run("MATCH (c:Entity {id:$cid})-[r]->(o:Entity)"
                         " RETURN type(r) AS t", cid=case_id).data()
        in_rels = s.run("MATCH (o:Entity)-[r]->(c:Entity {id:$cid})"
                        " RETURN type(r) AS t", cid=case_id).data()
    found = {n["id"] for n in nodes}
    out = {r["t"] for r in out_rels}
    inc = {r["t"] for r in in_rels}
    checks = {
        "nodes_written": set(ids) <= found,
        "authority_set": all(n.get("a") is not None for n in nodes),
        "rel_for_brand": "for_brand" in out,
    }
    if "Product" in classes:
        checks["rel_for_product"] = "for_product" in out
    if "Person" in classes:
        checks["rel_responsible"] = "responsible_for" in inc
    return checks


def alias_written(written: list[dict]) -> bool:
    """别名注册断言：written 实体在 PG entity_alias 各有 ≥1 行（commit 同事务写入）。"""
    import psycopg
    ids = [w["id"] for w in written]
    with psycopg.connect(os.environ["ADKG_PG_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("SELECT internal_id, count(*) FROM entity_alias"
                    " WHERE internal_id = ANY(%s) GROUP BY 1", (ids,))
        got = {r[0] for r in cur.fetchall()}
    return set(ids) <= got


def cleanup_written(written: list[dict]) -> None:
    """场景清理：DETACH DELETE written 节点 + 删别名行——评测不留脏数据。

    安全性由 commit_draft 主数据保护背书：written 只含新写实体（L1 对齐命中的
    既有 Brand/Product/Person 不进 written、不碰），按 written 清理不伤主数据。"""
    import psycopg
    ids = [w["id"] for w in written]
    with _neo4j().session() as s:
        s.run("MATCH (e:Entity) WHERE e.id IN $ids DETACH DELETE e", ids=ids)
    with psycopg.connect(os.environ["ADKG_PG_DSN"]) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM entity_alias WHERE internal_id = ANY(%s)", (ids,))
        conn.commit()


# ------------------------------------------------------------------ 单场景

def eval_agent(client, sc: dict, judge_fn=None, keep: bool = False) -> dict:
    t0 = time.monotonic()
    result = {"id": sc["id"], "type": sc["type"], "checks": {}, "tools": [], "degraded": []}
    r = None
    first_error = ""
    for attempt in (1, 2):                              # 传输层单次重试（端点 10~90s 方差长尾，
        try:                                            #  §7.2 引擎单次不重试纪律不受影响——重试在评测侧且透明标注）
            r = client.post("/agent/chat", json={
                "messages": [{"role": "user", "content": sc["question"]}],
                "role": sc["role"], "user": sc["user"]})
            if r.status_code == 200 or (400 <= r.status_code < 500 and r.status_code != 429):
                break                                   # 成功或确定性 4xx（权限/校验）不重试
            first_error = first_error or f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:                          # noqa: BLE001 超时/连接类传输失败
            first_error = first_error or f"{type(e).__name__}: {e}"
            r = None
    if attempt == 2 and first_error and (r is None or r.status_code != 200):
        # 传输类失败（异常/5xx/429）重试后仍死 → transport_dead：剔除该轮分母
        # （口径重拍板 2026-10-30：端点长尾不是 agent 质量信号，报告单列不掩埋）
        transport = r is None or r.status_code in (429, 500, 502, 503, 504)
        result["error"] = f"{first_error}（重试 1 次仍失败）"
        result["transport_dead"] = transport
        result["pass"] = False
        return result
    if attempt == 2 and r is not None and r.status_code == 200:
        result["retried"] = True                        # 首次传输失败、重试成功——报告可见
    result["first_error"] = first_error if result.get("retried") else ""
    result["seconds"] = round(time.monotonic() - t0, 1)
    if r.status_code != 200:
        result["error"] = f"HTTP {r.status_code}: {r.text[:200]}"
        result["pass"] = False
        return result
    body = r.json()
    reply, trace = str(body.get("reply") or ""), body.get("trace") or []
    result["tools"] = [t.get("tool") for t in trace]
    result["degraded"] = degraded_of(trace)
    result["reply_excerpt"] = reply[:300]               # 诊断材料：失败题看真实回复
    blob = reply + "\n" + "\n".join(str(t.get("result") or "") for t in trace)

    if sc["type"] == "casegen":
        checks = draft_checks(body.get("case_draft"), sc.get("expect_draft") or {})
        result["checks"].update(checks)
        written: list[dict] = []
        if all(checks.values()) and isinstance(body.get("case_draft"), dict):
            cr = client.post("/ingest/case-commit", json={
                "draft": body["case_draft"], "role": sc["role"], "user": sc["user"]})
            if cr.status_code == 200 and cr.json().get("status") == "written":
                result["checks"]["commit"] = True
                written = cr.json().get("written") or []
                case_id = cr.json().get("case_id") or ""
                result["checks"].update(graph_checks(case_id, written))
                result["checks"]["alias"] = alias_written(written)
                result["case_id"] = case_id
            else:
                result["checks"]["commit"] = False
                result["error"] = f"commit HTTP {cr.status_code}: {cr.text[:200]}"
        if written and not keep:
            cleanup_written(written)
            result["cleaned"] = True
        result["pass"] = all(result["checks"].values())
        return result

    # query / stat / comparison：judge 要点 + 实体锚 + 数值锚 + 越权缺席
    ans = sc.get("expected_answer") or {}
    points = ans.get("points") or []
    must = ans.get("must_entities") or []
    evs = evidence_of(reply, trace)
    checks = {"reply": bool(reply.strip())}
    if judge_fn is not None and points:
        verdict = judge_fn(sc["question"], points, evs)
        result["judge"] = verdict
        checks["judge"] = bool(verdict and verdict.get("verdict"))
    else:                                               # judge 缺席回退规则判据（§7.2）
        checks["judge"] = True                          # 仅由 reply/实体/数值锚兜底
    # agent 面证据不含结构化证据体（ask 工具只回传 answer/计数），实体锚按全 id
    # 或 slug 双重匹配；judge 在场时实体语义已由 judge 裁决（回复用实体名而非 ID
    # 是常态，2026-10-29 实弹）——匹配降为观察项，仅规则兜底模式下作硬门
    ent_hit = (not must) or any(m in blob or m.split(":", 1)[-1] in blob for m in must)
    if judge_fn is not None:
        result["entities_hit"] = ent_hit
    else:
        checks["entities"] = ent_hit
    checks["numbers"] = num_ok(blob, ans.get("must_numbers") or [])
    if sc.get("expect_absent"):
        checks["permission"] = all(a not in blob for a in sc["expect_absent"])
    result["checks"].update(checks)
    result["pass"] = all(result["checks"].values())
    return result


# ------------------------------------------------------------------ 主流程

def _client():
    from fastapi.testclient import TestClient

    from adkg.api.main import create_app
    env = {k: v for k, v in os.environ.items()
           if k.startswith(("ADKG_", "POSTGRES", "NEO4J"))}
    return TestClient(create_app(env))


def gate_of(results_by_round: list[list[dict]]) -> dict[str, bool]:
    """两轮门：每型各轮通过率 ≥ 阈值（casegen 恒 1.0），**分母剔除 transport_dead**
    （传输超时重试后仍死=端点长尾非质量信号，口径重拍板 2026-10-30）。单轮跑同式。"""
    by_type = defaultdict(list)
    for results in results_by_round:
        agg = defaultdict(lambda: [0, 0])
        for r in results:
            if r.get("transport_dead"):
                continue
            agg[r["type"]][1] += 1
            agg[r["type"]][0] += bool(r["pass"])
        for t, (ok, n) in agg.items():
            by_type[t].append(ok / n if n else 0.0)
    return {t: all(rate >= (1.0 if t == "casegen" else GATE_RATE) for rate in rates)
            for t, rates in by_type.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description="agent 场景评测（/agent/chat ReAct 全链路）")
    ap.add_argument("--scenarios", type=Path, default=SCENARIOS)
    ap.add_argument("--rounds", type=int, default=2, help="连跑轮数（验收=连续两轮，默认 2）")
    ap.add_argument("--types", default="", help="逗号分隔题型过滤（缺省全部）")
    ap.add_argument("--keep", action="store_true", help="casegen 跑后不清理（观察图上落点）")
    args = ap.parse_args()

    rows = load(args.scenarios)
    if args.types:
        want = {t.strip() for t in args.types.split(",") if t.strip()}
        unknown = want - AGENT_TYPES
        if unknown:
            sys.exit(f"未知题型 {sorted(unknown)}")
        rows = [r for r in rows if r["type"] in want]
    if not rows:
        sys.exit("无场景可跑")

    client = _client()
    judge_fn = None
    try:
        from adkg.llm import LLMClient
        llm = LLMClient()
        llm.batch_chat_json("ping", '返回 {"ok": true}')      # 通道可用性探测

        def judge_fn(q, pts, ev):
            return judge_item(llm.batch_chat_json, q, pts, ev)
        print(f"judge：LLM 按要点打分；场景 {len(rows)} 条 × {args.rounds} 轮\n")
    except Exception as e:
        print(f"judge 不可用，回退规则判据：{type(e).__name__}；场景 {len(rows)} 条 × {args.rounds} 轮\n")

    rounds: list[list[dict]] = []
    for ri in range(1, args.rounds + 1):
        print(f"—— 第 {ri}/{args.rounds} 轮 ——")
        results = []
        for sc in rows:
            try:
                results.append(eval_agent(client, sc, judge_fn, keep=args.keep))
            except Exception as e:                      # noqa: BLE001 单场景判分异常不炸整轮（§7.2）
                results.append({"id": sc["id"], "type": sc["type"], "checks": {},
                                "pass": False, "error": f"{type(e).__name__}: {e}"})
        rounds.append(results)
        for r in results:
            if r.get("transport_dead"):
                print(f"  ⊘ {r['id']} [{r['type']}] 传输超时剔除分母：{r.get('error', '')[:70]}")
                continue
            mark = "✓" if r["pass"] else "✗"
            extra = f" tools={r.get('tools')} degraded={r.get('degraded')}" if r["pass"] else ""
            err = f" error={r.get('error')}" if r.get("error") else ""
            bad = "" if r["pass"] else f" 失败项 {[k for k, v in r['checks'].items() if not v]}"
            print(f"  {mark} {r['id']} [{r['type']}] {r.get('seconds', '?')}s{extra}{bad}{err}")

    print("\n—— 达标门（每型分别，各轮 ≥90%；casegen 恒 100%；分母剔除传输超时）——")
    gate = gate_of(rounds)
    for t, ok in gate.items():
        rates = []
        for results in rounds:
            sub = [r for r in results if r["type"] == t and not r.get("transport_dead")]
            dead = sum(1 for r in results if r["type"] == t and r.get("transport_dead"))
            rate = f"{sum(bool(r['pass']) for r in sub)}/{len(sub)}"
            rates.append(rate + (f"（⊘{dead}）" if dead else ""))
        print(f"  {'✓' if ok else '✗'} {t}: {' → '.join(rates)}")
    all_pass = all(gate.values())
    print(f"\n验收门：{'全过' if all_pass else '未过'}（场景文件 {args.scenarios.name}）")

    out_dir = ROOT / "eval" / "runs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out_dir / f"agent-{stamp}.json").write_text(
        json.dumps({"rounds": rounds, "gate": gate, "all_pass": all_pass,
                    "summary": {"scenarios": len(rows), "rounds": args.rounds}},
                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"报告 → eval/runs/agent-{stamp}.json")


if __name__ == "__main__":
    main()
