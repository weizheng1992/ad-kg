---
type: task
status: open
assignee:
blocked-by: [T2-query-realistic, T3-stats-realistic, T4-comparison-realistic, T5-casegen-scenarios, T6-promptfoo-cross, T7-browser-spotcheck]
labels: [wayfinder:task]
---

# T8 收官：两轮全量验收 + 报告 + 文档同步

## Question

全部题型票落地后的**收官验收与文档同步**：

- **两轮全量验收**：查询/统计/对比三型各 ≥90% 且数值锚点全中、连续两轮；案例生成场景断言两轮全过；promptfoo 交叉全绿；pytest 全量绿（含 T1 新增单测）
- **报告**落 `docs/reports/`（沿用既有夜间检查报告文风：高密度中文短句+表格）：四型达标情况、锚点对账表、degraded/降级清单、时延方差观察、发现但未修的缺陷清单（含 T7 前端观察）
- **README/CLAUDE.md 同步**：评测三件套段扩为四型新事实（题型 taxonomy、新命令、时点值+日期标注）——README 唯一规范铁律，收官必改；introduction 若涉及评测叙述一并
- **地图闭图**：本票关闭时地图 status → closed，雾区未毕业项如实留档

## 验收

- 两轮达标报告 + 文档三处同步 + 地图闭图，全部完成后本图到站
