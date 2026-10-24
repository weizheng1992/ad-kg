"""管理后台只读三件套（spec §7）：角色门 + 无口令哈希 + 审计分页。

真库集成（不在线跳过）。"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _pg_up() -> bool:
    try:
        import psycopg
        with psycopg.connect(os.environ["ADKG_PG_DSN"], connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _pg_up(), reason="Postgres 不在线")
class TestAdminAPI:
    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def test_角色门(self):
        client = self._client()
        for role in ("management", "admin"):
            assert client.get("/admin/permission-matrix",
                              params={"role": role}).status_code == 200
        for role in ("finance", "ae", "optimizer", "creative", "client"):
            assert client.get("/admin/accounts",
                              params={"role": role}).status_code == 403

    def test_权限矩阵内容(self):
        client = self._client()
        d = client.get("/admin/permission-matrix",
                       params={"role": "management"}).json()
        assert "client" in d["roles"] and d["roles"]["client"]["external"]
        assert "Creator" in d["roles"]["finance"]["classes"]     # spec §3
        assert d["roles"]["optimizer"]["metrics_deny"] == ["gross_margin"]

    def test_账号一览不含哈希(self):
        client = self._client()
        d = client.get("/admin/accounts", params={"role": "admin"}).json()
        assert d["items"] and all("password_hash" not in a for a in d["items"])

    def test_审计分页与字段(self):
        client = self._client()
        d = client.get("/admin/audit", params={"role": "management", "page": 1,
                                               "size": 5}).json()
        assert d["total"] > 0 and len(d["items"]) <= 5
        assert {"id", "ts", "role", "action", "verdict"} <= set(d["items"][0])
