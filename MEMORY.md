# Memory

重大决策、阶段完成、未来 agent 需要知道的 bug 之后更新本文件。保持精简。
**在办状态的真源是 `docs/wayfinder/agent-real-eval/` 地图，本文件只是时点快照（见文末日期）。**

## Current State

- Current task: wayfinder「agent 真实化评测」地图在办——T1–T4 resolved，T5/T6 前线开放（票面以地图为准）
- Current phase: 既有系统增量演进（已上线；不走新项目规划）
- Next step: T5/T6（见地图前线）
- Blocked by: 无（引擎缺口七项已记地图雾区，修复属引擎工作另立 effort）

## Decisions

- 2026-10-31 T4 对比型真实化题收官（7/7 两轮 100%）：题库三形态落定；recalc_agent 锚累计九种；评测者伪影第五处（千分位剥离反噬）钉回归测试
- 2026-10-31 vibe 工具链接入拍板：PRD/TechDesign 用**薄指针**（非规范、真源 README）；README §四同批记录
- 2026-10-30 夜检修复批落地 + eval 五件套共享件收口（common.py / _criteria.py / metrics.STAT_HAVING）；agent 评测 transport_dead 剔除分母口径拍板（端点长尾非质量信号）

## AI / Tooling Decisions

- LLM 智谱双端点：交互路 coding 端点 glm-5.3-flash；批任务 glm-4-flash 走 `batch_chat_json`——`ADKG_LLM_BATCH_BASE_URL` 未配时回落主端点（分流需显式配置）
- 嵌入本地 bge-small-zh-v1.5；本机 pytest 必设 `HF_HUB_OFFLINE=1`
- LLM 时延预算：请求路单次不重试各限时档（12/15/30/60s），超时降级回模板

## Known Issues

- 引擎缺口清单七项在 wayfinder 地图雾区（top5 截断、计划级明细召回、双实体素材级对比不可达等）——agent 均诚实降级不编数，修复另立 effort
- 种子陈旧性：任意「最近 N 天」从今天滚动必落 2026-09-28 后空档（golden data_window 已注记）

## Completed

- [x] 八步路线收官（README §7.1）
- [x] 真实系统化升级 M1–M12（spec 2026-10-24）
- [x] web 公网演示（A 机 nginx 唯一公网面）
- [x] 评测三件套：pytest 全量绿（时点值见 AGENTS.md）· golden 38 题 · promptfoo 24/24
- [x] agent 场景集基建 + T1–T4 真实化题收官（query/stat 10 题/comparison 7 题）

---
快照日期：2026-10-31
