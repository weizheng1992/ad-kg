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
        ae_out = search("Case:C-2025-008 预算多少",
                        planner.plan("ae", person="Person:li"), g)
        case_props = next((e["props"] for e in ae_out["evidence"]
                           if e["type"] == "entity" and e["ref"] == "Case:C-2025-008"), {})
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

    def test_人锚点仅限第一人称(self):
        """G14 实弹（2026-10-27 golden）：无锚点的全局问题被静默圈到提问者本人，
        归因串行把 CPA 榜收窄成其品牌子集；人锚点只服务"我的品牌/我们的案例"
        （§9.1）——第一人称指代在场才启用。"""
        import os

        from adkg.guards.permission import PermissionPlanner
        from adkg.retrieval.graph_search import search
        from adkg.store.graph import GraphStore

        g = GraphStore(os.environ["ADKG_NEO4J_URI"], os.environ["ADKG_NEO4J_USER"],
                       os.environ["ADKG_NEO4J_PASSWORD"])
        planner = PermissionPlanner(ROOT / "ontology/permissions.yaml", graph=g)
        # 全局问法：不得锚到 Person:chen（entity_ids 会经 entity_ids_from 收窄 text2sql）
        out = search("效果差的素材和创意规范有没有关系？",
                     planner.plan("management", person="Person:chen"), g, person="Person:chen")
        assert out["entity_ids"] == []
        assert not any("Person:chen" in str(e.get("ref", "")) for e in out["evidence"])
        # 第一人称问法：锚点即本人（§9.1 原语义保留）
        mine = search("我负责哪些案例", planner.plan("management", person="Person:chen"), g,
                      person="Person:chen")
        assert "Person:chen" in mine["entity_ids"]
        assert any("Person:chen" in e["ref"] for e in mine["evidence"])
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

    def test_点名素材不走自由生成保双平台分行(self):
        """G16 实弹（2026-10-27 golden）：生成 prompt 建议的 string_agg(platform) 聚合形
        把 (素材,平台) 分行压成单行，"双平台 CPA 数值"证据点随 LLM 成败漂移——点名
        素材一律直落 entity_metrics 模板（§12.5），生成器不得被调用。"""
        import os

        from adkg.guards.permission import PermissionPlanner
        from adkg.retrieval.text2sql import run

        planner = PermissionPlanner(ROOT / "ontology/permissions.yaml")
        plan = planner.plan("management")
        gen_sql = ("SELECT creative_id, string_agg(DISTINCT platform::text, ',') AS platforms,"
                   " sum(cost)/NULLIF(sum(conversions),0) AS cpa FROM unified_metrics"
                   " WHERE creative_id = 'Creative:creative_992' GROUP BY 1 LIMIT 10")
        called = []

        def gen(prompt, user):
            called.append(1)                              # 若被调用即回归（聚合单行形）
            return {"sql": gen_sql}

        out = run("creative_992 的 CPA 高吗？和规范有关系吗？", plan,
                  os.environ["ADKG_PG_RO_DSN"], generator=gen)
        assert not called
        assert out["evidence"][0]["sql_source"].startswith("template")
        plats = {r["platform"] for r in out["evidence"][0]["rows"]
                 if r["creative_id"] == "Creative:creative_992"}
        assert plats == {"douyin", "xhs"}                 # 双平台分行在场

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
        # 附覆盖平台列（一案例常跨双平台，DISTINCT 聚合）
        assert "SELECT case_id" in sql and "sum(conversions)" in sql
        assert "string_agg(DISTINCT platform::text, ',') AS platforms" in sql
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

    def test_中文数量词解析(self):
        # 2026-10-21 线上 500：int('一') 崩在模板入口，问题带「一个/两条」即 /ask 全挂
        from adkg.retrieval.text2sql import build_sql
        for q, n in (("表现最好的一个案例", 1), ("最差的两条素材", 2),
                     ("十二个案例里 CPA 最好的", 12),
                     ("CPA 最好的素材", 5)):                      # 无数量词维持默认
            _, p = build_sql(q, self._plan())
            assert p.get("n") == n, f"{q!r} → n={p.get('n')}，应为 {n}"
        sql, _ = build_sql("第3个案例", self._plan())            # 不进 top_metric，但不许崩
        assert "platform" in sql

    def test_最高最低与花钱最多方向(self):
        """夜检 D2/A11：最高/最多/最低/最少是绝对方向词，不随成本型反转；花钱/烧钱→cost；
        "最近一个月"口语窗按近 30 天解析。"""
        from adkg.retrieval.text2sql import build_sql
        _, p = build_sql("消耗最高的十个素材", self._plan())
        assert p["metric"] == "cost" and p["direction"] == "DESC" and p["n"] == 10
        _, p = build_sql("CPA 最低的素材", self._plan())
        assert p["metric"] == "cpa" and p["direction"] == "ASC"   # 最低：与成本型判断无关
        _, p = build_sql("最近一个月花钱最多的创意", self._plan())
        assert p["metric"] == "cost" and p["direction"] == "DESC" and p["window"]
        assert p["n"] == 5    # "最近一个月"的"一个"是时长不是数量词，n 维持默认

    def test_效果差是排名语义且不劫持归因路由(self):
        """G14 实弹（2026-10-27 golden）："效果差"不带"最"也曾是排名语义——词表缺席时
        模板落到平台汇总/entity_metrics，"CPA 排序的素材清单"证据点永远缺席。"""
        from adkg.retrieval.router import rule_route
        from adkg.retrieval.text2sql import build_sql
        sql, p = build_sql("效果差的素材和创意规范有没有关系？", self._plan())
        assert p["metric"] == "cpa" and p["direction"] == "DESC"   # 缺省口径+差向前=最差优先
        assert p.get("group") == "creative_id" and "ORDER BY cpa DESC" in sql
        # 词表加词不得劫持既有路由：归因问法仍归因（_ATTR 先于 _FACT），裸问法进 fact
        assert rule_route("效果差的素材和创意规范有没有关系？").intent == "attribution"
        assert rule_route("效果差的素材有哪些").intent == "fact"

    def test_交易语义优先于排名词(self):
        """夜检 D7："卖得最好/购买率最高/订单最多"是交易语义，不得落缺省 cpa 的
        top_metric（问交易答投放）。"""
        from adkg.retrieval.text2sql import build_sql
        for q in ("最近卖得最好的是哪几个牌子", "购买率最高的商品", "上个月订单最多的产品"):
            sql, p = build_sql(q, self._plan())
            assert "product_orders_daily" in sql and "purchase_rate" in sql, q

    def test_交易模板预聚合与行谓词注入(self):
        """unified 粒度 creative×platform×day：join 前必须预聚合到 product×day
        （防 orders/gmv 按投放行数放大）；行权限谓词注入预聚合内，且用产品级半连接
        fail-closed——权限内产品 orders/gmv 仍全量、权限外产品一行不出；
        无谓词保留无覆盖 SKU（诚实，不编数）。"""
        from adkg.retrieval.text2sql import build_sql
        sql, _ = build_sql("最近的销量情况", self._plan())
        assert "GROUP BY 1, 2" in sql and "IN (SELECT product_id FROM uc)" not in sql
        scoped = self._plan().model_copy(
            update={"sql_predicate": "case_id IN ('Case:C-2025-003')"})
        sql2, _ = build_sql("最近的销量情况", scoped)
        assert "case_id IN ('Case:C-2025-003')" in sql2 \
            and "o.product_id IN (SELECT product_id FROM uc)" in sql2

    def test_商品品牌粒度排名不回归(self):
        """2026-10-22 对抗验证回归：排名分支曾吞掉商品粒度——group 按问句实体词判。"""
        from adkg.retrieval.text2sql import build_sql
        _, p = build_sql("消耗最高的商品", self._plan())
        assert p["group"] == "product_id" and p["direction"] == "DESC"
        _, p = build_sql("各商品 CPA 最低", self._plan())
        assert p["group"] == "product_id" and p["n"] == 20 and p["direction"] == "ASC"
        _, p = build_sql("哪个品牌的抖音消耗最高", self._plan())
        assert p["group"] == "brand_id" and p["platform"] == "douyin"
        _, p = build_sql("消耗最高的十个素材", self._plan())
        assert p["group"] == "creative_id" and p["n"] == 10

    def test_量词与复合词映射(self):
        """词长降序匹配：转化率先于转化、千次曝光成本先于成本；量词/投产比入口。"""
        from adkg.retrieval.text2sql import build_sql
        for q, m in (("转化量最高的素材", "conversions"), ("转化数最多的素材", "conversions"),
                     ("转化率最高的素材", "cvr"), ("点击最多的素材", "clicks"),
                     ("曝光最多的素材", "impressions"), ("千次曝光成本最低", "cpm"),
                     ("转化成本最高的素材", "cpa"), ("跑量最多的素材", "cost"),
                     ("投产比最高的素材", "roi"), ("烧钱最凶的素材", "cost")):
            _, p = build_sql(q, self._plan())
            assert p["metric"] == m, f"{q!r} → {p['metric']}，应为 {m}"
        _, p = build_sql("烧钱最凶的素材", self._plan())
        assert p["direction"] == "DESC"                        # 最凶 = 绝对方向词

    def test_roi不可算降级不炸(self):
        """roi 视图无列也无公式（需收入回传）：排名问句降级平台汇总 + 口径 note，
        永不生成 sum(roi)（2026-10-22 验证：曾直接把 /ask 打成 500）。"""
        from adkg.retrieval.text2sql import build_sql
        sql, p = build_sql("roi 最高的素材", self._plan())
        assert "sum(roi)" not in sql and "unified_metrics" in sql
        assert p.get("note") and "不可算" in p["note"]

    def test_平台汇总与天数口径(self):
        """汇总投影一律汇总比（禁裸 sum(cvr) 出 120% 转化率）；days=投放天数（DISTINCT date）。"""
        from adkg.retrieval.text2sql import build_sql
        cli = self._plan().model_copy(update={"allowed_columns":
                                              ["cost", "ctr", "cvr", "conversions"]})
        sql, _ = build_sql("近7天转化汇总", cli)
        assert "NULLIF(sum(clicks), 0)" in sql and "sum(cvr)" not in sql
        sql2, _ = build_sql("CPA 最差的素材", self._plan())
        assert "count(DISTINCT date) AS days" in sql2
        assert "HAVING count(DISTINCT date) >= 3" in sql2

    def test_交易模板排序键与方向(self):
        """交易榜排序按所问指标与方向，不再恒 ORDER BY orders DESC。"""
        from adkg.retrieval.text2sql import build_sql
        sql, _ = build_sql("购买率最高的商品", self._plan())
        assert "ORDER BY purchase_rate DESC NULLS LAST" in sql
        sql, _ = build_sql("卖得最差的商品", self._plan())
        assert "ORDER BY orders ASC NULLS LAST" in sql
        sql, _ = build_sql("gmv 最高的商品", self._plan())
        assert "ORDER BY gmv DESC NULLS LAST" in sql

    def test_时间窗口泛化(self):
        """口语窗：昨天/今天/前天/本周(周一起)/上周/最?近|过去 N 天日周月（中文数字可）。"""
        from datetime import date

        from adkg.retrieval.text2sql import _window_of
        t = date(2026, 10, 22)                                # 周四
        assert _window_of("昨天的消耗", t) == ("2026-10-21", "2026-10-21")
        assert _window_of("近一周的消耗", t) == ("2026-10-16", "2026-10-22")
        assert _window_of("上周的消耗", t) == ("2026-10-12", "2026-10-18")
        assert _window_of("最近3个月的消耗", t) == ("2026-07-25", "2026-10-22")
        assert _window_of("过去30天的消耗", t) == ("2026-09-23", "2026-10-22")
        assert _window_of("近一个月", t) == ("2026-09-23", "2026-10-22")
        assert _window_of("没有时间词", t) is None

    def test_数量词时间前缀规则(self):
        """时长跳过仅限"时间指示词+数量词+月/年/周"——"三个月饼"仍计 3。"""
        from adkg.retrieval.text2sql import _count_of
        assert _count_of("三个月饼礼盒") == 3
        assert _count_of("最近一个月花钱最多的创意") == 5
        assert _count_of("前2个月的订单") == 5
        assert _count_of("近一周的三个素材") == 3
        assert _count_of("top3 素材") == 3                     # top-N 直取

    def test_案例粒度家族外指标进投影(self):
        """case 粒度投影固定家族四列，ORDER BY 引用投影外指标列会 42803 空证据
        （2026-10-22 二轮验证回归）：家族外指标必须追加进投影。"""
        from adkg.retrieval.text2sql import build_sql
        for q, m in (("各案例转化量排名", "conversions"),
                     ("哪个案例曝光最大", "impressions"), ("各案例千次曝光成本对比", "cpm")):
            sql, p = build_sql(q, self._plan())
            assert p.get("group") == "case_id", q
            assert f"AS {m}" in sql, f"{q!r} 排序指标未进投影: {sql}"
        # 中心词是素材 → creative 粒度（单指标投影，无 42803 问题）
        sql, p = build_sql("案例点击最多的素材是哪个", self._plan())
        assert p["group"] == "creative_id" and "AS clicks" in sql

    def test_裸排名与中心词粒度(self):
        """裸排名（无方向词）多的在前；粒度取问句最右实体词（中心词）。"""
        from adkg.retrieval.text2sql import build_sql
        _, p = build_sql("素材转化量排名", self._plan())
        assert p["direction"] == "DESC"                     # 曾排成 ASC 最少在前
        _, p = build_sql("案例展现最多的计划", self._plan())
        assert p["group"] == "campaign_id"                  # 中心词是计划非案例
        _, p = build_sql("消耗最高的是哪些案例", self._plan())
        assert p["group"] == "case_id"

    def test_毛利与绝对年月窗(self):
        """毛利率→gross_margin 走不可算降级+note；绝对年月窗可解析（空窗回退有据）。"""
        from adkg.retrieval.text2sql import _window_of, build_sql
        from datetime import date
        sql, p = build_sql("毛利率最高的品牌", self._plan())
        assert "gross_margin" not in sql and p.get("note") and "不可算" in p["note"]
        assert _window_of("2027年1月卖得最好的商品", date(2026, 10, 22)) == \
            ("2027-01-01", "2027-01-31")
        assert _window_of("2026年整体消耗", date(2026, 10, 22)) == \
            ("2026-01-01", "2026-12-31")

    def test_素材中心词与统计触发词(self):
        """三轮验证：素材/创意也进中心词候选；统计分支触发词认量词族（各案例转化量）。"""
        from adkg.retrieval.text2sql import build_sql
        _, p = build_sql("品牌下消耗最高的素材", self._plan())
        assert p["group"] == "creative_id"                 # 中心词是素材，不被品牌劫持
        sql, p = build_sql("各案例的转化量", self._plan())
        assert p.get("group") == "case_id" and p["metric"] == "conversions"
        assert "AS conversions" in sql


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
        # 别名走私（2026-10-22 二轮验证）：deny cost 的角色，sum(cost) AS cost 仍须拒
        deny_cost = self._plan().model_copy(update={"allowed_columns":
                                                    ["ctr", "cvr", "conversions"]})
        err2, _ = validate_sql(
            "SELECT sum(cost) AS cost FROM unified_metrics LIMIT 5", deny_cost)
        assert err2 and "cost" in err2

    def test_谓词强制包裹(self):
        from adkg.retrieval.text2sql import enforce_predicate
        from adkg.models import PermissionPlan
        plan = PermissionPlan(allowed_columns=["cost"],
                              sql_predicate="brand_id IN ('B04')")
        wrapped = enforce_predicate("SELECT platform, sum(cost) FROM unified_metrics LIMIT 5", plan)
        assert wrapped.startswith("SELECT * FROM (") and "brand_id IN ('B04')" in wrapped
        # 无条件包裹（2026-10-22 二轮验证）：提及 brand_id ≠ 已施加行过滤——
        # 见字样即跳过曾让 client 跨品牌全量泄漏
        wrapped2 = enforce_predicate("SELECT brand_id FROM unified_metrics LIMIT 5", plan)
        assert wrapped2.startswith("SELECT * FROM (") and "brand_id IN ('B04')" in wrapped2

    def test_生成失败回落模板语义(self):
        from adkg.retrieval.text2sql import generate_sql
        assert generate_sql(lambda s, u: (_ for _ in ()).throw(RuntimeError("x")),
                            "任何问题", self._plan()) is None
        # 返回危险 SQL 也被闸门拒
        assert generate_sql(lambda s, u: {"sql": "DROP TABLE chunks"}, "q", self._plan()) is None

    def test_prompt推荐模式不再误杀_语义注入兼容别名(self):
        """三轮验证：extract(month from date) 曾系统性误杀（from 撞表扫描、month 撞列扫描）；
        值级越权闸弃用标量子查询/窗口函数；enforce_semantics 兼容表别名。"""
        from adkg.models import PermissionPlan
        from adkg.retrieval.text2sql import enforce_semantics, generate_sql, validate_sql
        sql = ("SELECT creative_id, string_agg(DISTINCT platform::text, ',') AS platforms,"
               " round(sum(cost)::numeric/NULLIF(sum(impressions),0),4) AS ctr,"
               " extract(month from date) AS mon"
               " FROM unified_metrics WHERE date >= current_date - interval '30 days'"
               " GROUP BY 1 ORDER BY ctr DESC LIMIT 5")
        # ctr 公式分母要 impressions——测试 plan 补上（无 impressions 的角色拒它是闸的正确行为）
        plan_full = self._plan().model_copy(update={"allowed_columns":
                                                    ["cost", "impressions", "clicks",
                                                     "conversions", "ctr", "cvr", "cpa"]})
        err, _ = validate_sql(sql, plan_full)
        assert err is None, err
        out = enforce_semantics("SELECT u.platform FROM unified_metrics AS u LIMIT 5")
        assert "AS u WHERE NOT unmatched" in out
        # 值级越权闸：有行谓词的角色，标量子查询把跨权限聚合值带出去 → 弃用生成
        scoped = PermissionPlan(allowed_columns=["cost"],
                                sql_predicate="brand_id IN ('B04')")
        gen = ("SELECT platform, round(sum(cost)::numeric,2) AS cost,"
               " (SELECT sum(cost) FROM unified_metrics) AS total"
               " FROM unified_metrics GROUP BY 1 LIMIT 5")
        assert generate_sql(lambda s, u: {"sql": gen}, "各平台消耗", scoped) is None
        # 无谓词角色不受此闸影响
        assert generate_sql(lambda s, u: {"sql": gen}, "各平台消耗", self._plan()) is not None

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


class Test关键词兜底分词:
    """_extract_keywords（§7.2 降级路）：jieba 分词替代字符窗口切片——
    旧版 [一-龥]{2,8} 把长问句切成任意 8 字窗口（非词），ILIKE 几乎必 miss
    （缺陷备忘②，2026-10-27 修）"""

    def test_长问句切出的是词不是窗口(self):
        from adkg.retrieval.vector_search import _extract_keywords
        kws = _extract_keywords("信息流视频的开头三秒要注意什么规范要求")
        assert "信息流" in kws and "视频" in kws          # jieba 实词
        assert all(2 <= len(k) <= 8 for k in kws)
        assert len(kws) <= 4

    def test_纯虚词剥完为空(self):
        from adkg.retrieval.vector_search import _extract_keywords
        assert _extract_keywords("的了吗呢") == []

    def test_去重与长词优先(self):
        from adkg.retrieval.vector_search import _extract_keywords
        assert _extract_keywords("信息流 信息流 信息流") == ["信息流"]   # 去重
        kws = _extract_keywords("信息流视频的开头三秒")
        assert kws[0] == "信息流" and len(kws) <= 4                     # 长词优先


@pytest.mark.skipif(not _dbs_up(), reason="数据库不在线")
class TestKeyword兜底集成:
    def test_嵌入缺失走分词兜底(self):
        import os
        from types import SimpleNamespace
        from adkg.retrieval.vector_search import search
        plan = SimpleNamespace(deny_all=False, metadata_filter={},
                               visible_entity_ids=[])
        r = search("信息流视频开头三秒的规范要求", plan,
                   os.environ["ADKG_PG_DSN"], embed_fn=None)
        assert r["degraded"] is False                     # 缺席不如降级检索（§7.2）
        if r["evidence"]:                                 # 库里有规范文档则应命中
            assert r["evidence"][0]["fallback"] == "keyword"
