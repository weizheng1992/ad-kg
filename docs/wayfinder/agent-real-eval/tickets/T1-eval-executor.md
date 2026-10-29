---
type: task
status: resolved
assignee: weizheng1992
blocked-by: []
resolved: 2026-10-29
labels: [wayfinder:task]
---

# T1 判据基建：agent 评测执行器

## Question

新增四型题全部打 `/agent/chat`（真实 LLM 多轮工具流），现有 `eval/run_eval.py` 只认 golden JSONL 单问一答形状，装不下。本票建**agent 评测执行器**，让后面四张题型票只管写题不管写轮子：

- **执行**：读场景文件 → 按角色登录 → 打 `/agent/chat`（或 SSE 流式）→ 采集事件流（thought/tool_*/reply/draft/done）→ 逐题判分
- **判据三件**：judge 要点命中（复用 `eval/judge.py`）、`must_numbers` 数值锚点（容差口径沿用现有 golden 机制）、场景断言（案例生成等多步：draft 字段/commit 后图上落点，直接查 Neo4j/PG 断言）
- **存储形状**：新场景文件的格式自定（JSONL 或 YAML 均可），但**不得改动现有 `golden_set.jsonl` 38 题的任何一行**；题型 taxonomy 如何容纳新四型在此票定死
- **锚点机制**：新题数值锚点沿用 recalc_golden 思路（先实弹跑出库值 → 人工核对 → 落锚；dry-run diff + --yes 幂等）
- **报告**：每轮跑完出 per-type 达标情况（≥90% 门槛线标注、锚点命中、degraded 降级清单），JSON/MD 落 `eval/runs/`（沿用现有 runs 时间戳惯例）
- **防抖**：支持同一场景集连跑 N 轮、汇总两轮达标判定（验收口径=每型分别达标+连续两轮）

## 验收

- 执行器可用一条命令跑完一个场景文件（命令进 README/CLAUDE.md 评测命令段，同批改文档）
- 拿 1 题统计样例 + 1 个案例生成样例实弹端到端跑通（真 LLM、真角色、真锚点落盘）
- 判据三件各有单测（mock LLM 事件流），pytest 全绿、ruff 干净
- degraded 降级在报告可见，不静默算过

## Answer（2026-10-29 实弹收官）

**交付**：`eval/agent_eval.py`（执行器）+ `eval/recalc_agent.py`（锚点重算）+ `eval/agent_scenarios.jsonl`（两样例）+ `tests/test_agent_eval.py`（21 测试）。命令已入 README/CLAUDE.md。

**关键定夺**（后续票沿用）：
- **执行路**：TestClient 进程内打 API（同 run_eval 惯例）——真 LLM/真库/真权限，只省网络层；`app.state.llm` 可注 FakeLLM 供离线测试。
- **判据三件**：judge 要点（复用 judge.py，证据=reply+trace）；must_numbers 容差 ±max(0.06,1%) 同 golden；场景断言（casegen：draft 字段→commit→图上落点九项→别名→清理）。
- **实体锚软化**（实弹拍板）：agent 面回复用实体名不用 ID（judge 证据里无结构化证据体），judge 在场时实体匹配降观察项，仅规则兜底模式作硬门。
- **锚点协议**：场景显式声明 `anchor.kind`（现三种：window_top_cpa/creative_cpa/platform_cost），协议同 recalc_golden（dry-run diff/--yes 幂等）；A01 锚=`Creative:C-2025-001-cp2-cr2` 48.78。
- **清理安全性**：commit_draft 的 `written` 只含新写实体（L1 对齐命中不碰），按 written 清理不伤主数据（代码注释钉死）。
- **守门**：报告落 `eval/runs/agent-{stamp}.json`（含 reply_excerpt 诊断摘录）；达标门=每型各轮 ≥90%（casegen 恒 100%）连 --rounds 轮。

**实弹结果**：2 轮 × 2 场景全过（A01 84.6s/40.6s；A02 132.9s/158.4s），报告 agent-20261029-221550.json；pytest 全量 303 绿；ruff（--select E4,E7,E9,F 项目基线）干净。

**事故与修正**（防复发已钉测试）：① `__main__` 守卫漏写→静默零输出（agent-all 同款事故，test_cli入口守卫钉死）；② degraded_of 炸数组结果（list_brands 返回 JSON 列表，isinstance 防御+测试）；③ 单场景判分异常炸整轮（main 循环 try/except，§7.2 降级不阻塞）。

**给后续票的事实**：
- **T5 注意**：case_seed 生成有 LLM 抖动——同场景一轮直 final 无 seed、一轮先搜商品知识后正确产出；场景判据须容忍（重跑/措辞调优），T5 场景库直面它。
- **T5 可加断言**：ae 行权限下 agent 看不见 scope 外品牌（实弹观察：agent 诚实说「途野露营不在可见品牌库」），但服务端 materialize 对齐仍正确命中既有 Brand——两层各司其职，可作诚实性断言素材。
- A01 回复形态：实体名+精确值（48.777→48.78 容差收）+归属上下文，judge 全中——后续统计题 points 照此粒度写。
