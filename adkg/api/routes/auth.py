"""Web 认证端点（spec §2 / README §9.1）：账号在库 + DB 会话 cookie。

登录成败均落审计；错密码与未知用户名等时（哑校验防探测）。会话 cookie
HttpOnly + SameSite=Lax，部署态 HTTPS 由 ADKG_COOKIE_SECURE=on 加 Secure。
"""
from __future__ import annotations

import psycopg

from adkg.store import pg_pool
from fastapi import APIRouter, HTTPException, Request, Response

from adkg.guards.audit import audit
from adkg.guards.passwords import DUMMY_HASH, verify_password
from adkg.guards.sessions import (SESSION_COOKIE, SESSION_TTL, create_session,
                                  resolve_session, revoke_session, touch_session)

router = APIRouter()


def _find_user(env: dict[str, str], username: str) -> dict | None:
    with pg_pool.connect(env["ADKG_PG_DSN"]) as c, c.cursor() as cur:
        cur.execute("SELECT id, username, display_name, role, person, "
                    "password_hash, disabled FROM app_user WHERE username = %s",
                    (username,))
        row = cur.fetchone()
    if not row:
        return None
    return dict(zip(("id", "username", "display_name", "role", "person",
                     "password_hash", "disabled"), row))


def _public(user: dict) -> dict:
    return {"username": user["username"], "display_name": user["display_name"],
            "role": user["role"], "person": user["person"]}


@router.post("/auth/login")
def login(request: Request, body: dict, response: Response) -> dict:
    env = request.app.state.env
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    user = _find_user(env, username)
    stored = user["password_hash"] if user else DUMMY_HASH   # 未知用户名也跑同代价 verify
    if not user or user["disabled"] or not verify_password(password, stored):
        audit(env, "anonymous", None, "login", username or "-", "deny", "账号或密码不正确")
        raise HTTPException(401, "账号或密码不正确")
    token = create_session(env, user["id"])
    audit(env, user["role"], user["person"], "login", username, "allow")
    response.set_cookie(SESSION_COOKIE, token,
                        max_age=int(SESSION_TTL.total_seconds()),
                        httponly=True, samesite="lax",
                        secure=env.get("ADKG_COOKIE_SECURE") == "on")
    return _public(user)


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_session(request.app.state.env, token)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request) -> dict:
    env = request.app.state.env
    token = request.cookies.get(SESSION_COOKIE)
    sess = resolve_session(env, token)
    if not sess:
        raise HTTPException(401, "未登录或会话已过期")
    touch_session(env, token)
    return {k: sess[k] for k in ("username", "display_name", "role", "person")}
