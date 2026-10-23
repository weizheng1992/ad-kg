"""认证解析收口（README §9.1，2026-10-23）：token→role+绑定 person / dev 兜底。

各端点（ask / graph / agent / ingest / creative）不再自抄认证块——散抄曾致
漏门（/ingest/assertion 无角色门即实例）。约定见 §12.4：token 路 person 一律
取 bindings 绑定值，body/query 自报仅补缺（多绑定角色）；dev 路
（ADKG_DEV_AUTH=off）允许 body/query 传 role/user。
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from adkg.guards.auth import AuthService


def resolve_identity(request: Request, authorization: str | None, *,
                     role: str | None = None, user: str | None = None,
                     body: dict | None = None, dev_default: str | None = None
                     ) -> tuple[str, str | None, "PermissionPlanner"]:
    """统一认证解析：返回 (role, person, planner)；未认证抛 401。

    - token 路：role 取 token 映射，person 取该 role 的唯一 bindings 绑定值
      （缺省回退 body/query 自报）；dev 路入参不采信
    - dev 路：ADKG_DEV_AUTH=off 时 body/query 的 role/user；dev_default 允许
      无角色调用落到默认角色（内部工具端点用，如 /ingest/docs → management）
    - role 合法性（planner.roles 预检）与角色门（CASEGEN_ROLES 等）由调用方负责
    """
    from adkg.api.routes.ask import _planner          # 惰性防环
    planner = _planner(request)
    env = request.app.state.env
    resolved = AuthService(env).resolve(authorization)
    if resolved:
        role = resolved[0]
        fallback = user if body is None else body.get("user")
        person = planner.bound_person(role) or fallback
        return role, person, planner
    dev_role = (body.get("role") if body is not None else None) or role or dev_default
    if env.get("ADKG_DEV_AUTH") == "off" and dev_role:
        person = (body.get("user") if body is not None else None) or user
        return dev_role, person, planner
    raise HTTPException(401, "缺有效 service token（生产经网关注入；本地 "
                             "ADKG_DEV_AUTH=off 可传 role）")
