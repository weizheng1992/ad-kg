"""router 规则版测试（§7.3 路由决策表 + §7.2 规则兜底）。"""
from adkg.models import RouterPlan
from adkg.retrieval.router import RouteDecision, rule_route


def intent_of(q: str) -> str:
    return rule_route(q).intent


class TestRuleRoute:
    def test_五类意图命中(self):
        assert intent_of("李昂名下还有哪些 live 案例？") == "graph"
        assert intent_of("上月抖音 CPA 最差的三个素材是哪些？") == "fact"
        assert intent_of("信息流视频的时长规范是什么？") == "concept"
        assert intent_of("效果差的素材和创意规范有没有关系？") == "attribution"
        assert intent_of("帮我删掉这个素材") == "operation"

    def test_操作类不产生执行计划(self):
        d = rule_route("删掉 live 案例里的素材")
        assert d.intent == "operation" and d.plan is None

    def test_归因混合是串行计划(self):
        plan = rule_route("效果差的素材和创意规范有没有关系？").plan
        assert isinstance(plan, RouterPlan)
        assert [s.route.value for s in plan.steps] == ["graph", "text2sql", "vector"]
        t, v = plan.steps[1], plan.steps[2]
        assert t.depends_on == ["g"] and v.depends_on == ["t"]
        assert t.params["entity_ids_from"] == "g"           # graph 圈实体作 SQL 条件

    def test_关系链计划_主路无依赖带辅助(self):
        plan = rule_route("李昂名下还有哪些 live 案例？").plan
        assert [s.route.value for s in plan.steps] == ["graph", "vector"]  # 主+辅（§7.3 表）
        assert plan.steps[0].depends_on == [] and plan.steps[1].depends_on == []
        assert plan.steps[0].confidence >= 0.8              # 强关键词高置信

    def test_无命中走三路全跑兜底(self):
        d = rule_route("今天天气怎么样")
        assert d.plan.fallback is True
        assert {s.route.value for s in d.plan.steps} == {"graph", "text2sql", "vector"}
        assert d.plan.steps[0].depends_on == []             # 全跑无依赖，assemble 去重

    def test_decision是纯数据(self):
        d = rule_route("消耗多少")
        assert isinstance(d, RouteDecision) and d.intent == "fact" and d.plan is not None
