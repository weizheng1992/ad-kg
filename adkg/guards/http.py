"""认证与身份上下文收口（README §9.1，2026-10-23 起）：token→role+绑定 person / web 会话 / dev 兜底。

各端点（ask / graph / agent / ingest / creative / actions / guideline）不再自抄认证块
——散抄曾致漏门（/ingest/assertion 无角色门即实例）。约定见 §12.4：token 路 person
一律取 bindings 绑定值，body/query 自报仅补缺（多绑定角色）；dev 路
（ADKG_DEV_AUTH=off）允许 body/query 传 role/user。角色合法性预检（§十二
fail-closed）也在此统一做——dev 路可传任意值，未知即 401。

web 会话 cookie 路（spec 2026-10-24 §2）：Bearer 缺席时按 adkg_session 解析
app_session → 账号 role/person；优先级 token > cookie > dev。

planner / graph 惰性单例挂 app.state（2026-10-24 收敛：本模块曾反向 import
routes.ask._planner，且 planner 与 actions 各建一份 GraphStore）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pathlib import Path

from fastapi import HTTPException, Request

from adkg.guards.auth import AuthService

if TYPE_CHECKING:                                    # 注解静态可见（惰性 import 防环不动）
    from adkg.guards.permission import PermissionPlanner
from adkg.guards.rbac import custom_base
from adkg.guards.sessions import SESSION_COOKIE, resolve_session


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


def get_llm(request: Request):
    """惰性 LLM 客户端（app.state.llm，与 get_graph/get_planner 同族）；探测失败
    不缓存（限流是暂态，下一问重试，§7.2）。2026-10-28 自 ask.py 下沉——曾由
    四个 route 跨模块 import 私有符号（§9.1 import 只向下）。
    tests 预置 app.state.llm 即命中缓存分支跳过探测（test_creative/test_agent）。"""
    if not hasattr(request.app.state, "llm"):
        request.app.state.llm = None
    if request.app.state.llm is None and request.app.state.env.get("ADKG_LLM_API_KEY"):
        try:
            from adkg.llm import LLMClient
            client = LLMClient()
            client.chat_json("ping", '返回 {"ok": true}', timeout=12, max_retries=0)
            request.app.state.llm = client
        except Exception:
            return None                                  # 本问降级，不缓存失败
    return request.app.state.llm


def get_embed_fn(request: Request):
    """本地 bge 嵌入独立于 chat 探测（失败域解耦，§7.2）：嵌入与 chat 端点零依赖，
    探测失败曾级联杀掉 vector 路（2026-10-23 检查实锤）。常驻缓存（本地模型可靠）。"""
    if not hasattr(request.app.state, "embedder"):
        try:
            from adkg.llm import LLMClient
            request.app.state.embedder = LLMClient()
        except Exception:
            request.app.state.embedder = None
    return request.app.state.embedder.embed if request.app.state.embedder else None


def require_casegen_role(request: Request, body: dict, authorization: str | None,
                         *, commit: bool = False) -> tuple[str, str | None]:
    """认证 + 案例生成角色门（token 反查优先，dev 模式 body 兜底，fail-closed）；
    person 一并返回（token 路取绑定值——审计 user_id 用，2026-10-24 起）。
    commit=True（case-commit 专用）叠加 create_case 动作门——§12.4「/ingest/*
    写端点要求 actions 含对应写动作」，与 /ingest/assertion 同款；角色门只是
    预检快失败，写门以动作判定为准。2026-10-28 自 ingest.py 下沉（creative.py
    曾跨 route import 此私有函数）。"""
    from adkg.guards.rbac import CASEGEN_ROLES, can_commit_case
    role, person, planner = resolve_identity(request, authorization, body=body)
    if role not in CASEGEN_ROLES:
        raise HTTPException(403, f"角色 {role} 无案例生成权限（允许：{sorted(CASEGEN_ROLES)}）")
    if commit and not can_commit_case(planner, role):
        raise HTTPException(403, f"角色 {role} 无案例提交权限（actions 不含 create_case，§12.4 动作门）")
    return role, person


def resolve_identity(request: Request, authorization: str | None, *,
                     role: str | None = None, user: str | None = None,
                     body: dict | None = None, dev_default: str | None = None
                     ) -> tuple[str, str | None, "PermissionPlanner"]:
    """统一认证解析：返回 (role, person, planner)；未认证/未知角色抛 401。

    - token 路：role 取 token 映射，person 取该 role 的唯一 bindings 绑定值
      （缺省回退 body/query 自报）；dev 路入参不采信
    - cookie 路：Bearer 缺席时 adkg_session → app_user 的 role/person
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
        sess = resolve_session(env, request.cookies.get(SESSION_COOKIE))
        if sess:
            # RBAC（§18）：cookie 角色可为自定义角色——数据面映射基角色后放行
            r = sess["role"]
            if r in planner.roles:
                return r, sess["person"], planner
            base = custom_base(env, r)
            if base and base in planner.roles:
                return base, sess["person"], planner
        dev_role = (body.get("role") if body is not None else None) or role or dev_default
        if not (env.get("ADKG_DEV_AUTH") == "off" and dev_role):
            raise HTTPException(401, "缺有效 service token（生产经网关注入；本地 "
                                     "ADKG_DEV_AUTH=off 可传 role）")
        role = dev_role
        person = (body.get("user") if body is not None else None) or user
    if role not in planner.roles:                        # fail-closed（§十二）
        # 自定义角色（spec §18 RBAC）：数据面映射到基角色——菜单/按钮权限在 DB
        base = custom_base(env, role)
        if base is None or base not in planner.roles:
            raise HTTPException(401, f"未知角色：{role}")
        role = base
    return role, person, planner
