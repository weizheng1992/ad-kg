"""认证（§9.1）：service token → role / Person。

token 本体在 .env（ADKG_TOKEN_<ROLE>）；bindings 的 person 绑定 Phase 5 接
密管后启用——v1 每 role 一 token，person 由调用方上下文给（受托/锚点）。
本地开发：ADKG_DEV_AUTH=off 时 API 层允许 body 传 role（仅限本地）。
"""
from __future__ import annotations


class AuthService:
    def __init__(self, env: dict[str, str]) -> None:
        # ADKG_TOKEN_OPTIMIZER=xxx → ("xxx", "optimizer")
        self._by_token: dict[str, str] = {}
        for key, value in env.items():
            if key.startswith("ADKG_TOKEN_") and value:
                self._by_token[value] = key.removeprefix("ADKG_TOKEN_").lower()

    def resolve(self, authorization: str | None) -> tuple[str, str | None] | None:
        """返回 (role, person|None)；不认识即 None（API 层回 401）。"""
        if not authorization or not authorization.startswith("Bearer "):
            return None
        role = self._by_token.get(authorization.removeprefix("Bearer ").strip())
        return (role, None) if role else None
