---
id: agent-real-eval
title: agent 真实化评测
type: map
labels: [wayfinder:map]
status: open
created: 2026-10-29
---

## Destination

AdKG agent 面的**真实化评测扩容**到站：查询/统计/对比三型真实措辞新题（打 `/agent/chat` ReAct 全链路，真实 LLM、真实角色）+ 案例生成生命周期场景脚本（draft→commit→图上落点断言）全部落地，**每型分别 judge ≥90% 且数值锚点全中、连续两轮达标**；promptfoo 补真实角色×新题型越权交叉用例；浏览器实弹抽查通过；报告落 `docs/reports/`，README/CLAUDE.md 评测段同步。现有 golden 38 题冻结不动。

## Notes

- **执行图 override**（2026-10-29 拍板）：票=实现+验证+关闭，地图兼作进度看板；全部子票关闭即到达。
- **制图拍板记录**（grilling 共识，后续票不得翻案除非目的地重画）：
  - 被测面：新增题重点打 `/agent/chat`（内部自调 /ask/检索/案例草稿）；`/ask` 已有 38 题垫底不重复铺；浏览器实弹只作抽查通道。
  - 「真实」=真实措辞（口语/行话/模糊指代/一问夹两事）+ 真实 LLM 全链路（不 mock 不降级，吃 10~90s 时延方差）+ 真实角色权限（管理层/优化师/客户/财务各出题，越权面同测）。
  - 对比型=双实体 + 双平台/双品牌 + 双期间三种问法；期间对比会踩 text2sql 时间窗交叉，票内单独处理。
  - 案例生成走**独立场景脚本通道**（golden JSONL 装不下多步流）：`/agent/chat` 产 draft → 字段断言 → `/ingest/case-commit` → 图上落点断言（对齐、authority、建号约定）。
  - 规模：查询 8~10 题 + 统计 8~10 题 + 对比 6~8 题 + 案例生成场景 4~6 个。
  - 验收口径：**每型分别** judge 要点命中 ≥90% 且数值锚点全中（不允许静默错答）；案例生成按场景断言全过计；**连续两轮达标**才验收（防单轮抖动）。
  - promptfoo 补「真实角色 × 新题型」越权交叉用例；run_ablation 不动（归因工具非质量门）。
- **定调流程（HITL）**：每型先出 2~3 题样例给用户过目拍板定调（口语浓度/模糊度/行话密度），定调后同型批量出、不再逐题过目——判据和锚点兜质量。
- **烧钱授权**：本机 GLM coding 端点 key 授权用于本图评测实弹（含迭代重跑），无单次预算上限，跑前不逐次请示。
- **环境前提**：docker compose 全家桶起（PG:5433 / Neo4j / 星图·模拟 :8100）+ `uvicorn adkg.api.main:app --port 8000` + `HF_HUB_OFFLINE=1`；凭据在 `.env`（永不入库）。
- **README 唯一规范铁律照常适用**：票动到评测入口命令/题型口径/端点行为时，同批改 README/CLAUDE.md，不留文档债到收官。
- **领域铁律引用**（评测断言要守住）：权限 fail-closed、汇总比 sum(分子)/sum(分母) 禁 avg 行比率、LLM 失败降级不阻塞（降级必须进报告 `degraded` 标注，不许静默算过）。
- **Tracker 约定**：本地 markdown（`tickets/` 每文件一票，frontmatter `type/status/assignee/blocked-by`；claim=填 assignee；blocked-by 全 closed 才进 frontier）。

## Decisions so far

<!-- 一行一条 closed ticket：名字链接 + 一句话答案，细节在 ticket 里 -->

- [T1 判据基建：agent 评测执行器](tickets/T1-eval-executor.md)：TestClient 进程内全链路执行器落地（判据三件+judge 在场实体软化+锚点协议三种 kind+written 清理安全），实弹 2 轮×2 场景全绿（48.78 锚落盘、casegen 九项断言+清理），pytest 303 绿；命令入 README/CLAUDE.md

## Not yet specified

- **加码扩容**：每型题数翻倍（20+）——四型跑通、看清单轮成本与抖动分布后再议。
- **多轮追问型题**：第二轮引用第一轮指代（"那它的 CPA 呢？"）——执行器支持多 turn 会话态后才能表述清楚；现 T1 执行器先按单题单流设计。
- **评测常态化**：两轮达标后是否挂 launchd 定时真弹跑（飞书同步先例）——成本分布看清后再议。
- **答案中文名/脱敏断言**：新题要不要把人名脱敏、答案中文名等展示约定一并断言——跑起来看过真实输出形状再定。
- **判据型别细化**：统计/对比题的路由证据断言（走没走 text2sql、sql_source 标注）是否纳入判据——先只判答案内容，跑通后视噪音再决定加严。

## Out of scope

- **种子/数据规模扩容到生产量级**：牵动全量锚点重算，独立 effort 另起（2026-10-29 拍板不与本题混）。
- **现有 38 题措辞真实化改写**：38/38 是已发布评测事实与回归锚，冻结（拍板 a）。
- **run_ablation 扩容**：图谱增益归因工具，非质量门，不动（拍板 a）。
- **smartServe 联调**：跨仓库，AdKG 只测自家 HTTP 面。
- **评测成本优化/换模型分流**：LLM 分流策略不在本图。
