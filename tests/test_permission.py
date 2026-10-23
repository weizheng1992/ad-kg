"""guards 认证 + PermissionPlan 唯一翻译点（Phase 4 核心，README §9.1/§12.4/§7.3）。

offline：token→role 解析、类白名单、指标列派生联动、外部角色 fail-closed、脱敏规则；
live（图在线）：row_filter 图展开成可见 ID 集——optimizer 只见自己负责链、
client 只见 external_for 锚定的品牌子图、全局类豁免。
"""
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from adkg.guards.auth import AuthService
from adkg.guards.permission import PermissionPlanner, load_permissions

PERMS = load_permissions(ROOT / "ontology" / "permissions.yaml")
SCHEMA_PATH = ROOT / "ontology" / "schema.yaml"


class TestAuthService:
    def test_env_token解析到role(self):
        auth = AuthService({"ADKG_TOKEN_OPTIMIZER": "t-opt", "ADKG_TOKEN_CLIENT": "t-cli"})
        assert auth.resolve("Bearer t-opt") == ("optimizer", None)
        assert auth.resolve("Bearer t-cli") == ("client", None)

    def test_未知token与坏格式拒绝(self):
        auth = AuthService({"ADKG_TOKEN_OPTIMIZER": "t-opt"})
        assert auth.resolve("Bearer nope") is None
        assert auth.resolve("t-opt") is None            # 缺 Bearer 前缀


class TestPermissionPlanner:
    def _planner(self):
        return PermissionPlanner(ROOT / "ontology" / "permissions.yaml")

    def test_类白名单进metadata_filter(self):
        plan = self._planner().plan("creative")
        assert "Creative" in plan.metadata_filter["entity_class__in"]
        assert "Case" not in plan.metadata_filter["entity_class__in"]

    def test_指标列派生联动与白名单(self):
        p = self._planner().plan("creative")
        assert set(p.allowed_columns) >= {"ctr", "cvr", "conversions", "cost", "cpa"} or \
            "cost" not in p.allowed_columns             # deny cost 必然连带 cpa/roi 不在
        assert "cpa" not in p.allowed_columns and "roi" not in p.allowed_columns

        pc = self._planner().plan("client")
        # 2026-10-21 夜检 B7：单数 conversion 对不上统一列名 conversions，客户看不到转化数
        assert set(pc.allowed_columns) == {"cost", "ctr", "cvr", "conversions"}

    def test_外部角色带脱敏规则_内部不带(self):
        assert self._planner().plan("client").mask_rules == ["person_name"]
        assert self._planner().plan("optimizer").mask_rules == []

    def test_全局类豁免_不进可见集约束(self):
        plan = self._planner().plan("optimizer")
        assert "Guideline" in plan.metadata_filter["entity_class__in"]  # 全局类在类白名单内全量可见


def _graph_up() -> bool:
    try:
        import os

        from neo4j import GraphDatabase
        d = GraphDatabase.driver(os.environ["ADKG_NEO4J_URI"],
                                 auth=(os.environ["ADKG_NEO4J_USER"],
                                       os.environ["ADKG_NEO4J_PASSWORD"]))
        d.verify_connectivity()
        d.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _graph_up(), reason="Neo4j 不在线")
class TestRowFilter图展开:
    def _planner(self):
        import os

        from adkg.store.graph import GraphStore
        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        return PermissionPlanner(ROOT / "ontology" / "permissions.yaml", graph=g)

    def test_optimizer只见自己负责链(self):
        # seed：Person:li 负责 Case:C-2025-006（首个分配）——链上实体可见，链外不可见
        plan = self._planner().plan("optimizer", person="Person:li")
        vis = plan.visible_entity_ids
        assert "Case:C-2025-006" in vis
        assert "Case:C-2025-005" not in vis               # 别人的案例
        assert any(i.startswith("Campaign:C-2025-006") for i in vis)

    def test_client只见锚定品牌子图(self):
        # client_a external_for Brand:B04；B04 的案例 = 003/011/019（i%8==3）
        plan = self._planner().plan("client", person="Person:client_a")
        vis = plan.visible_entity_ids
        assert "Brand:B04" in vis
        assert "Case:C-2025-003" in vis and "Case:C-2025-011" in vis
        assert "Case:C-2025-005" not in vis                # Brand:B06 的案例，零可见
        assert plan.sql_predicate.startswith("case_id IN (")   # 案例级谓词（比品牌级更严）
        assert "Case:C-2025-003" in plan.sql_predicate

    def test_无row_filter的角色全量可见(self):
        plan = self._planner().plan("management")
        assert plan.visible_entity_ids == frozenset()      # 空 = 不约束
        assert plan.sql_predicate == ""

    def test_row_filter角色缺person_fail_closed(self):
        """2026-10-23 §12.4：row_filter 角色无 person / 图中无此人 → deny-all，不再静默跳过。"""
        p = self._planner().plan("optimizer")               # 无 person
        assert p.deny_all and p.sql_predicate == "1=0"
        p2 = self._planner().plan("client", person="Person:nope")   # 图中无此人
        assert p2.deny_all

    def test_bound_person取唯一绑定(self):
        pl = self._planner()
        assert pl.bound_person("optimizer") == "Person:li"
        assert pl.bound_person("client") == "Person:client_a"
