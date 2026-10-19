"""action_check 约束校验（§六 关键约束 / guards/action_check.py）。

状态机与"live/closed 不可删素材"离线测（图上下文注入假实现）。
"""
import pytest

from adkg.guards.action_check import ActionChecker
from adkg.models import load_schema

SCHEMA = load_schema()


class FakeGraph:
    """creative → campaign → case → stage 的图上下文假实现。"""

    def __init__(self, stage: str | None):
        self.stage = stage

    def creative_case_stage(self, creative_id: str) -> str | None:
        return self.stage


class TestActionChecker:
    def _checker(self, stage=None):
        return ActionChecker(SCHEMA, FakeGraph(stage))

    def test_状态机合法迁移放行(self):
        ok = [("proposal", "live", {}), ("proposal", "lost", {}),
              ("live", "closed", {}),
              ("live", "terminated", {"terminate_reason": "客户预算终止"})]
        for src, dst, extra in ok:
            verdict = self._checker().check("update_stage", {"case_id": "Case:C-1",
                                                             "from_stage": src, "to_stage": dst, **extra})
            assert verdict["decision"] == "allow", f"{src}->{dst} 应放行"

    def test_状态机非法迁移拒绝(self):
        bad = [("proposal", "closed"), ("closed", "live"), ("lost", "proposal"),
               ("terminated", "live"), ("live", "proposal")]
        for src, dst in bad:
            verdict = self._checker().check("update_stage", {"case_id": "Case:C-1",
                                                             "from_stage": src, "to_stage": dst})
            assert verdict["decision"] == "deny", f"{src}->{dst} 应拒绝"
            assert "状态机" in verdict["reason"]

    def test_终态目标必须给原因缺失拒绝(self):
        verdict = self._checker().check("update_stage", {"case_id": "Case:C-1",
                                                         "from_stage": "live", "to_stage": "terminated"})
        assert verdict["decision"] == "deny" and "terminate_reason" in verdict["reason"]

    def test_live或closed案例不可删素材(self):
        for stage in ("live", "closed"):
            verdict = self._checker(stage).check("delete_creative",
                                                 {"target": "Creative:creative_992"})
            assert verdict["decision"] == "deny"
            assert "不可删除" in verdict["reason"] or "live" in verdict["reason"]

    def test_proposal案例删素材放行(self):
        verdict = self._checker("proposal").check("delete_creative",
                                                  {"target": "Creative:x"})
        assert verdict["decision"] == "allow"

    def test_词表外动作与缺目标拒绝(self):
        assert self._checker().check("teleport", {})["decision"] == "deny"
        assert self._checker().check("delete_creative", {})["decision"] == "deny"
