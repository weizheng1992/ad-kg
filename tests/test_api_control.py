"""管控端点端到端（Phase 5）：裁决 / 机判 / 断言写回，真库真图。"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from adkg.api.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    env = {k: v for k, v in os.environ.items()
           if k.startswith(("ADKG_", "POSTGRES", "NEO4J"))}
    return TestClient(create_app(env))


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestActionsCheck:
    def test_live案例删素材被拦(self, client):
        r = client.post("/actions/check", json={
            "op": "delete_creative", "target": "Creative:creative_992",
            "role": "optimizer", "user": "Person:li"})
        body = r.json()
        assert body["decision"] == "deny"                      # 画面 5
        assert "不可删除" in body["reason"] and body["audit_id"]

    def test_proposal案例删素材放行(self, client):
        r = client.post("/actions/check", json={
            "op": "delete_creative", "target": "Creative:C-2025-001-cp1-cr1",
            "role": "optimizer", "user": "Person:li"})
        body = r.json()
        assert body["decision"] == "allow" and "不代执行" in body["note"]

    def test_状态机非法迁移拒绝(self, client):
        r = client.post("/actions/check", json={
            "op": "update_stage", "case_id": "Case:C-2025-014",
            "from_stage": "closed", "to_stage": "live",
            "role": "admin", "user": "Person:admin"})
        assert r.json()["decision"] == "deny"

    def test_角色无此动作拒绝(self, client):
        r = client.post("/actions/check", json={
            "op": "delete_creative", "target": "Creative:x",
            "role": "client", "user": "Person:client_a"})      # client 只有 read
        assert r.json()["decision"] == "deny"


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestGuidelineCheck:
    def test_超时长违规(self, client):
        r = client.post("/guideline/check", json={
            "spec": {"duration_s": 40, "aspect_ratio": "9:16"},
            "role": "creative", "user": "Person:wang"})
        body = r.json()
        assert body["violations"] and any(v["max_duration_s"] == 15 for v in body["violations"])
        assert body["applicable"]

    def test_合规时长零违规(self, client):
        r = client.post("/guideline/check", json={
            "spec": {"duration_s": 10}, "role": "creative"})
        assert r.json()["violations"] == []


@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestIngestAssertion:
    def test_高置信写回图(self, client):
        r = client.post("/ingest/assertion", json={
            "subject": "Creative:C-2025-005-cp2-cr2", "predicate": "violates",
            "object": "Guideline:G-08", "confidence": 0.92,
            "role": "creative", "user": "Person:wang", "source_id": "aigc_check:t1"})
        assert r.json()["status"] == "written"

    def test_中置信进人审_低置信丢弃(self, client):
        r1 = client.post("/ingest/assertion", json={
            "subject": "Creative:C-2025-006-cp1-cr1", "predicate": "violates",
            "object": "Guideline:G-04", "confidence": 0.55, "role": "creative"})
        assert r1.json()["status"] == "review"
        r2 = client.post("/ingest/assertion", json={
            "subject": "Creative:C-2025-006-cp1-cr2", "predicate": "violates",
            "object": "Guideline:G-04", "confidence": 0.2, "role": "creative"})
        assert r2.json()["status"] == "dropped"

    def test_词表外谓词422(self, client):
        r = client.post("/ingest/assertion", json={
            "subject": "a", "predicate": "teleports_to", "object": "b",
            "confidence": 0.9, "role": "creative"})
        assert r.status_code == 422



@pytest.mark.skipif(not os.environ.get("ADKG_PG_DSN"), reason="未配置 .env")
class TestActionsReceipt:
    """回执两段契约后半段（备忘⑮；2026-10-31 夜检：0c08c65 声称的 +2 测试三轮未落，本类补齐对齐提交声明）。"""

    def test_裁决到回执闭环(self, client):
        # 裁决（allow）→ 回执 done：新审计行引用原 id，原行只追加不回改
        r = client.post("/actions/check", json={
            "op": "delete_creative", "target": "Creative:C-2025-001-cp1-cr1",
            "role": "optimizer", "user": "Person:li"})
        audit_id = r.json()["audit_id"]
        r2 = client.post("/actions/receipt", json={
            "audit_id": audit_id, "outcome": "done", "note": "执行方已删除",
            "role": "optimizer", "user": "Person:li"})
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["ok"] is True and body["linked"] == audit_id
        import psycopg
        with psycopg.connect(os.environ["ADKG_PG_DSN"]) as c, c.cursor() as cur:
            cur.execute("SELECT action, target, verdict FROM audit_log WHERE id = %s",
                        (body["receipt_audit_id"],))
            assert cur.fetchone() == ("action_receipt", f"audit:{audit_id}", "done")
            cur.execute("SELECT verdict FROM audit_log WHERE id = %s", (audit_id,))
            assert cur.fetchone()[0] == "allow"          # 原裁决行未被回执改写

    def test_校验序_outcome_uuid_404(self, client):
        # outcome 词表外 → 422（先于 audit_id 校验——校验序契约钉死）
        r1 = client.post("/actions/receipt", json={"audit_id": "", "outcome": "ok",
                                                   "role": "admin"})
        assert r1.status_code == 422 and "outcome" in r1.json()["detail"]
        # audit_id 非 uuid → 422
        r2 = client.post("/actions/receipt", json={"audit_id": "not-a-uuid",
                                                   "outcome": "done", "role": "admin"})
        assert r2.status_code == 422 and "uuid" in r2.json()["detail"].lower()
        # 合法 uuid 但库中不存在 → 404
        import uuid as _u
        ghost = str(_u.uuid4())
        r3 = client.post("/actions/receipt", json={"audit_id": ghost, "outcome": "done",
                                                   "role": "admin"})
        assert r3.status_code == 404 and ghost in r3.json()["detail"]
