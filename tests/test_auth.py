"""认证（spec docs/specs/2026-10-24-真实系统化升级-spec.md §2）。

scrypt 哈希离线测；/auth/* 与 cookie 路走真库集成（库不在线跳过，
同 tests/test_stores_integration.py 的门模式）。
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from adkg.guards.passwords import hash_password, verify_password

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _pg_up() -> bool:
    try:
        import psycopg
        with psycopg.connect(os.environ["ADKG_PG_DSN"], connect_timeout=3):
            return True
    except Exception:
        return False


class TestPasswords:
    def test_哈希可验证且错密码拒绝(self):
        stored = hash_password("s3cret-pass")
        assert verify_password("s3cret-pass", stored)
        assert not verify_password("wrong", stored)

    def test_每次哈希盐随机(self):
        assert hash_password("same") != hash_password("same")

    def test_畸形存储串不炸一律False(self):
        for bad in ("", "not-a-hash", "scrypt$!!$$", "scrypt$AAAA$BBB", "$-$"):
            assert not verify_password("x", bad)


@pytest.mark.skipif(not _pg_up(), reason="Postgres 不在线")
class TestAuthAPI:
    """login → me → logout 全链 + 错密码 401 + cookie 路 resolve_identity。"""

    USERNAME = "pytest_user"

    def _setup_user(self) -> None:
        import psycopg
        # DDL 走 admin（adkg_rw 无建表权，§五 双账号边界）；DML 走应用账号
        admin = (f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
                 f"@127.0.0.1:{os.environ.get('POSTGRES_PORT', '5433')}/"
                 f"{os.environ['POSTGRES_DB']}")
        sql = (ROOT / "sql" / "003_auth.sql").read_text(encoding="utf-8")
        with psycopg.connect(admin, autocommit=True) as c:
            c.execute(sql)
        with psycopg.connect(os.environ["ADKG_PG_DSN"], autocommit=True) as c:
            c.execute(
                "INSERT INTO app_user (id, username, password_hash, display_name, role, person)"
                " VALUES ('u_pytest', %s, %s, '测试账号', 'finance', NULL)"
                " ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash,"
                " disabled=false",
                (self.USERNAME, hash_password("pw-12345")))
            c.execute("DELETE FROM app_session WHERE user_id='u_pytest'")

    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        # dev 关：逼认证只走 cookie 路（body 自报 role 不应生效）
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "on"}))

    def test_登录登出与会话(self):
        self._setup_user()
        client = self._client()
        r = client.post("/auth/login", json={"username": self.USERNAME, "password": "wrong"})
        assert r.status_code == 401
        r = client.post("/auth/login",
                        json={"username": "no-such-user", "password": "whatever"})
        assert r.status_code == 401
        r = client.post("/auth/login",
                        json={"username": self.USERNAME, "password": "pw-12345"})
        assert r.status_code == 200
        me = r.json()
        assert me["role"] == "finance" and me["username"] == self.USERNAME
        r = client.get("/auth/me")
        assert r.status_code == 200 and r.json()["role"] == "finance"
        r = client.post("/auth/logout")
        assert r.status_code == 200
        assert client.get("/auth/me").status_code == 401

    def test_无会话未认证端点401(self):
        self._setup_user()
        client = self._client()          # 从未登录：无 cookie
        r = client.get("/graph/entity", params={"id": "Brand:B01"})
        assert r.status_code == 401      # cookie 缺席且 dev 关——fail-closed

    def teardown_method(self):
        if not _pg_up():
            return
        import psycopg
        with psycopg.connect(os.environ["ADKG_PG_DSN"], autocommit=True) as c:
            c.execute("DELETE FROM app_session WHERE user_id='u_pytest'")
            c.execute("DELETE FROM app_user WHERE id='u_pytest'")
