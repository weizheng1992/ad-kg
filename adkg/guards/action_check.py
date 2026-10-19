"""操作前约束校验（§六 关键约束，guards/action_check.py 读取）。

ActionChecker 只回答 allow/deny + 依据——AdKG 是决策点不是执行点（§二.3）。
约束真源 = ontology/schema.yaml#constraints：
- Case 状态机：proposal→live｜lost，live→closed｜terminated，终态不可逆；
  terminated 必填原因；lost 排除可比检索（retrieval 侧，不在此）
- live / closed 的 Case 不可删除 Creative（素材→计划→案例→stage 查图）
- 动作词表：op 必须 ∈ schema actions
"""
from __future__ import annotations

TERMINAL_REQUIRES_REASON = {"terminated"}     # §六 on_terminated


class ActionChecker:
    def __init__(self, schema: dict, graph=None) -> None:
        self.actions = set(schema["actions"])
        self.stage = schema["constraints"]["case_stage"]
        self._graph = graph                     # 提供 creative_case_stage()

    def check(self, op: str, params: dict) -> dict:
        if op not in self.actions:
            return {"decision": "deny", "reason": f"动作 {op} 不在 schema.yaml#actions 词表"}

        if op == "update_stage":
            return self._check_stage(params)
        if op in ("delete_creative", "pause_campaign", "create_creative", "read", "create_case"):
            if op == "delete_creative":
                if not params.get("target"):
                    return {"decision": "deny", "reason": "缺操作目标 target"}
                stage = (self._graph.creative_case_stage(params["target"])
                         if self._graph else None)
                if stage in ("live", "closed"):
                    return {"decision": "deny",
                            "reason": f"constraint violated: live/closed 状态的 Case "
                                      f"不可删除 Creative（schema.yaml#constraints，当前 stage={stage}）"}
            return {"decision": "allow", "reason": "无约束违反"}
        return {"decision": "deny", "reason": f"动作 {op} 未实现校验"}

    def _check_stage(self, p: dict) -> dict:
        src, dst = p.get("from_stage"), p.get("to_stage")
        allowed = self.stage["transitions"].get(src, [])
        if dst not in allowed:
            return {"decision": "deny",
                    "reason": f"状态机不允许 {src}→{dst}（合法迁移：{self.stage['transitions']}）"}
        if dst in TERMINAL_REQUIRES_REASON and not p.get("terminate_reason"):
            return {"decision": "deny", "reason": f"迁移到 {dst} 必填 terminate_reason（§六）"}
        return {"decision": "allow", "reason": f"{src}→{dst} 合法"}
