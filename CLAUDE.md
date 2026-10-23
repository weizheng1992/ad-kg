# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目现状与最高规则

- **README §7.1 八步路线全部完成**（2026-10-19）+ web/ 演示前端；五个端点真跑通（`/ask` `/graph/entity` `/actions/check` `/guideline/check` `/ingest/assertion`）；评测三件套全绿（115 pytest、golden set 36 题 89%、promptfoo 多角色矩阵 24/24）
- README 是唯一规范：**任何设计、接口、约定变更，先改 README 再写代码**；中文项目（文档/注释/提交信息）；**提交信息不带任何 Claude 署名**（历史已清洗，勿再引入）
- 换行业的重写边界只在 README §9.6 一处声明；文风高密度中文短句 + 表格

## 常用命令

```bash
docker compose up -d                         # PG18 :5433 · Neo4j 2025.09 :7474/7687（镜像走 docker.m.daocloud.com 后 retag）
uv sync
cp .env.example .env                         # 凭据已在 .env（永不入库）
uv run python scripts/init_db.py             # 建表 + 双账号(adkg_rw/adkg_ro) + Neo4j 约束；幂等
uv run python scripts/gen_seed.py            # 生成种子：CSV 进 data/seed，文档直写 data/raw（幂等，clone 后首跑）
uv run python scripts/load_seed.py           # 主数据+文档+事实入图入库；幂等（嵌入本地当场生成）
uv run uvicorn adkg.api.main:app --port 8000 # API；改代码后要重启（默认没挂 --reload）
cd web && bun run dev                        # 前端 :5173（vite 代理 → :8000；用 bun，pnpm 与 Node 22.23 不兼容）
```

测试与评测：

```bash
uv run pytest                              # 全量 117（数据库不在线自动跳过集成）
uv run pytest tests/test_retrieval.py -q   # 单文件
uv run pytest -k "客户"                     # 按名筛选
bunx promptfoo@latest eval -c promptfooconfig.json -j 1 --no-cache   # 多角色矩阵 24 用例（必须 --no-cache + 串行）
uv run python eval/run_eval.py             # golden set（LLM judge + 规则判据）
uv run python eval/run_ablation.py         # 消融：multi_hop 0/5→5/5 图谱增益归因
uv run python scripts/sync_feishu.py       # 飞书增量同步（.env FEISHU_DOCS；ingest_job+chunks 双判幂等跳过；新 revision 走 supersedes 版本链）
mkdir -p data/logs && sed "s|__REPO__|$PWD|; s|__UV__|$(command -v uv)|" scripts/com.adkg.feishu-sync.plist > ~/Library/LaunchAgents/com.adkg.feishu-sync.plist && launchctl load ~/Library/LaunchAgents/com.adkg.feishu-sync.plist   # 定时增量（每 10 分钟；卸载 launchctl unload）
```

嵌入（load_seed / sync_feishu）本地 bge 当场生成，无需事后回填；跑前设 `HF_ENDPOINT=https://hf-mirror.com`。

## 架构大图

AdKG 是本体驱动的广告营销知识中台，为 Agent 引擎 **smartServe**（`~/Desktop/test/ai/agent-all`，独立仓库）提供"查什么、能动什么"——只暴露 HTTP API，不内置编排。

七层：`ontology/`（唯一语义真源，横贯所有层）→ `connectors`（files/feishu/platforms）→ `pipeline`（chunking/extraction/resolution/etl_facts/run 双写编排）→ `store`（raw 不可变 / vector / graph / provenance）→ `retrieval`（router + 三路 + assemble）→ `guards`（auth/permission/action_check/audit）→ `api`。数据流单向：connectors → `data/raw/`（不可变+hash）→ Postgres 先 Neo4j 后（幂等 MERGE，ingest_job 对账）→ 检索层只读。

`/ask` 链路：认证（token→role，dev 模式 body 兜底）→ **PermissionPlan**（guards/permission.py 是 permissions.yaml → 三路过滤器的唯一翻译点；SQL 谓词案例级优先品牌级兜底）→ 路由（强关键词信规则，弱置信走 LLM）→ 按步执行三路（graph 路命中实体带属性作 `entity` 证据，`deny_properties` 属性黑名单在该出口执行）→ 事实行→图补 join（素材→负责人）→ assemble（去重/得分/缺席路/人名脱敏）→ **agent 总结**（LLM 依据证据生成，带 [#N] 引用；失败回模板）→ audit。

**text2sql 双路**（`retrieval/text2sql.py`）：LLM 自由生成 → `validate_sql` 五道闸静态校验（仅 SELECT/单语句/视图白名单/列白名单——剥 AS 别名与字符串字面量/强制 LIMIT）→ `enforce_semantics` 系统注入 `NOT unmatched` → `enforce_predicate` 行谓词包裹 → ro 账号执行；任何失败回落**口径感知模板**（指标词/方向反转——成本型越低越好/平台/时间窗/空窗回退注明）。响应 `sql_source` 标注来源。

## 不可违背的约定（细则以 README §十二为准）

- provenance 四元组强制，authority 由 source_type 查表（代码从 `ontology/authority.yaml` 加载）
- 权限 fail-closed；外部角色全白名单 + 人名脱敏；指标列派生联动（deny cost 连带 cpa/roi）
- AdKG 是决策点不是执行点：`/actions/check` 只裁决（allow/deny + audit_id）
- 实体 ID `{class}:{slug}`；平台 ID 只作 external_id 进 entity_alias；抽取产物**必须先过对齐**（`scripts/enrich_aligned.py` 的 L1）才能入图——未对齐直接入图会污染检索（实测教训）
- LLM：智谱 **coding 端点** `glm-5.3-flash`（同 key 普通端点仅 glm-4-flash）；批任务（抽取/judge）走 `batch_chat_json`（普通端点，coding 端点限流严）；嵌入**本地** bge-small-zh-v1.5（512 维，需 `HF_ENDPOINT=https://hf-mirror.com`，模型已缓存）；LLM 失败一律降级不阻塞（§7.2 矩阵）
