# Project Brief

需求真源是 README（§一、§九、§十一）——本文件是面向构建的短版，不承载规范。

## Product

- One-line vision: 本体驱动的广告营销知识中台——从「能搜到文档」升级到「能回答跨系统的问题，每个答案可追溯、每个操作有边界」；为 Agent 引擎 smartServe 提供「查什么、能动什么」，只暴露 HTTP API 不内置编排
- Target users: 六类角色（AE/销售、优化师、创意/AIGC、客户方外部、财务/商务、管理层）+ Agent 引擎 smartServe（受托身份，权限矩阵对人对 Agent 一致）
- Primary user outcome: 同一个问题不同角色得到不同的行和字段（本体权限的副作用，不是功能）；答案带 #N 编号引用可溯源，操作有 allow/deny 边界

## Scope

- Must ship:
  - 核心五端点 `/ask` `/graph/entity` `/actions/check` `/guideline/check` `/ingest/assertion`（全量 44 端点）
  - 本体唯一语义真源（ontology/ 横贯所有层）+ provenance 四元组强制
  - 权限 fail-closed（类/属性/指标列/行过滤；指标列派生联动）
  - text2sql 五道闸 + 口径感知模板回落；汇总比单源 metrics.py
  - web 真系统（登录会话/达人库/案例全生命周期/结算/看板/管理台两平面 RBAC）
  - 评测三件套（pytest 全量 / golden 38 题 / promptfoo 24 用例）
- Not in v1:
  - Agent 编排（在 smartServe，AdKG 只暴露 API）
  - 操作执行（决策点不是执行点）
  - 对齐 L3 LLM 判别（L1/L2 + 人审兜底）

## Principles

- Solve the user story before adding polish.
- Prefer boring, maintainable choices.
- Keep generated docs short and current.
- Verify user-visible work in the real product surface.
- 本项目特有：README 唯一规范（先改 README 再写代码）；数据流单向；口径单一来源；LLM 一律可降级。

## AI Position

- AI is used for: /ask 总结（带引用）、路由弱置信兜底、text2sql 生成、抽取/judge/案例草稿（批任务）
- AI is not used for: 权限裁决、汇总比口径、provenance/authority 派生——这些是代码与 ontology 真源，不交给 LLM 裁量
- Human approval required for: review_queue 人审（冲突/补录）、案例草稿 commit
