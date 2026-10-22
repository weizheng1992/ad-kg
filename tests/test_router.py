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

    def test_属性型问题归graph路(self):
        """实体自身属性（target_age 等属性证据项）走 graph 路而非 fact（§7.3）。"""
        assert intent_of("轻食日记App 的目标人群是什么年龄段？") == "graph"
        assert intent_of("这些小程序的人群画像是怎样的？") == "graph"

    def test_排名绝对词与口语花费词进fact路(self):
        """夜检 D2/A11/D7：最高/最低/花钱/烧钱/销量/订单是事实语义，不再落 unknown 兜底；
        词表扩充不得误伤属性型 graph 题。"""
        assert intent_of("消耗最高的十个素材") == "fact"
        assert intent_of("最近一个月花钱最多的创意") == "fact"
        assert intent_of("上个月订单最多的产品") == "fact"
        assert intent_of("点击最多的素材") == "fact"
        assert intent_of("轻食日记App 的目标人群是什么年龄段？") == "graph"

    def test_定义类短语优先归concept(self):
        """交易/指标词进 _FACT 后，口径/定义类问题不得被抢去查数（2026-10-22 验证）；
        操作口语词（停投/关停）归 operation。"""
        assert intent_of("购买率的口径定义是什么") == "concept"
        assert intent_of("ctr 是什么意思") == "concept"
        assert intent_of("转化量最高的素材") == "fact"       # 定义词缺席时量词题仍查数
        assert intent_of("停投这个计划") == "operation"
        assert intent_of("把那个创意关停") == "operation"

    def test_词表误伤面回归表(self):
        """2026-10-22 二轮验证实锤的误伤面：口径作修饰语=查数、被动义操作词=检索、
        规格词撞绝对词/量词=概念、点击率≠点击量。"""
        cases = [
            ("按新口径 CPA 最差的素材", "fact"),          # 口径是修饰语，题眼是最差排名
            ("各平台总消耗是多少（按新口径）", "fact"),
            ("已下线案例的负责人是谁", "graph"),
            ("logo 最小尺寸规范", "concept"),              # 规格词撞"最小"
            ("落地页对点击率有什么规范", "concept"),        # 点击率≠点击量
            ("信息流视频的时长规范是什么？", "concept"),    # 老概念题不回归
            ("点击最多的素材", "fact"),                    # 正例不回归
            ("哪个案例曝光最大", "fact"),
        ]
        for q, want in cases:
            got = intent_of(q)
            assert got == want, f"{q!r} → {got}，应为 {want}"
        # "被关停的案例有哪些"：存量 _GRAPH 无"有哪些"词序（"案例有哪些"≠"哪些案例"），
        # 落 unknown 三路兜底（graph 在内、有证据）——本条缺陷的实害是 operation 劫持，
        # 断言非 operation 即可；给 _GRAPH 加"有哪些"会偷走"规范里有哪些要求"类概念题
        assert intent_of("被关停的案例有哪些") != "operation"

    def test_定语指标与名词性检索标记(self):
        """三轮验证实锤：定语型指标词（跑量素材）不作硬聚合信号、规范题归 concept；
        名词性检索标记（列表/清单/查一下）使操作词（含旧词暂停）降检索路。"""
        cases = [
            ("跑量素材的时长要求", "concept"),
            ("爆量素材的规范有哪些", "concept"),
            ("投放量最大的素材符合规范吗", "concept"),
            ("花钱最多的素材违反规范了吗", "concept"),
            ("销量最高的商品有什么要求", "concept"),
            ("排名是什么意思", "concept"),                 # 定义尾压过主语排除词
            ("最差 CPA 的计算口径是什么", "concept"),
            ("logo 最小尺寸是多少", "concept"),             # 多少不作硬信号
            ("各平台总消耗是多少", "fact"),                  # 真聚合不受救实影响
            ("关停的案例列表", "unknown"),                  # 名词性标记 → 检索（三路兜底）
            ("查一下关停的案例", "unknown"),
            ("帮我看看被暂停的素材", "unknown"),             # 旧操作词同样受护栏
            ("已暂停的计划有哪些", "unknown"),
            ("暂停计划 Campaign:C-2025-005-cp1", "operation"),  # 真操作不误放
        ]
        for q, want in cases:
            got = intent_of(q)
            assert got == want, f"{q!r} → {got}，应为 {want}"

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
