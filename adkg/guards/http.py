"""认证与身份上下文收口（README §9.1，2026-10-23 起）：token→role+绑定 person / dev 兜底。

各端点（ask / graph / agent / ingest / creative / actions / guideline）不再自抄认证块
——散抄曾致漏门（/ingest/assertion 无角色门即实例）。约定见 §12.4：token 路 person
一律取 bindings 绑定值，body/query 自报仅补缺（多绑定角色）；dev 路
（ADKG_DEV_AUTH=off）允许 body/query 传 role/user。角色合法性预检（§十二
fail-closed）也在此统一做——dev 路可传任意值，未知即 401。

planner / graph 惰性单例挂 app.state（2026-10-24 收敛：本模块曾反向 import
routes.ask._planner，且 planner 与 actions 各建一份 GraphStore）。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request

from adkg.guards.auth import AuthService


def get_graph(request: Request):
    """图谱连接惰性单例（app.state.graph）——行权限展开、检索与图端点共用一个 driver。"""
    graph = getattr(request.app.state, "graph", None)
    if graph is None:
        from adkg.store.graph import GraphStore
        env = request.app.state.env
        request.app.state.graph = GraphStore(env["ADKG_NEO4J_URI"], env["ADKG_NEO4J_USER"],
                                             env["ADKG_NEO4J_PASSWORD"])
    return request.app.state.graph


def get_planner(request: Request) -> "PermissionPlanner":
    """PermissionPlanner 惰性单例（app.state.planner，挂共享图连接）——行权限展开
    与各端点认证共用同一实例。"""
    from adkg.guards.permission import PermissionPlanner   # 惰性防环
    planner = getattr(request.app.state, "planner", None)
    if planner is None:
        request.app.state.planner = PermissionPlanner(
            Path(__file__).resolve().parents[2] / "ontology" / "permissions.yaml",
            graph=get_graph(request))
    return request.app.state.planner


def resolve_identity(request: Request, authorization: str | None, *,
                     role: str | None = None, user: str | None = None,
                     body: dict | None = None, dev_default: str | None = None
                     ) -> tuple[str, str | None, "PermissionPlanner"]:
    """统一认证解析：返回 (role, person, planner)；未认证/未知角色抛 401。

    - token 路：role 取 token 映射，person 取该 role 的唯一 bindings 绑定值
      （缺省回退 body/query 自报）；dev 路入参不采信
    - dev 路：ADKG_DEV_AUTH=off 时 body/query 的 role/user；dev_default 允许
      无角色调用落到默认角色（内部工具端点用，如 /ingest/docs → management）
    - role ∈ planner.roles 预检（§十二）在此统一；角色门（CASEGEN_ROLES 等）
      仍由调用方负责
    """
    planner = get_planner(request)
    env = request.app.state.env
    resolved = AuthService(env).resolve(authorization)
    if resolved:
        role = resolved[0]
        fallback = user if body is None else body.get("user")
        person = planner.bound_person(role) or fallback
    else:
        dev_role = (body.get("role") if body is not None else None) or role or dev_default
        if not (env.get("ADKG_DEV_AUTH") == "off" and dev_role):
            raise HTTPException(401, "缺有效 service token（生产经网关注入；本地 "
                                     "ADKG_DEV_AUTH=off 可传 role）")
        role = dev_role
        person = (body.get("user") if body is not None else None) or user
    if role not in planner.roles:                        # fail-closed（§十二）
        raise HTTPException(401, f"未知角色：{role}")
    return role, person, planner
