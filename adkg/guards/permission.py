"""PermissionPlan 唯一翻译点（§7.3 权限下推 / §12.4）。

permissions.yaml → PermissionPlan：一份矩阵翻译成三路可执行过滤器 + 脱敏规则，
三路检索与 assemble 出口只消费 plan、不读权限矩阵（翻译收口在一处，
越权测试只打这一个 interface——架构评审 C1 的落地）。

- 类白名单 → vector 路 metadata_filter
- row_filter（锚点+路径+方向）→ 图展开成 visible_entity_ids（级联收窄自动成立）
- 品牌维度行集 → text2sql 路 sql_predicate；指标列白名单含派生联动
- 外部角色 → mask_rules（assemble 出口对人名脱敏）
- 全局类（Metric/Guideline/Channel，schema global_class）不参与 row_filter
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from adkg.models import PermissionPlan, load_schema

# 派生联动（§12.4）：deny 一列时同步 deny 含它的派生列（防乘法反推）
DERIVED: dict[str, set[str]] = {"cost": {"cpa", "roi"}, "impressions": {"cpm", "ctr"},
                                "clicks": {"ctr", "cvr"}}

_ALL_METRIC_COLUMNS = ["cost", "impressions", "clicks", "conversions",
                       "ctr", "cvr", "cpa", "cpm", "roi", "gross_margin"]


def load_permissions(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


class PermissionPlanner:
    def __init__(self, permissions_path: Path, graph=None) -> None:
        self.schema = load_schema()                        # 全局类豁免要读 schema
        self.perms = load_permissions(permissions_path)
        self.global_classes = {c for c, cfg in self.schema["classes"].items()
                               if cfg.get("global_class")}
        self._graph = graph

    # ----------------------------------------------------- 指标列白名单
    def _allowed_columns(self, cfg: dict) -> list[str]:
        if cfg.get("metrics_allow"):                       # 外部：全白名单
            return list(cfg["metrics_allow"])
        denied = set(cfg.get("metrics_deny", []))
        for col in list(denied):
            denied |= DERIVED.get(col, set())
        return [c for c in _ALL_METRIC_COLUMNS if c not in denied]

    # ----------------------------------------------------- row_filter 展开
    def _expand_row_filter(self, expr: str, person: str) -> tuple[frozenset[str], str]:
        """锚点+路径+方向 → 图上可达实体 ID 集 + SQL 行谓词。

        记法：Person(responsible_for)->Case<-belongs_to-Campaign
        段方向：`->pred` 正向走；`<-pred` 反向走。路径上全部实体收进可见集；
        品牌维度另算 SQL 谓词（text2sql 路消费）。
        """
        m = re.match(r"(\w+)\((\w+)\)->(\w+)(.*)", expr)
        if not m or not person:
            return frozenset(), ""
        _anchor, first_rel, _cls, rest = m.groups()
        path = f"(p0:Entity {{id: $person}})-[:{first_rel}]->(p1:Entity)"
        n = 1
        while rest:
            m2 = re.match(r"<-(\w+)-(\w+)(.*)", rest)      # 反向段：Cls-[pred]->当前
            m3 = re.match(r"-(\w+)->(\w+)(.*)", rest)      # 正向段：当前-[pred]->Cls
            if m2:
                rel, _cls, rest = m2.groups()
                n += 1
                path += f"<-[:{rel}]-(p{n}:Entity)"
            elif m3:
                rel, _cls, rest = m3.groups()
                n += 1
                path += f"-[:{rel}]->(p{n}:Entity)"
            else:
                break
        with self._graph.session() as s:
            var_list = ", ".join(f"p{i}" for i in range(n + 1))
            rows = s.run(f"MATCH {path} WITH [{var_list}] AS ns UNWIND ns AS n"
                         " RETURN DISTINCT n.id AS id", person=person).data()
            ids: set[str] = {person} | {r["id"] for r in rows if r["id"]}
            # 品牌维度 → SQL 谓词（text2sql 行级落点）
        # SQL 谓词（闸 4 的数据）：优先案例级（optimizer 的"负责案例"粒度，§9.2），
        # 无案例维度再退品牌级（client 的品牌子图）；维度来自可见集而非锚点品牌——
        # 修复：optimizer 对接品牌 ≠ 负责案例所在品牌，按品牌收窄会错杀（评测 R2 抓出）
        case_ids = sorted(i for i in ids if i.startswith("Case:"))
        brand_ids = sorted(i for i in ids if i.startswith("Brand:"))
        if case_ids:
            predicate = "case_id IN (" + ", ".join(f"'{c}'" for c in case_ids) + ")"
        elif brand_ids:
            predicate = "brand_id IN (" + ", ".join(f"'{b}'" for b in brand_ids) + ")"
        else:
            predicate = ""
        return frozenset(ids), predicate

    # ----------------------------------------------------- 主入口
    def plan(self, role: str, person: str | None = None) -> PermissionPlan:
        cfg = self.perms["roles"][role]
        classes = [c for c in cfg["classes"]]
        visible: frozenset[str] = frozenset()
        predicate = ""
        if cfg.get("row_filter") and self._graph is not None and person:
            visible, predicate = self._expand_row_filter(cfg["row_filter"], person)
        return PermissionPlan(
            metadata_filter={"entity_class__in": classes},
            visible_entity_ids=visible,
            sql_predicate=predicate,
            allowed_columns=self._allowed_columns(cfg),
            deny_properties=frozenset(cfg.get("deny_properties", [])),
            allow_properties=frozenset(cfg.get("allow_properties", [])),
            mask_rules=["person_name"] if cfg.get("external") else [],
        )
