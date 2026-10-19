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
