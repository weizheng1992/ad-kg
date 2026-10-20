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

    def test_实体属性证据与黑名单(self):
        """属性型问题（target_age）由 entity 证据项可答；deny_properties 在该出口执行。"""
        import os

        from adkg.guards.permission import PermissionPlanner
        from adkg.retrieval.graph_search import search
        from adkg.store.graph import GraphStore

        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        planner = PermissionPlanner(ROOT / "ontology/permissions.yaml", graph=g)
        out = search("喵汪到家App 适合哪个年龄？", planner.plan("management"), g)
        ents = {e["ref"]: e["props"] for e in out["evidence"] if e["type"] == "entity"}
        assert ents.get("Product:P06", {}).get("target_age") == "22-40"
        ae_out = search("Case:C-2025-006 预算多少", planner.plan("ae"), g)
        case_props = next((e["props"] for e in ae_out["evidence"]
                           if e["type"] == "entity" and e["ref"] == "Case:C-2025-006"), {})
        assert "bd_budget" not in case_props and "stage" in case_props   # 黑名单只拦指定属性
        g.close()

    def test_外部角色属性白名单(self):
        """client 只许 Case.stage / Campaign.status（§12.4 fail-closed），其余属性在证据出口剥掉。"""
        import os

        from adkg.guards.permission import PermissionPlanner
        from adkg.retrieval.graph_search import search
        from adkg.store.graph import GraphStore

        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        planner = PermissionPlanner(ROOT / "ontology/permissions.yaml", graph=g)
        out = search("Case:C-2025-011 的状态", planner.plan("client", person="Person:client_a"), g)
        case_props = next((e["props"] for e in out["evidence"]
                           if e["type"] == "entity" and e["ref"].startswith("Case:")), None)
        assert case_props is not None
        assert set(case_props) <= {"stage"}              # 白名单内属性才可见
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
        assert rows and "cpa" in rows[0] and rows[0]["creative_id"]

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
        assert "case_id IN (" in sql                          # 闸 4：谓词注入（案例级）
        out = run("上月 CPA 最差的素材", plan, os.environ["ADKG_PG_RO_DSN"])
        rows = out["evidence"][0]["rows"]
        # 案例级谓词下：客户能看到自己品牌（B04=案例 003/011/019）的 matched 行，
        # 但不得出现他牌案例（如 005/006）的素材——行级权限的正行为
        theirs = {r[0] for r in [(c,) for c in []]}
        bad = [r for r in rows if str(r.get("creative_id", "")).startswith(
            ("Creative:C-2025-005", "Creative:C-2025-006", "Creative:C-2025-002"))]
        assert not bad, f"越权：{bad}"
        g.close()

    def test_创意角色列白名单_无cpa(self):
        from adkg.guards.permission import PermissionPlanner
        from adkg.retrieval.text2sql import build_sql

        planner = PermissionPlanner(ROOT / "ontology/permissions.yaml")
        plan = planner.plan("creative")
        sql, _ = build_sql("上月 CPA 最差的素材", plan)
        assert "cpa" not in sql                             # deny cost 派生联动（§12.4）


class TestTopMetric模板:
    """口径感知 top-N（§六 Metric）：指标词/方向/平台/时间窗的纯函数解析。"""

    def _plan(self):
        from adkg.models import PermissionPlan
        return PermissionPlan(metadata_filter={"entity_class__in": ["Metric", "Creative"]},
                              allowed_columns=["cost", "impressions", "clicks",
                                               "conversions", "ctr", "cvr", "cpa", "cpm"])

    def test_点击率最好_抖音_上月(self):
        from adkg.retrieval.text2sql import build_sql
        sql, p = build_sql("上个月抖音的点击率最好的素材", self._plan())
        assert p["metric"] == "ctr" and p["direction"] == "DESC"    # 比率型越高越好
        assert p["platform"] == "douyin" and p["window"]
        # 聚合口径铁律：比率型 = 汇总比 sum(clicks)/sum(impressions)，非 avg 行比率
        assert "platform = 'douyin'" in sql and "sum(clicks)" in sql and "BETWEEN" in sql

    def test_案例粒度上卷(self):
        from adkg.retrieval.text2sql import build_sql
        sql, p = build_sql("各案例的平均转化率是多少", self._plan())
        assert p.get("group") == "case_id" and p["metric"] == "cvr"
        assert "SELECT case_id" in sql and "sum(conversions)" in sql
        _, p2 = build_sql("CPA 最差的案例", self._plan())
        assert p2.get("group") == "case_id" and p2["metric"] == "cpa"

    def test_cpa最好方向反转(self):
        from adkg.retrieval.text2sql import build_sql
        _, p = build_sql("CPA 最好的素材", self._plan())
        assert p["metric"] == "cpa" and p["direction"] == "ASC"     # 成本型越低越好

    def test_小红书转化率最差(self):
        from adkg.retrieval.text2sql import build_sql
        sql, p = build_sql("小红书转化率最差的素材有哪些", self._plan())
        assert p["metric"] == "cvr" and p["direction"] == "ASC" and p["platform"] == "xhs"
        assert "platform = 'xhs'" in sql


class Test五道闸校验:
    """LLM 生成 SQL 的静态闸门（§7.3：不信任生成的 SQL）。"""

    def _plan(self):
        from adkg.models import PermissionPlan
        return PermissionPlan(allowed_columns=["cost", "ctr", "cvr", "cpa", "conversions"])

    def test_合法生成通过并强制LIMIT(self):
        from adkg.retrieval.text2sql import validate_sql
        err, fixed = validate_sql(
            "SELECT brand_id, sum(cost) FROM unified_metrics GROUP BY 1", self._plan())
        assert err is None and "LIMIT 50" in fixed

    def test_写操作与多语句与他表拒绝(self):
        from adkg.retrieval.text2sql import validate_sql
        for bad in ("DELETE FROM unified_metrics",
                    "SELECT 1; SELECT 2",
                    "SELECT * FROM provenance",
                    "SELECT pg_sleep(10)"):
            err, _ = validate_sql(bad, self._plan())
            assert err, bad

    def test_白名单外列拒绝(self):
        from adkg.retrieval.text2sql import validate_sql
        err, _ = validate_sql(
            "SELECT gross_margin FROM unified_metrics LIMIT 5", self._plan())
        assert err and "gross_margin" in err

    def test_谓词强制包裹(self):
        from adkg.retrieval.text2sql import enforce_predicate
        from adkg.models import PermissionPlan
        plan = PermissionPlan(allowed_columns=["cost"],
                              sql_predicate="brand_id IN ('B04')")
        wrapped = enforce_predicate("SELECT platform, sum(cost) FROM unified_metrics LIMIT 5", plan)
        assert wrapped.startswith("SELECT * FROM (") and "brand_id IN ('B04')" in wrapped
        # 已含 brand_id 的不再包
        assert enforce_predicate("SELECT brand_id FROM unified_metrics", plan) == \
            "SELECT brand_id FROM unified_metrics"

    def test_生成失败回落模板语义(self):
        from adkg.retrieval.text2sql import generate_sql
        assert generate_sql(lambda s, u: (_ for _ in ()).throw(RuntimeError("x")),
                            "任何问题", self._plan()) is None
        # 返回危险 SQL 也被闸门拒
        assert generate_sql(lambda s, u: {"sql": "DROP TABLE chunks"}, "q", self._plan()) is None

    def test_点名素材必须落在该素材(self):
        # 口径闸：全局均值冒充单素材答案 → 弃用生成回模板（G08/G31/G35 实测教训）
        from adkg.retrieval.text2sql import _named_creative_hit
        good = ("SELECT creative_id, round(sum(cost)::numeric / NULLIF(sum(conversions), 0), 2) AS cpa"
                " FROM unified_metrics"
                " WHERE creative_id = 'Creative:C-2025-003-cp1-cr1' LIMIT 5")
        bad = ("SELECT round(avg(cpa)::numeric, 2) AS avg_cpa"
               " FROM unified_metrics LIMIT 5")
        q = "Creative:C-2025-003-cp1-cr1 的平均 CPA 多少？"
        assert _named_creative_hit(q, good)
        assert not _named_creative_hit(q, bad)
        # creative_id 只在 WHERE（如 IS NOT NULL）不在 SELECT → 证据无实体，仍拒
        where_only = ("SELECT round(avg(cpa)::numeric, 2) AS avg_cpa FROM unified_metrics"
                      " WHERE creative_id IS NOT NULL LIMIT 5")
        assert not _named_creative_hit(q, where_only)
        assert _named_creative_hit("上月 CPA 最差的素材有哪些？", bad)   # 未点名不设限

    def test_本体ID连字符叫法可识别(self):
        from adkg.retrieval.text2sql import _named_creative_of
        assert _named_creative_of("Creative:C-2025-003-cp1-cr1 的平均 CPA 多少？") == \
            "C-2025-003-cp1-cr1"
        assert _named_creative_of("creative_992 的 CPA 是多少") == "creative_992"
        assert _named_creative_of("上月 CPA 最差的素材") is None

    def test_点名素材走单素材模板(self):
        from adkg.retrieval.text2sql import build_sql
        sql, p = build_sql("Creative:C-2025-003-cp1-cr1 的平均 CPA 多少？", self._plan())
        # ID 走参数绑定（%(ids)s），SQL 里有 creative_id 列
        assert p["ids"] == ["Creative:C-2025-003-cp1-cr1"] and "creative_id" in sql


class Test语义不变量注入:
    def test_unmatched条件强制(self):
        from adkg.retrieval.text2sql import enforce_semantics
        # 无 WHERE → 注入
        assert "WHERE NOT unmatched" in enforce_semantics(
            "SELECT brand_id FROM unified_metrics GROUP BY 1 LIMIT 5")
        # 有 WHERE → AND 进去
        out = enforce_semantics(
            "SELECT brand_id FROM unified_metrics WHERE platform = 'douyin' LIMIT 5")
        assert "NOT unmatched AND platform" in out.replace("  ", " ")
        # 已有 → 不动
        assert enforce_semantics(
            "SELECT 1 FROM unified_metrics WHERE NOT unmatched") == \
            "SELECT 1 FROM unified_metrics WHERE NOT unmatched"
