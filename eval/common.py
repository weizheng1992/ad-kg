"""eval 共享件（2026-10-31 夜检收口：client / judge 装配 / jsonl 读取 / dry-run
写回协议曾四文件各抄——run_eval ↔ agent_eval 逐字同形，recalc_golden ↔
recalc_agent 同形；口径本体在 _criteria.py，本模块只收执行协议）。"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path: Path) -> list[dict]:
    """jsonl → dict 列表（跳过空行；四个 eval 入口曾各抄一份）。"""
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def make_client():
    """进程内 TestClient（env 过滤 ADKG_/POSTGRES_/NEO4J_ 前缀）——评测不占端口。"""
    from fastapi.testclient import TestClient

    from adkg.api.main import create_app
    env = {k: v for k, v in os.environ.items()
           if k.startswith(("ADKG_", "POSTGRES", "NEO4J"))}
    return TestClient(create_app(env))


def connect_judge():
    """judge 装配：LLM 通道 ping 探测 → (judge_fn, err)。ping 失败返回 (None, 异常名)
    ——调用方自行打印降级声明（§7.2 judge 缺席回规则判据）。"""
    try:
        from adkg.llm import LLMClient
        llm = LLMClient()
        llm.batch_chat_json("ping", '返回 {"ok": true}')   # 通道可用性探测

        def judge_fn(q, pts, ev):
            from eval.judge import judge_item
            return judge_item(llm.batch_chat_json, q, pts, ev)

        return judge_fn, ""
    except Exception as e:                                   # noqa: BLE001
        return None, type(e).__name__


DIFF_KEYS = ("points", "must_entities", "must_numbers")


def show_changes(changes: list[tuple[dict, dict]]) -> None:
    """锚点重算 dry-run diff 打印（recalc_golden ↔ recalc_agent 曾逐字同形）。"""
    for it, new_ans in changes:
        old = it.get("expected_answer", {})
        print(f"  {it['id']} [{it['type']}] {it['question']}")
        for k in DIFF_KEYS:
            if new_ans.get(k) != old.get(k):
                print(f"    {k}: {old.get(k)}\n      → {new_ans.get(k)}")


def apply_writeback(items: list[dict], changes: list[tuple[dict, dict]],
                    path: Path) -> int:
    """--yes 落盘（幂等协议后半段）：new_ans 合入 items 原位、整文件重写。
    返回条数；零变更/收尾语各 main 自持（golden/场景措辞不同）。"""
    for it, new_ans in changes:
        it["expected_answer"] = new_ans
    path.write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in items) + "\n",
        encoding="utf-8")
    return len(changes)
