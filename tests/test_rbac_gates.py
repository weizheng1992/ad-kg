"""RBAC 门语义回归（2026-10-26 夜检三缺陷 + §19 事务化）：真库集成，不在线跳过。

三缺陷（534449a 线二修复）的本意是生产会话路（cookie 携带原始角色）——dev 路
（ADKG_DEV_AUTH=off 传 role）在 resolve_identity 里就把自定义角色映射成基角色，
display_role 判不出差别，所以本文件一律 /auth/login 拿会话再打端点：

- base=admin 的自定义角色不得借映射获得角色配置写权（require_system_admin 硬判
  display_role；读门仍按自身 admin_view 配置放行）
- 自定义角色**角色级零记录**才整体回落基角色；有任意自身配置即白名单语义——
  权限树取消勾选必须真实收权（旧逐 action 回落使取消勾选无效）
- admin 播种 action 自留权不可摘（防自锁 422）；未传 actions = 保持不变
- PUT /admin/permissions 单事务双落：菜单校验失败时角色改动一并回滚
"""
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PROBE = "rbac_gate_probe"          # 自定义角色名（测试自建自删）
PROBE_USER = "rbac_probe"          # 绑定探针角色的账号


def _pg_up() -> bool:
    try:
        import psycopg
        with psycopg.connect(os.environ["ADKG_PG_DSN"], connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _pg_up(), reason="Postgres 不在线")
class TestRbacGateSemantics:
    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def _cleanup(self):
        import psycopg
        with psycopg.connect(os.environ["ADKG_PG_DSN"]) as c, c.cursor() as cur:
            cur.execute("DELETE FROM app_session WHERE user_id = 'u_rbac_probe'")
            cur.execute("DELETE FROM app_user WHERE username = %s", (PROBE_USER,))
            cur.execute("DELETE FROM app_role_action WHERE role = %s", (PROBE,))
            cur.execute("DELETE FROM app_role WHERE name = %s", (PROBE,))
            c.commit()

    def _mk_probe(self, client, *, base: str, actions: list[str]):
        self._cleanup()
        r = client.post("/admin/roles", params={"role": "admin"},
                        json={"name": PROBE, "base_role": base, "actions": actions})
        assert r.status_code == 200, r.text

    def _login_probe(self, client) -> None:
        """直接插账号绑定探针角色 → /auth/login 拿会话 cookie（生产路）。"""
        import psycopg
        from adkg.guards.passwords import hash_password
        with psycopg.connect(os.environ["ADKG_PG_DSN"]) as c, c.cursor() as cur:
            cur.execute(
                "INSERT INTO app_user (id, username, password_hash, display_name, role)"
                " VALUES ('u_rbac_probe', %s, %s, '门语义探针', %s)"
                " ON CONFLICT (username) DO UPDATE SET role = EXCLUDED.role,"
                " disabled = false",
                (PROBE_USER, hash_password("rbac-probe-pw"), PROBE))
            c.commit()
        r = client.post("/auth/login", json={"username": PROBE_USER,
                                             "password": "rbac-probe-pw"})
        assert r.status_code == 200, r.text

    # ---------------------------------------------------- base=admin 写门绕过
    def test_base_admin自定义角色_角色配置写403_读按自身配置(self):
        client = self._client()
        self._mk_probe(client, base="admin", actions=["admin_view"])
        self._login_probe(client)
        # 读门：探针自身配置了 admin_view → 管理后台可读（display_role=probe）
        assert client.get("/admin/permission-matrix").status_code == 200
        # 写门：base=admin 也不得创建/改角色——require_system_admin 硬判 display_role
        r = client.post("/admin/roles",
                        json={"name": "rbac_probe_escalate", "base_role": "ae",
                              "actions": []})
        assert r.status_code == 403, r.text
        r = client.put("/admin/roles/admin", json={"actions": ["admin_view"]})
        assert r.status_code == 403
        r = client.delete("/admin/roles/ae")
        assert r.status_code == 403
        # 数据面：resolve_identity 映射基角色 admin——数据接口正常（非 401）
        assert client.get("/cases").status_code == 200
        self._cleanup()

    # ---------------------------------------------------- 取消勾选真实收权
    def test_零记录回落_有配置即白名单_取消勾选收权(self):
        client = self._client()
        admin = self._client()       # 管理操作走独立 client——探针会话 cookie 会压过 dev 路 role 参数
        self._mk_probe(admin, base="management", actions=["dashboard_view"])
        self._login_probe(client)
        # 有自身配置（非零记录）→ 白名单语义：只给 dashboard_view
        assert client.get("/stats/overview").status_code == 200
        # management 播种里有 settlement_view / admin_view，但探针未勾 → 不回落
        assert client.get("/settlements").status_code == 403
        assert client.get("/admin/audit").status_code == 403
        # 勾上 → 收权再放开（真实回权）
        r = admin.put(f"/admin/roles/{PROBE}", params={"role": "admin"},
                      json={"actions": ["dashboard_view", "settlement_view"]})
        assert r.status_code == 200, r.text
        assert client.get("/settlements").status_code == 200
        # 再取消 → 再次收权（旧逐 action 回落下这里是 200，回归判别点）
        admin.put(f"/admin/roles/{PROBE}", params={"role": "admin"},
                  json={"actions": ["dashboard_view"]})
        assert client.get("/settlements").status_code == 403
        self._cleanup()

    def test_零记录整体回落基角色(self):
        client = self._client()
        self._mk_probe(client, base="finance", actions=[])   # 零记录
        self._login_probe(client)
        # §18 字面「无记录回落」= 角色级整体继承：finance 的 dashboard/settlement 都放行
        assert client.get("/stats/overview").status_code == 200
        assert client.get("/settlements").status_code == 200
        # finance 播种外（admin_view）不放行
        assert client.get("/admin/audit").status_code == 403
        self._cleanup()

    # ---------------------------------------------------- admin 自留权不可摘
    def test_admin自留权不可摘_未传actions保持不变(self):
        from adkg.guards.rbac import SYSTEM_ROLE_ACTIONS
        client = self._client()
        reserved = SYSTEM_ROLE_ACTIONS["admin"]
        # 摘任何一个自留权 → 422（防自锁）
        r = client.put("/admin/roles/admin", params={"role": "admin"},
                       json={"actions": ["admin_view"]})
        assert r.status_code == 422 and "自留权" in r.json()["detail"]
        # 未传 actions = 保持不变（缺省当空集会静默清空——一并回归）
        r = client.put("/admin/roles/admin", params={"role": "admin"},
                       json={"description": "门语义探针触碰"})
        assert r.status_code == 200, r.text
        roles = client.get("/admin/roles", params={"role": "admin"}).json()["items"]
        admin_row = next(x for x in roles if x["name"] == "admin")
        assert set(admin_row["actions"]) == set(reserved)

    # ---------------------------------------------------- 权限树单事务双落
    def test_permissions单事务_菜单校验失败角色回滚(self):
        client = self._client()
        self._mk_probe(client, base="ae", actions=["dashboard_view"])
        # 同一请求里角色 actions 改动 + 菜单白名单外 path → 422
        r = client.put("/admin/permissions", params={"role": "admin"},
                       json={"role": {"name": PROBE, "actions": ["creator_export"]},
                             "menus": {"items": [
                                 {"path": "/hack", "label": "x", "icon": "Menu",
                                  "roles": ["admin"], "sort": 0, "enabled": True}]}})
        assert r.status_code == 422
        # 事务回滚：角色动作仍是原集（不是 creator_export）
        roles = client.get("/admin/roles", params={"role": "admin"}).json()["items"]
        probe = next(x for x in roles if x["name"] == PROBE)
        assert probe["actions"] == ["dashboard_view"]
        # 合法整批保存一次通过
        menus = client.get("/admin/menus", params={"role": "admin"}).json()["items"]
        r = client.put("/admin/permissions", params={"role": "admin"},
                       json={"role": {"name": PROBE, "actions": ["creator_export"]},
                             "menus": {"items": menus}})
        assert r.status_code == 200 and r.json()["ok"], r.text
        roles = client.get("/admin/roles", params={"role": "admin"}).json()["items"]
        probe = next(x for x in roles if x["name"] == PROBE)
        assert probe["actions"] == ["creator_export"]
        self._cleanup()
