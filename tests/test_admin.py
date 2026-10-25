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


@pytest.mark.skipif(not _pg_up(), reason="Postgres 不在线")
class TestReviewResolve:
    """人审处置闭环（spec §15）：冲突 → approve 落图进源 + 快照 + 状态流转。"""

    CID = "Creator:pytest-rq"

    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def _cleanup(self):
        import psycopg
        from adkg.store.graph import GraphStore
        import os
        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        with g.session() as s:
            s.run(f"MATCH (n:Entity {{id: '{self.CID}'}}) DETACH DELETE n")
        with psycopg.connect(os.environ["ADKG_PG_DSN"], autocommit=True) as c, c.cursor() as cur:
            cur.execute("DELETE FROM review_queue WHERE payload->>'entity' = %s", (self.CID,))
            cur.execute("DELETE FROM creator_quote_history WHERE creator_id = %s", (self.CID,))

    def test_冲突采纳闭环(self):
        import io
        import json as j

        import psycopg
        from openpyxl import Workbook
        client = self._client()
        self._cleanup()
        # ① xlsx 导入建号（official_doc/60，spec §15）
        wb = Workbook(); ws = wb.active
        ws.append(["name", "platform", "niches", "followers", "quote_20s", "creator_id"])
        ws.append(["人审测试达人", "douyin", "测试|人审", 50000, 8000, self.CID])
        buf = io.BytesIO(); wb.save(buf); buf.seek(0)
        r = client.post("/creators/import", params={"role": "management", "user": "Person:chen"},
                        files={"file": ("t.xlsx", buf, "application/vnd.ms-excel")})
        assert r.json()["created"] == 1, r.text
        # ② 手工录入（20）撞高权威 → conflict 入队
        r = client.post("/creators", params={"role": "management", "user": "Person:chen"},
                        json={"name": "人审测试达人", "platform": "douyin", "niches": "测试",
                              "quote_20s": 19999, "creator_id": self.CID})
        assert r.json()["outcome"] == "conflict"
        with psycopg.connect(os.environ["ADKG_PG_DSN"]) as c, c.cursor() as cur:
            cur.execute("SELECT id FROM review_queue WHERE kind='conflict'"
                        " AND status='open' AND payload->>'entity' = %s", (self.CID,))
            qid = str(cur.fetchone()[0])
        # ③ reject 先行：维持现状（驳回后原行 status=rejected，同源可再挂新冲突）
        r = client.post(f"/admin/review-queue/{qid}/resolve", params={"role": "admin"},
                        json={"decision": "rejected"})
        assert r.status_code == 200 and r.json()["applied"] is False
        det = client.get(f"/creators/{self.CID}",
                         params={"role": "management", "user": "Person:chen"}).json()
        assert det["creator"]["quote_20s"] == 8000            # 驳回维持导入值
        # ④ 再造冲突（库内仍是导入的 60 > 手工 20）→ approve → 落图进源 + 报价快照
        client.post("/creators", params={"role": "management", "user": "Person:chen"},
                    json={"name": "人审测试达人", "platform": "douyin", "niches": "测试",
                          "quote_20s": 19999, "creator_id": self.CID})
        with psycopg.connect(os.environ["ADKG_PG_DSN"]) as c, c.cursor() as cur:
            cur.execute("SELECT id FROM review_queue WHERE kind='conflict'"
                        " AND status='open' AND payload->>'entity' = %s", (self.CID,))
            qid2 = str(cur.fetchone()[0])
        r = client.post(f"/admin/review-queue/{qid2}/resolve",
                        params={"role": "admin"},
                        json={"decision": "approved", "note": "测试采纳"})
        body = r.json()
        assert r.status_code == 200 and body["applied"] is True
        det = client.get(f"/creators/{self.CID}",
                         params={"role": "management", "user": "Person:chen"}).json()
        assert det["creator"]["quote_20s"] == 19999
        assert any(h["source_type"] == "conversation" for h in det["quote_history"])
        with psycopg.connect(os.environ["ADKG_PG_DSN"]) as c, c.cursor() as cur:
            cur.execute("SELECT status FROM review_queue WHERE id = %s", (qid2,))
            assert cur.fetchone()[0] == "approved"
        self._cleanup()


@pytest.mark.skipif(not _pg_up(), reason="Postgres 不在线")
class TestAccountAdmin:
    """人员管理（spec §16）：开户/改密吊销/启停——写操作仅 admin。"""

    U = "pytest_acct"

    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def _cleanup(self):
        import psycopg
        with psycopg.connect(os.environ["ADKG_PG_DSN"], autocommit=True) as c, c.cursor() as cur:
            cur.execute("DELETE FROM app_session WHERE user_id = 'u_pytest_acct'")
            cur.execute("DELETE FROM app_user WHERE username = %s", (self.U,))

    def test_闭环(self):
        client = self._client()
        self._cleanup()
        # management 只读 → 403
        assert client.post("/admin/accounts",
                           params={"role": "management", "user": "Person:chen"},
                           json={"username": self.U, "password": "x", "role": "ae"}
                           ).status_code == 403
        # admin 开户（角色过 permissions 合法集；坏角色 422；重号 409）
        ok = client.post("/admin/accounts", params={"role": "admin"},
                         json={"username": self.U, "password": "pw-1",
                               "display_name": "测试账号", "role": "optimizer",
                               "person": "Person:zhao"})
        assert ok.status_code == 200, ok.text
        assert client.post("/admin/accounts", params={"role": "admin"},
                           json={"username": self.U, "password": "x", "role": "ae"}
                           ).status_code == 409
        assert client.post("/admin/accounts", params={"role": "admin"},
                           json={"username": "z", "password": "x", "role": "nope"}
                           ).status_code == 422
        # 新账号能登录（dev 关 → 走 cookie 路）
        r = client.post("/auth/login", json={"username": self.U, "password": "pw-1"})
        assert r.status_code == 200 and r.json()["role"] == "optimizer"
        client.cookies.clear()      # cookie 优先于 dev 参数（设计如此）：admin 操作先退出登录态
        # 改密 → 旧会话吊销，新密码可登录
        assert client.post("/admin/accounts/u_pytest_acct/reset-password",
                           params={"role": "admin"},
                           json={"password": "pw-2"}).status_code == 200
        assert client.get("/auth/me").status_code == 401
        assert client.post("/auth/login",
                           json={"username": self.U, "password": "pw-1"}).status_code == 401
        assert client.post("/auth/login",
                           json={"username": self.U, "password": "pw-2"}).status_code == 200
        # 停用 → 登录拒绝；启用恢复
        client.cookies.clear()
        assert client.post("/admin/accounts/u_pytest_acct/toggle", params={"role": "admin"},
                           json={"disabled": True}).status_code == 200
        assert client.post("/auth/login",
                           json={"username": self.U, "password": "pw-2"}).status_code == 401
        client.cookies.clear()
        assert client.post("/admin/accounts/u_pytest_acct/toggle", params={"role": "admin"},
                           json={"disabled": False}).status_code == 200
        assert client.post("/auth/login",
                           json={"username": self.U, "password": "pw-2"}).status_code == 200
        self._cleanup()


@pytest.mark.skipif(not _pg_up(), reason="Postgres 不在线")
class TestMenus:
    """菜单管理（spec §17）：懒播种默认 + 角色过滤 + admin 保存 + 防自锁。"""

    def _client(self):
        from fastapi.testclient import TestClient
        from adkg.api.main import create_app
        return TestClient(create_app({**os.environ, "ADKG_DEV_AUTH": "off"}))

    def test_播种与角色过滤(self):
        client = self._client()
        r = client.get("/menus", params={"role": "finance", "user": "Person:zhou"})
        assert r.status_code == 200
        labels = [m["path"] for m in r.json()["items"]]
        assert "/settlements" in labels and "/creators" in labels
        assert "/menus" not in labels and "/people" not in labels   # finance 不可见管理入口
        r = client.get("/menus", params={"role": "admin"})
        assert "/menus" in [m["path"] for m in r.json()["items"]]

    def test_保存与防自锁(self):
        import psycopg
        client = self._client()
        assert client.get("/admin/menus", params={"role": "management"}).status_code == 403
        items = client.get("/admin/menus", params={"role": "admin"}).json()["items"]
        # 改：财务结算对 optimizer 也可见；「案例」改名；图谱停用
        for m in items:
            if m["path"] == "/settlements":
                m["roles"] = ["management", "finance", "optimizer"]
            if m["path"] == "/cases":
                m["label"] = "案例库"
            if m["path"] == "/graph":
                m["enabled"] = False
        r = client.put("/admin/menus", params={"role": "admin"}, json={"items": items})
        assert r.status_code == 200
        got = client.get("/menus", params={"role": "optimizer"}).json()["items"]
        assert "/settlements" in [m["path"] for m in got]           # 新增可见生效
        assert "/graph" not in [m["path"] for m in got]              # 停用生效
        assert next(m for m in got if m["path"] == "/cases")["label"] == "案例库"
        # 防自锁：把 /menus 从 admin 摘除 → 422
        for m in items:
            if m["path"] == "/menus":
                m["roles"] = ["management"]
        assert client.put("/admin/menus", params={"role": "admin"},
                          json={"items": items}).status_code == 422
        # 还原默认（重播种语义：直接整批 PUT 回默认 roles/enabled）
        items = client.get("/admin/menus", params={"role": "admin"}).json()["items"]
        default = client.get("/menus", params={"role": "finance"}).json()  # noqa: F841
        import json as j
        from adkg.api.routes.menus import DEFAULT_MENUS
        restored = [{"path": p, "label": l, "icon": i, "roles": r.split(","),
                     "sort": s, "enabled": True} for p, l, i, r, s in DEFAULT_MENUS]
        assert client.put("/admin/menus", params={"role": "admin"},
                          json={"items": restored}).status_code == 200
