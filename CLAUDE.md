# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目现状与最高规则

- **设计阶段**：仓库目前是 README.md（600+ 行设计基线）+ `.env.example`，代码按 README §7.1 的八步路线（Phase 0–6）逐步落地。README 是唯一规范：**任何设计、接口、约定变更，先改 README 再写代码**，保持文档-代码同步
- 中文项目：文档、代码注释、提交信息全部用中文；README 文风是高密度短句 + 表格，修改时保持
- 换行业的重写边界只在 README §9.6 声明一处，其他位置只指回该表，不得另立口径

## 常用命令（代码就绪后生效）

```bash
docker compose up -d                         # PostgreSQL 18 :5433 · Neo4j 2025.09 LTS :7474/7687
uv sync
cp .env.example .env                         # 填 API key、service token
uv run python scripts/init_db.py             # 建表 + Postgres 双账号(adkg_rw/adkg_ro) + Neo4j 约束
uv run python scripts/load_seed.py           # 导入 data/seed/
uv run uvicorn adkg.api.main:app --reload    # http://127.0.0.1:8000/docs
```

评测 `uv run python eval/run_eval.py`（三路 vs 双路 / 双路+Text2SQL 消融）；测试 `uv run pytest tests/`。

## 架构大图

AdKG 是本体驱动的广告营销知识中台，为 Agent 引擎 **smartServe**（独立仓库 agent-all）提供"查什么、能动什么"的依据——只暴露 HTTP API（`/ask` `/graph` `/actions/check` `/guideline/check` `/ingest/*`），不内置编排。

七层自下而上：`ontology/`（唯一语义真源，横贯所有层）→ `connectors` → `pipeline` → `store`（五层存储）→ `retrieval`（vector / graph / text2sql 三路召回 + router）→ `guards` → `api`。

数据流严格单向：`connectors → data/raw/（不可变）→ pipeline（Postgres 先、Neo4j 后，幂等 MERGE）→ 检索层只读`。资产（`ontology/` `sql/` `eval/`）与代码（`adkg/`）分离，层与层只通过 `adkg/models.py` 交互。

## 不可违背的约定（细则以 README §十二为准）

- **provenance 四元组强制**：source_type / source_id / fetched_at / authority 缺失即拒绝入库
- **权限 fail-closed**：内部角色类白名单+属性黑名单，外部角色全白名单；`guards/permission.py` 是 permissions.yaml → PermissionPlan 的**唯一翻译点**，三路检索与 assemble 出口只消费 plan、不读权限矩阵；指标列权限有派生联动（deny cost 连带 cpa/roi）
- **AdKG 是决策点不是执行点**：`/actions/check` 只裁决（allow/deny + 依据 + audit_id），执行归调用方
- **身份不可自报**：service token → role 由网关注入；本地开发才允许 `ADKG_DEV_AUTH=off` 下 body 传 role
- **事实表素材粒度**（platform × campaign × creative × day）+ 物化 campaign_id / case_id / brand_id 维度列；Text2SQL 只对 unified_metrics 与白名单视图生成，过五道闸（只读账号 · 仅 SELECT · 白名单 · 谓词注入 · LIMIT+超时）
- **实体 ID**：`{class}:{slug}` 平台无关；平台 ID 只作 external_id 进 entity_alias，不进主键
- **authority 由 source_type 查表**（system_of_record 100 > platform_api 80 > official_doc 60 > wiki 40 > conversation 20）；同分比 confidence、再比 fetched_at 取新
- **row_filter 语义**：锚点+路径+方向，沿关系级联收窄，未连通默认不可见；全局类（Metric / Guideline / Channel）豁免

## 环境要点

- `.env` 永不入库（.gitignore 已含）；模板见 `.env.example`（双库连接、LLM/嵌入/重排 API、七枚 role token、飞书凭据）
- 运行形态：智能全走 OpenAI 兼容 API（LLM=GLM，嵌入=Qwen3-Embedding-0.6B），数据资产全本地（seed 进 repo、双库 docker、`data/raw/` 不可变），零云成本
- 数据三层：合成 seed（`scripts/gen_seed.py` 生成静态文件）→ 手工"CRM 导出"（`data/seed/org_people.csv`）→ 平台后台导出文件路（官方 API 留给真实部署方）
