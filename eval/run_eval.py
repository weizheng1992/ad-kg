"""评测（README §11.3 / §7.1 Phase 6）。

判据（LLM judge 待 API key，先跑规则判据）：
- routes：expected_routes 主路线 ∈ 实际 routes_used（graph 题的 vector 辅路不算错）
- evidence：非空且含 must_entities 之一（graph/fact/attribution）
- 越权：client 题的他牌案例零出现
- operation：/ask 返回指引后打 /actions/check，verdict 与期望一致
消融基线（双路 RAG / 双路+Text2SQL）依赖嵌入与 judge——key 修复后补跑，
本脚本已留 baseline 参数位。结果写 eval/runs/（gitignored）。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from eval.judge import judge_item  # noqa: E402

load_dotenv(ROOT / ".env")

GOLDEN = ROOT / "eval" / "golden_set.jsonl"
REQUIRED_TYPES = {"multi_hop", "fact", "concept", "attribution", "operation"}


def load() -> list[dict]:
    rows = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    bad = [r.get("id") for r in rows
           if not {"id", "type", "question", "expected_routes"} <= set(r)]
    if bad:
        sys.exit(f"缺 §12.3 必填字段的题：{bad}")
    unknown = {r["type"] for r in rows} - REQUIRED_TYPES
    if unknown:
        sys.exit(f"未知题型 {unknown}")
    return rows


def _client():
    import os

    from fastapi.testclient import TestClient
    from adkg.api.main import create_app
    env = {k: v for k, v in os.environ.items()
           if k.startswith(("ADKG_", "POSTGRES", "NEO4J"))}
    return TestClient(create_app(env))


def _role_of(item: dict) -> tuple[str, str]:
    """notes 里 role=xxx / user=Person:xxx；缺省 management。"""
    import re
    notes = item.get("notes", "")
    role = (re.search(r"role=(\w+)", notes) or [None, "management"])[1]
    user = (re.search(r"user=(Person:\w+)", notes) or [None, "Person:chen"])[1]
    if role == "client":
        user = "Person:client_a"
    return role, user


def eval_one(client, item: dict, judge_fn=None) -> dict:
    role, user = _role_of(item)
    r = client.post("/ask", json={"question": item["question"], "role": role, "user": user})
    body = r.json()
    result = {"id": item["id"], "type": item["type"], "checks": {}}

    if item["type"] == "operation":
        result["checks"]["guidance"] = body.get("action") == "guidance"
        op = {"删掉 live 案例的素材 creative_992": ("delete_creative", "Creative:creative_992", "deny"),
              "把 Case:C-2025-014 从 closed 改回 live": ("update_stage", None, "deny"),
              "暂停计划 Campaign:C-2025-005-cp1": ("pause_campaign", None, "allow")}.get(item["question"])
        if op:
            payload = {"op": op[0], "role": role if op[0] != "update_stage" else "admin",
                       "user": user}
            if op[0] == "update_stage":
                payload.update({"case_id": "Case:C-2025-014", "from_stage": "closed",
                                "to_stage": "live"})
            if op[1]:
                payload["target"] = op[1]
            v = client.post("/actions/check", json=payload).json()
            result["checks"]["verdict"] = v.get("decision") == op[2]
            result["audit_id"] = v.get("audit_id")
        result["pass"] = all(result["checks"].values())
        return result

    routes = [x["route"] for x in body.get("routes_used", [])]
    result["checks"]["routes"] = (not item["expected_routes"]
                                  or item["expected_routes"][0] in routes)
    evidence = body.get("evidence", [])
    must = item.get("expected_answer", {}).get("must_entities", [])
    blob = json.dumps(evidence, ensure_ascii=False, default=str)
    points = item.get("expected_answer", {}).get("points", [])
    # 数值硬断言（2026-10-23 收紧）：期望数字必须出现在证据/答案里，不再依赖 judge 心情；
    # judge 只认 verdict——verdict=False 即不通过（points_hit 曾把明确否决放行成虚绿）
    must_num = item.get("expected_answer", {}).get("must_numbers", [])
    num_ok = all(any(str(n) in txt for txt in (blob, str(body.get("answer") or "")))
                 for n in must_num)
    if judge_fn is not None and evidence:
        verdict = judge_fn(item["question"], points, evidence)   # LLM 按要点（§11.3）
        result["judge"] = verdict
        result["checks"]["evidence"] = bool(
            verdict and verdict["verdict"]) and (
            not must or any(m in blob for m in must)) and num_ok
    else:
        result["checks"]["evidence"] = bool(evidence) and (
            not must or any(m in blob for m in must)) and num_ok
    if role == "client":
        result["checks"]["permission"] = "Case:C-2025-006" not in blob  # 越权目标零出现
    result["degraded"] = body.get("degraded", [])
    result["pass"] = all(result["checks"].values())
    return result


def main() -> None:
    rows = load()
    client = _client()
    judge_fn = None
    try:
        from adkg.llm import LLMClient
        llm = LLMClient()
        llm.batch_chat_json("ping", '返回 {"ok": true}')      # 通道可用性探测
        judge_fn = lambda q, pts, ev: judge_item(llm.batch_chat_json, q, pts, ev)
        print("judge：LLM 按要点打分（glm-4-flash 批通道）\n")
    except Exception as e:
        print(f"judge 不可用，回退规则判据：{type(e).__name__}\n")
    results = [eval_one(client, item, judge_fn) for item in rows]

    dist = Counter(r["type"] for r in results)
    by_type: dict[str, list] = {t: [r for r in results if r["type"] == t] for t in REQUIRED_TYPES}
    passed = sum(1 for r in results if r["pass"])
    print(f"golden set {len(results)} 题，通过 {passed}（{passed / len(results):.0%}）\n")
    print(f"{'类型':<12}{'通过/总数':<10}备注")
    for t in sorted(REQUIRED_TYPES):
        sub = by_type[t]
        ok = sum(1 for r in sub if r["pass"])
        degraded_n = sum(1 for r in sub if r.get("degraded"))
        note = f"缺席路 {degraded_n} 题" if degraded_n else ""
        print(f"{t:<12}{ok}/{len(sub):<8}{note}")
    judged = [r for r in results if r.get("judge")]
    if judged:
        agree = sum(1 for r in judged if r["judge"]["verdict"])
        print(f"\njudge：{agree}/{len(judged)} 题要点全命中")
    failed = [r for r in results if not r["pass"]]
    if failed:
        print("\n未过：")
        for r in failed:
            bad = [k for k, v in r["checks"].items() if not v]
            print(f"  {r['id']} [{r['type']}] 失败项 {bad} degraded={r.get('degraded')}")

    out_dir = ROOT / "eval" / "runs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out_dir / f"{stamp}.json").write_text(
        json.dumps({"results": results, "summary": {"total": len(results), "passed": passed,
                                                    "dist": dict(dist)}},
                   ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n报告 → eval/runs/{stamp}.json（gitignored）")


if __name__ == "__main__":
    main()
