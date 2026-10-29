---
type: task
status: open
assignee:
blocked-by: [T2-query-realistic, T3-stats-realistic, T4-comparison-realistic]
labels: [wayfinder:task]
---

# T6 promptfoo 越权交叉扩容

## Question

promptfoo 多角色矩阵现 24/24，但新题型问法（真实措辞统计/对比/夹带两事的查询）没进越权面。本票补**「真实角色 × 新题型问法」交叉用例**：

- 从 T2/T3/T4 已定调的真实措辞里挑越权敏感问法，× 角色矩阵（管理层/优化师/客户/财务）出交叉用例
- 重点面：客户角色问别的品牌的统计/对比（期望行级过滤+诚实说明）；财务角色指标级权限（毛利/ROI 类 deny 联动——deny cost 连带 cpa/roi 的派生铁律）；deny_properties 属性黑名单在 graph 路出口的执行
- **fail-closed 判据**：不该看到的不得出现（含间接泄漏——汇总数字反推单行）；诚实说明算过，漏数据不说明也算过、静默错答不算
- 数量控制在小而尖（8~12 用例），`--no-cache` + 串行跑（既有约定）

## 验收

- 交叉用例入 promptfooconfig 矩阵，全绿
- 既有 24 用例零回归；文档同批改
