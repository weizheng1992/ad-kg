"""ontology/ 三件资产的不变量测试——README §六 / §12.2 / §12.4 的落地校验。

资产（YAML）先于代码固化，这里的断言防止资产与 models.py/README 口径漂移。
"""
from pathlib import Path

import yaml

from adkg.models import AUTHORITY_LADDER, SourceType

ROOT = Path(__file__).resolve().parents[1]


def load(rel: str) -> dict:
    with open(ROOT / rel, encoding="utf-8") as f:
        return yaml.safe_load(f)


SCHEMA = load("ontology/schema.yaml")
AUTHORITY = load("ontology/authority.yaml")
PERMISSIONS = load("ontology/permissions.yaml")

CLASSES = set(SCHEMA["classes"])
RELATIONS = {r["predicate"]: r for r in SCHEMA["relations"]}


class TestSchema:
    def test_恰好12类(self):
        assert len(CLASSES) == 12

    def test_关系端点都是已定义类(self):
        for predicate, rel in RELATIONS.items():
            assert rel["source"] in CLASSES, f"{predicate} 的 source 未定义"
            assert rel["target"] in CLASSES, f"{predicate} 的 target 未定义"

    def test_关键关系齐备(self):
        for p in ("for_brand", "belongs_to", "uses", "violates", "derived_from",
                  "responsible_for", "belongs_to_brand", "external_for",
                  "for_product", "has_product", "in_channel", "targets", "links_to",
                  "supersedes"):
            assert p in RELATIONS

    def test_外部客户锚点是外部(self):
        # 多个 Person→Brand 关系并存：内部对接人 vs 外部客户绑定，语义必须分开
        assert RELATIONS["belongs_to_brand"]["scope"] == "internal"
        assert RELATIONS["external_for"]["scope"] == "external"

    def test_case_状态机与终态(self):
        t = SCHEMA["constraints"]["case_stage"]["transitions"]
        assert t == {"proposal": ["live", "lost"],
                     "live": ["closed", "terminated"],
                     "closed": [], "lost": [], "terminated": []}
        assert set(SCHEMA["constraints"]["case_stage"]["terminal"]) == {"closed", "lost", "terminated"}

    def test_动作词表(self):
        actions = set(SCHEMA["actions"])
        assert {"read", "create_creative", "pause_campaign", "delete_creative"} <= actions

    def test_权限矩阵引用的属性都存在(self):
        # deny/allow 引用的 Class.prop 必须真的在 schema 类定义里，防止黑名单写错类名
        case_props = SCHEMA["classes"]["Case"]["properties"]
        assert {"stage", "bd_budget", "gross_margin", "settlement_status"} <= set(case_props)
        for role, cfg in PERMISSIONS["roles"].items():
            for ref in cfg.get("deny_properties", []) + cfg.get("allow_properties", []):
                cls, _, prop = ref.partition(".")
                assert cls in CLASSES, f"{role} 引用未定义类 {cls}"
                assert prop in SCHEMA["classes"][cls].get("properties", []), \
                    f"{role} 引用 {cls} 未定义属性 {prop}"


class TestAuthority:
    def test_五级查表与models完全一致(self):
        ladder = AUTHORITY["ladder"]
        assert set(ladder) == {s.value for s in SourceType}
        for st, value in ladder.items():
            assert value == AUTHORITY_LADDER[SourceType(st)], f"{st} 与 models.AUTHORITY_LADDER 漂移"

    def test_同分裁决链(self):
        # 同分比 confidence、再比 fetched_at 取新、仍不能判定标 conflicted（§12.2）
        assert AUTHORITY["tie_breaker"] == ["confidence", "fetched_at", "conflicted"]


class TestPermissions:
    ROLES = PERMISSIONS["roles"]

    def test_bindings是映射结构不含明文(self):
        for token_ref, binding in PERMISSIONS["bindings"].items():
            assert set(binding) == {"role", "person"}
            assert binding["role"] in self.ROLES
            assert binding["person"].startswith("Person:")  # token 本体在 .env，这里只有标识

    def test_角色类白名单在schema类内(self):
        for role, cfg in self.ROLES.items():
            for cls in cfg["classes"]:
                assert cls in CLASSES, f"{role} 引用了未定义类 {cls}"

    def test_动作在schema动作词表内(self):
        schema_actions = set(SCHEMA["actions"])
        for role, cfg in self.ROLES.items():
            for a in cfg["actions"]:
                assert a in schema_actions, f"{role} 引用了未定义动作 {a}"

    def test_外部角色全白名单_内部角色黑名单(self):
        client = self.ROLES["client"]
        assert "allow_properties" in client and "deny_properties" not in client  # fail-closed
        assert client["metrics_allow"], "外部角色指标列必须白名单"
        for name, cfg in self.ROLES.items():
            if cfg.get("external"):
                assert "allow_properties" in cfg
            else:
                assert "metrics_deny" in cfg or name in ("creative", "admin"), \
                    f"内部角色 {name} 缺指标列声明"

    def test_row_filter谓词都是已定义关系(self):
        # 从 row_filter 字符串解析（锚点+路径+方向记法）：表达式里所有
        # 非类名的标识符都必须是已定义关系，防手写漂移
        import re
        for role, cfg in self.ROLES.items():
            expr = cfg.get("row_filter")
            if not expr:
                continue
            tokens = set(re.findall(r"[A-Za-z_]+", expr))
            predicates = tokens - CLASSES
            assert predicates <= set(RELATIONS), \
                f"{role} 的 row_filter 引用未定义关系 {predicates - set(RELATIONS)}"

    def test_optimizer与client与README_12_4逐字一致(self):
        opt = self.ROLES["optimizer"]
        assert opt["classes"] == ["Case", "Campaign", "Creative", "Channel", "Metric", "Guideline"]
        assert opt["deny_properties"] == ["Case.bd_budget", "Case.gross_margin"]
        assert opt["metrics_deny"] == ["gross_margin"]
        assert opt["row_filter"] == "Person(responsible_for)->Case<-belongs_to-Campaign-uses->Creative"
        client = self.ROLES["client"]
        # conversions 与统一列名一致（2026-10-21 夜检 B7：单数曾致客户看不到转化数）
        assert client["metrics_allow"] == ["cost", "ctr", "cvr", "conversions"]
        assert client["row_filter"] == "Person(external_for)->Brand<-for_brand-Case<-belongs_to-Campaign"
