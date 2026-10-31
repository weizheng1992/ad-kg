"""agent 场景评测执行器（eval/agent_eval.py）。

离线：loader 校验 / 数值容差 / 证据与降级收集 / 草稿字段断言 / 达标门口径 /
query 路全流程（stub client）。
端点：真库 skipif 门控——stat 与 casegen 场景脚本化 FakeLLM 全链
（casegen 验证落点断言 + 清理零残留，安全性由 commit_draft written 语义背书）。
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from eval.agent_eval import (draft_checks, evidence_of, eval_agent, gate_of,  # noqa: E402
                             load, num_ok, degraded_of)

def _resp(status_code: int, body: dict | None = None, text: str = ""):
    """响应桩单源（2026-10-31 夜检：三处 type("R",()) 复制收口）。"""
    return type("R", (), {"status_code": status_code, "text": text,
                          "json": lambda self: body if body is not None else {}})()


SCEN = {"id": "X01", "type": "stat", "question": "上个月哪个素材 CPA 最差？", "role": "management",
        "user": "Person:chen", "expected_answer": {"points": ["top1", "数值"],
                                                   "must_entities": ["Creative:a"], "must_numbers": [21.59]}}


# ------------------------------------------------------------------ 离线件

class TestLoader:
    def test_缺必填字段退出(self, tmp_path):
        p = tmp_path / "s.jsonl"
        p.write_text('{"id": "X", "type": "stat", "question": "q"}', encoding="utf-8")
        with pytest.raises(SystemExit):
            load(p)

    def test_未知题型退出(self, tmp_path):
        p = tmp_path / "s.jsonl"
        p.write_text('{"id": "X", "type": "golden_fact", "question": "q", "role": "r", "user": "u"}',
                     encoding="utf-8")
        with pytest.raises(SystemExit):
            load(p)

    def test_casegen缺期望退出(self, tmp_path):
        p = tmp_path / "s.jsonl"
        p.write_text('{"id": "X", "type": "casegen", "question": "q", "role": "r", "user": "u"}',
                     encoding="utf-8")
        with pytest.raises(SystemExit):
            load(p)

    def test_id重复退出(self, tmp_path):
        p = tmp_path / "s.jsonl"
        row = '{"id": "X", "type": "stat", "question": "q", "role": "r", "user": "u"}'
        p.write_text(f"{row}\n{row}", encoding="utf-8")
        with pytest.raises(SystemExit):
            load(p)

    def test_合法文件载入(self, tmp_path):
        p = tmp_path / "s.jsonl"
        p.write_text('{"id": "X", "type": "casegen", "question": "q", "role": "r", "user": "u",'
                     ' "expect_draft": {"brand_name": "途野露营"}}', encoding="utf-8")
        assert len(load(p)) == 1


class TestNumOk:
    def test_容差与形态(self):
        assert num_ok("CPA 21.6 元", ["21.59"])            # ±max(0.06,1%) 容差
        assert num_ok("CPA 22 元", ["21.59"]) is False
        assert num_ok("消耗 558079", [558079])
        assert num_ok("没有数字", ["21.59"]) is False
        assert num_ok("任意文本", [])                       # 无锚恒真

    def test_多锚全中(self):
        assert num_ok("A 100，B 200", ["100", "200"])
        assert num_ok("A 100", ["100", "200"]) is False

    def test_千分位逗号不劈数字(self):
        assert num_ok("总消耗 1,001,609.41 元", [1001609])
        assert num_ok("转化 68,746，花费 558,078.95", [68746])

    def test_百分号语义(self):
        assert num_ok("CTR 为 1.64%（点击 5368 次）", [0.02])   # 1.64%/100=0.0164 容差内
        assert num_ok("CTR 为 1.64%", [1.64])                   # 锚是百分数形态也中
        assert num_ok("CPA 48.78 元", [0.02]) is False          # 无百分号不撒 /100 网


def test_evidence组装():
    evs = evidence_of("答复正文", [{"tool": "ask_knowledge", "result": "结果一"}])
    assert evs[0]["ref"] == "agent:reply" and "答复" in evs[0]["quote"]
    assert evs[1]["ref"] == "tool:0:ask_knowledge" and evs[1]["quote"] == "结果一"


def test_degraded收集():
    trace = [{"tool": "ask_knowledge", "result": '{"answer": "x", "degraded": ["vector"]}'},
             {"tool": "list_brands", "result": "非 JSON 文本"},
             {"tool": "list_brands", "result": '[{"id": "Brand:B01"}]'}]   # 数组结果不炸
    assert degraded_of(trace) == ["ask_knowledge:['vector']"]
    assert degraded_of([{"tool": "t", "result": "plain"}]) == []


class TestDraftChecks:
    def _draft(self):
        return {"case": {"id": "Case:C-2026-001", "props": {"stage": "proposal"}},
                "brand": {"name": "途野露营"}}

    def test_全过(self):
        assert all(draft_checks(self._draft(), {"brand_name": "途野露营", "stage": "proposal"}).values())

    def test_草稿缺席(self):
        assert draft_checks(None, {}) == {"draft": False}

    def test_品牌不符(self):
        assert draft_checks(self._draft(), {"brand_name": "别的牌"})["brand"] is False

    def test_阶段不符(self):
        assert draft_checks(self._draft(), {"stage": "live"})["stage"] is False

    def test_建号约定破坏(self):
        d = self._draft()
        d["case"]["id"] = "Case:whatever"
        assert draft_checks(d, {})["case_id_format"] is False


class TestGate:
    def _rows(self, type_, n, k):
        return [{"id": f"{type_}{i}", "type": type_, "pass": i < k, "checks": {}}
                for i in range(n)]

    def test_题型九成线(self):
        assert gate_of([self._rows("stat", 10, 9)])["stat"] is True
        assert gate_of([self._rows("stat", 10, 8)])["stat"] is False

    def test_casegen恒全过(self):
        assert gate_of([self._rows("casegen", 10, 9)])["casegen"] is False
        assert gate_of([self._rows("casegen", 10, 10)])["casegen"] is True

    def test_连续两轮(self):
        r1, r2 = self._rows("stat", 10, 10), self._rows("stat", 10, 9)
        assert gate_of([r1, r2])["stat"] is True
        r2b = self._rows("stat", 10, 8)
        assert gate_of([r1, r2b])["stat"] is False


def test_cli入口守卫钉死():
    """两评测脚本必须有 __main__ 守卫——recalc_agent 曾漏写致静默零输出
    （agent-all 评测票「守卫缺失曾致零入库」同款事故，机器钉死防复发）。"""
    for f in ("eval/agent_eval.py", "eval/recalc_agent.py"):
        assert '__name__ == "__main__"' in (ROOT / f).read_text(encoding="utf-8"), f


def test_query路_checks组装():
    """离线全流程：stub client 返回聚合 JSON，judge/实体/数值/越权四判据组装。"""
    class _C:
        def post(self, url, json=None):                 # noqa: A002
            assert url == "/agent/chat"
            return _resp(200, {
                "reply": "素材 a 的 CPA 是 21.6，最差。",
                "trace": [{"tool": "ask_knowledge", "result": '{"answer": "x"}'}],
                "case_draft": None, "creative_drafts": None})

    sc = {**SCEN, "expected_answer": {"points": [], "must_entities": ["Creative:a"],
                                      "must_numbers": [21.59]},
          "expect_absent": ["Case:C-2025-006"]}
    r = eval_agent(_C(), sc, judge_fn=None)
    assert r["pass"] is True and r["checks"]["entities"] and r["checks"]["numbers"]
    assert r["checks"]["permission"]

    leak = {**sc, "expect_absent": ["素材 a"]}          # 正文真实泄漏的 token
    r2 = eval_agent(_C(), leak, judge_fn=None)
    assert r2["pass"] is False and r2["checks"]["permission"] is False

    err = {**sc, "expect_absent": []}
    calls = []

    class _Boom:
        def post(self, url, json=None):                 # noqa: A002
            calls.append(url)
            raise RuntimeError("管线炸了")

    r3 = eval_agent(_Boom(), err, judge_fn=None)
    assert r3["pass"] is False and "RuntimeError" in r3["error"]

    def _judge_ok(q, pts, ev):                          # judge 在场：实体匹配软化
        return {"verdict": True, "points_hit": pts, "reason": "ok"}

    r4 = eval_agent(_C(), {**sc, "expect_absent": []}, judge_fn=_judge_ok)
    assert r4["pass"] is True
    assert "entities" not in r4["checks"] and r4["entities_hit"] is True
    assert r4.get("reply_excerpt")                      # 诊断摘录落报告


def test_传输层单次重试():
    """首调超时、重试成功 → 过且 retried 标注；两连败 → 误差含首错。"""
    class _FlakyOnce:
        calls = 0

        def post(self, url, json=None):                 # noqa: A002
            _FlakyOnce.calls += 1
            if _FlakyOnce.calls == 1:
                raise TimeoutError("Request timed out.")
            return _resp(200, {"reply": "答复。", "trace": [],
                               "case_draft": None, "creative_drafts": None})

    sc = {**SCEN, "expected_answer": {"points": [], "must_entities": [], "must_numbers": []}}
    r = eval_agent(_FlakyOnce(), sc, judge_fn=None)
    assert r["pass"] is True and r.get("retried") is True
    assert "TimeoutError" in r.get("first_error", "")   # 首错留痕不掩埋

    class _AlwaysDead:
        def post(self, url, json=None):                 # noqa: A002
            raise TimeoutError("Request timed out.")

    r2 = eval_agent(_AlwaysDead(), sc, judge_fn=None)
    assert r2["pass"] is False and "重试 1 次仍失败" in r2["error"]
    assert r2.get("transport_dead") is True             # 异常路=传输类，剔除分母

    class _Always422:
        calls = 0

        def post(self, url, json=None):                 # noqa: A002
            _Always422.calls += 1
            return _resp(422, text="校验挂")

    r3 = eval_agent(_Always422(), sc, judge_fn=None)
    assert r3["pass"] is False and not r3.get("transport_dead")  # 确定性 4xx=真失败进分母
    assert _Always422.calls == 1                        # 4xx 不重试


def test_gate剔除传输超时分母():
    """transport_dead 不进分母（口径重拍板 2026-10-30）；4xx 真失败照常计入。"""
    rows = [{"id": "a", "type": "stat", "pass": True},
            {"id": "b", "type": "stat", "pass": False},
            {"id": "c", "type": "stat", "pass": False, "transport_dead": True}]
    assert gate_of([rows])["stat"] is False             # 1/2=50%
    rows[1]["pass"] = True
    assert gate_of([rows])["stat"] is True              # 剔除后 2/2
    rows.append({"id": "d", "type": "stat", "pass": False})  # 2/3
    assert gate_of([rows])["stat"] is False


# --------------------------------------------------- 真库集成（skipif 门控）

FINAL = {"final": {"answer": "基于图里的途野露营（户外旅行）给出案例草稿。",
                   "case_seed": {"brand_name": "途野露营", "product_names": ["星链Pro"],
                                 "case_name": "星链Pro 冬季投放", "stage": "proposal",
                                 "person_ids": ["Person:li"]},
                   "creative_drafts": None}}
ACTION_ASK = {"action": "ask_knowledge", "args": {"question": "上月 CPA 最差的素材有哪些？"}}


def _script_llm(*payloads):
    class _L:
        calls = 0

        def chat_json_slow(self, system, user, *, timeout=180, **kw):
            _L.calls += 1
            return payloads[min(_L.calls - 1, len(payloads) - 1)]

        def chat_json(self, system, user, **kw):            # /ask 内部（路由/总结）
            return {"answer": "已按证据回答", "decision": {"intent": "fact"}}

        def embed(self, texts):
            return [[0.0] * 512 for _ in texts]
    return _L()


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestAgentEvalReal:
    def _client(self, payloads):
        from fastapi.testclient import TestClient

        from adkg.api.main import create_app
        env = {k: v for k, v in os.environ.items() if k.startswith(("ADKG_", "NEO4J"))}
        c = TestClient(create_app(env))
        c.app.state.llm = _script_llm(*payloads)
        return c

    def test_stat场景_脚本LLM全链(self):
        """窗口 top CPA：先按库算锚（与 recalc_agent 同口径），脚本 FINAL 转述
        slug+数值 → 实体锚/数值锚双中。"""
        import psycopg

        from adkg.retrieval import text2sql
        from adkg.retrieval.metrics import agg_expr
        w = text2sql._window_of("上月")                  # 窗口口径单源（随运行日历走）
        with psycopg.connect(os.environ["ADKG_PG_RO_DSN"]) as conn, conn.cursor() as cur:
            cur.execute(f"SELECT creative_id, {agg_expr('cpa')} FROM unified_metrics"
                        " WHERE NOT unmatched AND date BETWEEN %s AND %s"
                        " GROUP BY 1 HAVING count(DISTINCT date) >= 3"
                        " ORDER BY 2 DESC LIMIT 1", w)
            row = cur.fetchone()
        assert row and row[1] is not None, "种子库应存在上月窗口 CPA 锚"
        cid, val = row[0], round(float(row[1]), 2)

        sc = {**SCEN, "expected_answer": {"points": ["top1", "数值"],
                                          "must_entities": [cid], "must_numbers": [val]}}
        final = {"final": {"answer": f"上月 CPA 最差的是 {cid.split(':', 1)[1]}，"
                                       f"汇总比 CPA {val}。", "case_seed": None,
                           "creative_drafts": None}}
        r = eval_agent(self._client([ACTION_ASK, final]), sc, judge_fn=None)
        assert r["pass"] is True, r
        assert "ask_knowledge" in r["tools"]

    def test_casegen场景_落点断言与清理(self):
        from eval.agent_eval import load
        sc = next(s for s in load() if s["id"] == "A02")
        r = eval_agent(self._client([FINAL]), sc, judge_fn=None)
        assert r["pass"] is True, r
        assert r.get("cleaned") is True and r["case_id"].startswith("Case:C-")
        # 清理零残留：图与别名都不见 written 痕迹
        from eval.agent_eval import _neo4j
        with _neo4j().session() as s:
            left = s.run("MATCH (e:Entity {id:$id}) RETURN e", id=r["case_id"]).data()
        assert left == []


def test_judge回复窗口钉死1600():
    """T3「评测者伪影四处全钉测试」欠账（2026-10-31 夜检）：judge 回复窗口 800→1600
    曾无钉死测试——回退 800 不会挂。常量 + 截断行为双锚。"""
    from eval import agent_eval
    assert agent_eval.REPLY_WINDOW == 1600
    evs = agent_eval.evidence_of("x" * 2000, [])
    assert len(evs[0]["quote"]) == agent_eval.REPLY_WINDOW
    assert agent_eval.evidence_of("短", [])[0]["quote"] == "短"
