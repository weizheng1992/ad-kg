# PRD-AdKG-MVP（薄指针，非规范）

```json
{
  "schemaVersion": 1,
  "documentType": "prd",
  "appName": "AdKG",
  "phase": "已上线（八步路线收官 + 真实系统化升级 M1–M12 全交付 + web 公网演示；既有系统增量演进，不走新项目规划）",
  "oneLiner": "本体驱动的广告营销知识中台——从「能搜到文档」升级到「能回答跨系统的问题，每个答案可追溯、每个操作有边界」；为 Agent 引擎 smartServe 提供「查什么、能动什么」，只暴露 HTTP API 不内置编排（README §1.4、§十三）",
  "targetUsers": "六类角色（README §9.2）：AE/销售、优化师、创意/AIGC、客户方（外部角色全白名单+人名脱敏）、财务/商务、管理层；Agent 引擎 smartServe 以受托身份调用，权限矩阵对人对 Agent 一致",
  "mustHave": [
    "核心五端点 /ask /graph/entity /actions/check /guideline/check /ingest/assertion（全量 44 端点）",
    "本体唯一语义真源：ontology/（schema/authority/permissions）横贯所有层",
    "provenance 四元组强制，authority 由 source_type 查表派生",
    "权限 fail-closed：类/属性/指标列/行过滤（SQL 谓词案例级优先品牌级兜底）",
    "text2sql 五道闸 + 口径感知模板回落；汇总比一律 sum(分子)/sum(分母) 单源 metrics.py",
    "web 真系统：登录会话/达人库/案例全生命周期/结算/看板/管理台（界面权限与数据面两平面分离）",
    "评测三件套：pytest 全量 + golden set 38 题 + promptfoo 多角色矩阵 24 用例"
  ],
  "notInMvp": [
    "Agent 编排不内置（编排在 smartServe，AdKG 只暴露 API）",
    "操作执行不内置（/actions/check 只裁决 allow/deny——决策点不是执行点）",
    "对齐 L3 LLM 判别未实现（L1/L2 + 人审兜底）"
  ],
  "successMetrics": [
    "pytest 全量绿（时点值随提交增长，以 AGENTS.md 记录为准）",
    "golden set 38 题（README 记 2026-10-24 终评 95%±抖动）",
    "promptfoo 多角色矩阵 24/24",
    "agent 场景集四型（query/stat/comparison/casegen，--rounds 2 每型 ≥90%）"
  ]
}
```


> **本文件不是规范。** AdKG 已建成上线，产品需求的唯一真源是 [README.md](../README.md)；本文件仅为 vibeworkflow 工具链（`npx vibeworkflow` / `doctor`）提供入口锚点，不新增任何决策内容。任何与 README 冲突之处，以 README 为准。

## 需求内容指针

| PRD 要素 | 真源位置 |
|---|---|
| 产品定位与一句话价值 | README §一、§1.4 |
| 现有方案失效面 / 替代方案对比 | README §1.1、§1.2 |
| 适用规模与用户 | README §1.3、§9.1–§9.2（六类角色日常用法） |
| 量化验收口径 | README §11.3（评测三件套时点值以 README 为准） |
| 数据边界与保留 | README §12.6 |
| 换行业的重写边界 | README §9.6（唯一声明处） |

## Handoff Context（均为指针）

- **app**：AdKG——本体驱动的广告营销知识中台，为 smartServe（独立仓库）提供"查什么、能动什么"，只暴露 HTTP API 不内置编排
- **状态**：MVP 已收官并上线（README §7.1 八步路线 + 2026-10-24 真实系统化升级 M1–M12 全交付 + web 公网演示）
- **mode**：既有系统增量演进，不走新项目规划（vibe 工具链按 existing 项目路由：改动用 vibe-change、修复用 vibe-debug）
- **open questions**：不在此维护——当前工作以 `docs/wayfinder/agent-real-eval/` 地图为准
