# Product Requirements

PRD 真源是 README——本文件是构建面向短版（vibe 工具链 `docs/PRD-AdKG-MVP.md` 的展开态，同不承载规范）。

## Users

- Primary user: 六类角色（README §9.2 逐角色日常问法表）+ smartServe Agent（受托身份）
- Main problem: 跨系统的广告营销知识散在文档/平台后台/飞书——能搜到文档 ≠ 能回答问题；多 Agent 协作缺管控边界

## Must-Have Features

- 五端点真跑通 - `/ask` `/graph/entity` `/actions/check` `/guideline/check` `/ingest/assertion`（44 端点全量）
- 权限 fail-closed - 越权零泄漏写成不变量测试；外部角色全白名单 + 人名脱敏
- provenance 四元组 - 任何入库必带；缺 provenance 拒绝（不变量测试）
- 汇总比口径 - sum(分子)/sum(分母) 单源 metrics.py；成本型指标方向反转
- 评测三件套全绿 - pytest 全量（时点值见 AGENTS.md）/ golden 38 题 / promptfoo 24/24

## Nice-To-Have Features

- 重排 bge-reranker（仅 vector 路候选精排，graph 链路不进）
- 对齐 L3 LLM 判别（当前 L1/L2 + 人审兜底）
- 多人原始层 MinIO（接口不变）

## Out Of Scope

- Agent 编排（smartServe 边界，README §十三）
- 操作执行（`/actions/check` 只裁决）
- OAuth/JWT（单人维护相称，service token + 会话 cookie 足够）

## Success Signals

- golden set 38 题（README 记 2026-10-24 终评 95%±抖动）
- promptfoo 多角色矩阵 24/24
- agent 场景集四型 --rounds 2 每型 ≥90%
- 同问题不同角色得到不同行和字段（演示级效果六个画面，README §11.1）
