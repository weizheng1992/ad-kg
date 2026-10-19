"""三路检索 + assemble 测试：assemble 离线；graph / text2sql 打真库。"""
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from adkg.retrieval.assemble import assemble


class TestAssemble:
    def _decision(self):
        from adkg.retrieval.router import rule_route
        return rule_route("上月 CPA 最差的素材")

    def test_合并去重与得分(self):
        plan = type("P", (), {"mask_rules": []})()
        results = {
            "t": {"route": "text2sql", "confidence": 0.9,
                  "evidence": [{"type": "fact", "ref": "unified_metrics · x", "rows": []}],
                  "filtered": 3},
            "g": {"route": "graph", "confidence": 0.85,
                  "evidence": [{"type": "relation", "ref": "(a)-[:r]->(b)"},
                               {"type": "relation", "ref": "unified_metrics · x"}]},
        }
        out = assemble(results, plan, self._decision())
        assert len(out["evidence"]) == 2                    # ref 去重
        assert out["permission_applied"] is True
        assert {"route": "text2sql", "score": 0.9} in out["routes_used"]

    def test_缺席路进degraded(self):
        plan = type("P", (), {"mask_rules": []})()
        out = assemble({"v": {"route": "vector", "confidence": 0.5,
                              "evidence": [], "degraded": True}}, plan, self._decision())
        assert out["degraded"] == ["vector"]

    def test_外部角色人名掩码(self):
        plan = type("P", (), {"mask_rules": ["person_name"]})()
        results = {"g": {"route": "graph", "confidence": 0.9, "evidence": [
            {"type": "relation", "ref": "(Person:li)-[:responsible_for]->(Case:C-1)",
             "quote": "对接人李昂负责"}]}}
        out = assemble(results, plan, self._decision(), person_names=["李昂"])
        ev = out["evidence"][0]
        assert "李昂" not in ev["quote"] and "＊＊" in ev["quote"]
        assert "Person:li" in ev["ref"]                     # ID 不掩，姓名掩（§12.6）


def _dbs_up() -> bool:
    try:
        import os

        import psycopg
        with psycopg.connect(os.environ["ADKG_PG_DSN"], connect_timeout=3):
            return True
    except Exception:
        return False


@pytest.mark.skipif(not _dbs_up(), reason="数据库不在线")
class TestGraphSearch:
    def test_实体定位与邻域(self):
        import os

        from adkg.guards.permission import PermissionPlanner
        from adkg.retrieval.graph_search import search
        from adkg.store.graph import GraphStore

        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        planner = PermissionPlanner(ROOT / "ontology/permissions.yaml", graph=g)
        out = search("李昂负责哪些 Case？", planner.plan("management"), g)
        refs = " ".join(e["ref"] for e in out["evidence"])
        assert "Person:li" in refs and "responsible_for" in refs
        g.close()

    def test_可见集过滤_客户不见他牌(self):
        import os

        from adkg.guards.permission import PermissionPlanner
        from adkg.retrieval.graph_search import search
        from adkg.store.graph import GraphStore

        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        planner = PermissionPlanner(ROOT / "ontology/permissions.yaml", graph=g)
        client_plan = planner.plan("client", person="Person:client_a")
        out = search("Case:C-2025-006", client_plan, g)     # B06 的案例（越权目标）
        assert out["evidence"] == [] and out["filtered"] >= 1
        g.close()


@pytest.mark.skipif(not _dbs_up(), reason="数据库不在线")
class TestText2SQL:
    def test_top_cpa模板(self):
        import os

        from adkg.guards.permission import PermissionPlanner
        from adkg.retrieval.text2sql import run

        planner = PermissionPlanner(ROOT / "ontology/permissions.yaml")
        out = run("上月 CPA 最差的素材", planner.plan("management"),
                  os.environ["ADKG_PG_RO_DSN"])
        rows = out["evidence"][0]["rows"]
        assert rows and "avg_cpa" in rows[0] and rows[0]["creative_id"]

    def test_客户行过滤与列白名单(self):
        import os

        from adkg.guards.permission import PermissionPlanner
        from adkg.retrieval.text2sql import build_sql, run
        from adkg.store.graph import GraphStore

        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        planner = PermissionPlanner(ROOT / "ontology/permissions.yaml", graph=g)
        plan = planner.plan("client", person="Person:client_a")
        sql, _ = build_sql("消耗多少", plan)
        assert "brand_id IN ('B04')" in sql                 # 闸 4：谓词注入
        out = run("上月 CPA 最差的素材", plan, os.environ["ADKG_PG_RO_DSN"])
        assert out["evidence"][0]["rows"] == []             # B04 无 matched 事实行 → 空集不越权
        g.close()

    def test_创意角色列白名单_无cpa(self):
        from adkg.guards.permission import PermissionPlanner
        from adkg.retrieval.text2sql import build_sql

        planner = PermissionPlanner(ROOT / "ontology/permissions.yaml")
        plan = planner.plan("creative")
        sql, _ = build_sql("上月 CPA 最差的素材", plan)
        assert "cpa" not in sql                             # deny cost 派生联动（§12.4）
