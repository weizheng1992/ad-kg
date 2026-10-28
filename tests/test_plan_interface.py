"""PermissionPlan 执行侧五方法（§12.4 出口唯一执行点，2026-10-28 收口）。

表驱动单测——只打 plan 这一个 interface（permission.py docstring 的承诺）：
端点的类门/详情门/行过滤/属性投影/人名掩码语义在此钉死，route 测试退到
happy path。全部离线（plan 直构或 yaml 翻译，无图无库）。
"""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException

from adkg.models import PermissionPlan

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _plan(**kw) -> PermissionPlan:
    """直构 plan（表驱动基底）：默认 management 形态（类白名单、无行过滤）。"""
    base = dict(metadata_filter={"entity_class__in": ["Case", "Campaign", "Creative"]},
                sql_predicate="", allowed_columns=["cost", "ctr"])
    base.update(kw)
    return PermissionPlan(**base)


_CLIENT = dict(metadata_filter={"entity_class__in": ["Case", "Campaign", "Creative"]},
               allow_properties=frozenset({"Case.stage", "Case.lost_reason",
                                           "Campaign.status"}),
               visible_entity_ids=frozenset({"Brand:B04", "Case:C-2025-011"}),
               mask_rules=["person_name"])


def _raises(code, fn, *a, **kw):
    try:
        fn(*a, **kw)
    except HTTPException as e:
        assert e.status_code == code, (e.status_code, code)
        return
    raise AssertionError(f"未抛 {code}")


class TestGate:
    def test_deny_all即403(self):
        _raises(403, _plan(deny_all=True).gate, "Case")

    def test_类不在白名单(self):
        _raises(403, _plan().gate, "Person")
        _plan().gate("Case")                                # 白名单内通过

    def test_not_found面404(self):
        _raises(404, _plan().gate, "Person", not_found=True)
        _raises(404, _plan(deny_all=True).gate, "Case", not_found=True)

    def test_anchor_ok锚点角色豁免类闸(self):
        p = _plan(visible_entity_ids=frozenset({"Brand:B04"}))
        p.gate("Brand", anchor_ok=True)                     # 类不在白名单但锚点角色放行
        _raises(403, _plan().gate, "Brand", anchor_ok=True)  # 无锚点不豁免


class TestGateDetail:
    def test_次序钉死锚点外404先于类闸403(self):
        # client 查他牌：可见集非空且不在集内 → 404 锚点外（不是类闸 403）
        p = _plan(**_CLIENT)
        _raises(404, p.gate_detail, "Brand", "Brand:B01", label="品牌")

    def test_锚点内豁免类闸(self):
        p = _plan(**_CLIENT)                                # client 类白名单无 Brand
        p.gate_detail("Brand", "Brand:B04", label="品牌")    # external_for 锚点内放行

    def test_全局类豁免可见集(self):
        p = _plan(**_CLIENT, global_classes=frozenset({"Guideline"}))
        p.gate_detail("Guideline", "Guideline:G-03", not_found=True)

    def test_deny_all与not_found(self):
        _raises(404, _plan(deny_all=True).gate_detail, "Case", "Case:X", not_found=True)
        _raises(403, _plan().gate_detail, "Person", "Person:li")

    def test_require_visible(self):
        p = _plan(**_CLIENT)
        _raises(404, p.require_visible, "Case:C-2099-999", label="案例")
        p.require_visible("Case:C-2025-011", label="案例")   # 锚点内通过
        _plan().require_visible("Case:任意")                 # 无行过滤全量放行


class TestFilterVisible:
    def test_无行过滤全量放行(self):
        rows = [{"id": "Case:A"}, {"id": "Case:B"}]
        assert _plan().filter_visible(rows) is rows

    def test_有行过滤收敛(self):
        p = _plan(**_CLIENT)
        out = p.filter_visible([{"id": "Case:C-2025-011"}, {"id": "Case:X"}])
        assert [r["id"] for r in out] == ["Case:C-2025-011"]

    def test_自定义key(self):
        p = _plan(visible_entity_ids=frozenset({"Case:B"}))
        out = p.filter_visible([{"cid": "Case:B"}, {"cid": "Case:C"}], key="cid")
        assert [r["cid"] for r in out] == ["Case:B"]


class TestProject:
    def test_内部黑名单(self):
        p = _plan(deny_properties=frozenset({"Case.bd_budget", "Case.gross_margin"}))
        out = p.project({"stage": "live", "bd_budget": 1, "gross_margin": "0.2",
                         "lost_reason": None}, "Case")
        assert out == {"stage": "live", "lost_reason": None}
        assert p.project({"daily_budget": 5}, "Campaign") == {"daily_budget": 5}

    def test_外部白名单fail_closed(self):
        p = _plan(**_CLIENT)
        out = p.project({"stage": "live", "lost_reason": "价格", "bd_budget": 1,
                         "settlement_status": "未结"}, "Case")
        assert out == {"stage": "live", "lost_reason": "价格"}   # 白名单外一概不出
        assert p.project({"status": "paused", "name": "x"}, "Campaign") == {"status": "paused"}
        assert p.project({"name": "李昂"}, "Person") == {}        # 陌生类零属性（fail-closed）

    def test_yaml翻译的plan投影(self):
        """翻译产物直接打 interface：ae 黑名单裁预算/毛利；client 白名单只剩
        stage/lost_reason——yaml 加属性时此处先行失败（CI 报警位）。"""
        from adkg.guards.permission import PermissionPlanner
        planner = PermissionPlanner(ROOT / "ontology" / "permissions.yaml")
        ae = planner.plan("ae")                              # row_filter 无 person → deny_all
        ae = ae.model_copy(update={"deny_all": False})
        out = ae.project({"stage": "live", "bd_budget": 1, "gross_margin": "0.2"}, "Case")
        assert out == {"stage": "live"}
        client = planner.plan("client")
        out = client.project({"stage": "live", "lost_reason": "价格", "settlement_status": "x"},
                             "Case")
        assert out == {"stage": "live", "lost_reason": "价格"}


class TestMaskPerson:
    def test_掩码与空名跳过(self):
        from adkg.retrieval.assemble import mask_person
        assert mask_person("李昂负责的案例", ["李昂", ""]) == "＊＊负责的案例"
        assert mask_person("无名人", []) == "无名人"
