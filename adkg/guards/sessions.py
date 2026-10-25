"""Web 会话存储（spec §2）：DB 会话（可吊销、滑动续期），与 service token 路
（guards/auth.py，smartServe / eval 用）互补——互不感知，解析优先级见 http.py。
"""
from __future__ import annotations

import secrets
from datetime import timedelta

import psycopg

from adkg.store import pg_pool

SESSION_COOKIE = "adkg_session"
SESSION_TTL = timedelta(days=7)

_COLS = ("user_id", "username", "display_name", "role", "person")


def create_session(env: dict[str, str], user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("INSERT INTO app_session (token, user_id, expires_at) "
                    "VALUES (%s, %s, now() + %s::interval)",
                    (token, user_id, f"{SESSION_TTL.total_seconds():.0f} seconds"))
    return token


def resolve_session(env: dict[str, str], token: str | None) -> dict | None:
    """token → 账号字段；过期 / 吊销 / 禁用账号一律 None（fail-closed）。"""
    if not token:
        return None
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute(
            "SELECT u.id, u.username, u.display_name, u.role, u.person "
            "FROM app_session s JOIN app_user u ON u.id = s.user_id "
            "WHERE s.token = %s AND s.expires_at > now() AND NOT u.disabled", (token,))
        row = cur.fetchone()
    if not row:
        return None
    return dict(zip(_COLS, row))


def touch_session(env: dict[str, str], token: str) -> None:
    """滑动续期（/auth/me 时顺延）；API 请求只读不续，写放大留给登录面。"""
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("UPDATE app_session SET expires_at = now() + %s::interval, "
                    "last_seen_at = now() WHERE token = %s",
                    (f"{SESSION_TTL.total_seconds():.0f} seconds", token))


def revoke_session(env: dict[str, str], token: str) -> None:
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("DELETE FROM app_session WHERE token = %s", (token,))
