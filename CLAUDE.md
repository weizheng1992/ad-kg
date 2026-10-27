# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目现状与最高规则

- **已建成上线**：README §7.1 八步路线 2026-10-19 收官 + 真实系统化升级（spec 2026-10-24，M1–M12 全交付：登录会话/达人库/案例全生命周期/结算/看板/管理台 RBAC）+ web 公网演示（A 机 nginx 唯一公网面）；核心五端点 `/ask` `/graph/entity` `/actions/check` `/guideline/check` `/ingest/assertion` 真跑通，全量 44 端点
- 评测三件套全绿（时点值，引用注明日期）：pytest 255（截至 2026-10-27 晚，随提交增长）、golden set 38 题（README 记 2026-10-24 终评 95%±抖动、judge 要点命中 32–34/35）、promptfoo 多角色矩阵 24/24
- README 是唯一规范：**任何设计、接口、约定变更，先改 README 再写代码**；中文项目（文档/注释/提交信息）；**提交信息不带任何 Claude 署名**（历史已清洗，勿再引入）
- 换行业的重写边界只在 README §9.6 一处声明；文风高密度中文短句 + 表格；新读者导览在 `docs/introduction.md`

## 常用命令

```bash
docker compose up -d                         # PG18 :5433 · Neo4j 2025.09 :7474/7687 · 星图·模拟 :8100（镜像走 docker.m.daocloud.com 后 retag）
uv sync
cp .env.example .env                         # 凭据已在 .env（永不入库）
uv run python scripts/init_db.py             # 建表（sql/001–010）+ 双账号(adkg_rw/adkg_ro) + Neo4j 约束；幂等
ADKG_USER_PASSWORD=xxx uv run python scripts/init_users.py   # web 登录账号（与 permissions.yaml bindings 对账，漂移即退）
uv run python scripts/gen_seed.py            # 生成种子：CSV 进 data/seed，文档直写 data/raw（幂等，clone 后首跑）
uv run python scripts/load_seed.py           # 主数据+文档+事实入图入库；幂等（嵌入本地当场生成）
uv run uvicorn adkg.api.main:app --port 8000 # API；改代码后要重启（默认没挂 --reload）
cd web && bun run dev                        # 前端 :5173（vite 代理 → :8000；用 bun，pnpm 与 Node 22.23 不兼容）
```

测试与评测：

```bash
HF_HUB_OFFLINE=1 uv run pytest              # 全量 255（库不在线自动跳集成；本机必设离线变量否则 hf-mirror 卡死十分钟级）
uv run pytest tests/test_retrieval.py -q   # 单文件
uv run pytest -k "客户"                     # 按名筛选
bunx promptfoo@latest eval -c promptfooconfig.json -j 1 --no-cache   # 多角色矩阵 24 用例（必须 --no-cache + 串行）
uv run python eval/run_eval.py             # golden set 38 题（LLM judge + 规则判据）
uv run python eval/run_ablation.py         # 消融：multi_hop 图谱增益归因
uv run python eval/recalc_golden.py        # 库值锚点重算（dry-run diff；--yes 落盘幂等；防种子扩容后手工漏改）
uv run python scripts/sync_feishu.py       # 飞书增量同步（.env FEISHU_DOCS/FEISHU_FOLDER；ingest_job+chunks 双判幂等跳过；新 revision 走 supersedes 版本链）
mkdir -p data/logs && sed "s|__REPO__|$PWD|; s|__UV__|$(command -v uv)|" scripts/com.adkg.feishu-sync.plist > ~/Library/LaunchAgents/com.adkg.feishu-sync.plist && launchctl load ~/Library/LaunchAgents/com.adkg.feishu-sync.plist   # 定时增量（每 10 分钟，装在本机 macOS；卸载 launchctl unload）
```

嵌入（load_seed / sync_feishu）本地 bge 当场生成，无需事后回填；跑前设 `HF_ENDPOINT=https://hf-mirror.com`，模型已缓存后设 `HF_HUB_OFFLINE=1`。

## 架构大图

AdKG 是本体驱动的广告营销知识中台，为 Agent 引擎 **smartServe**（`~/Desktop/test/ai/agent-all`，独立仓库）提供"查什么、能动什么"——只暴露 HTTP API，不内置编排。

七层：`ontology/`（唯一语义真源，横贯所有层）→ `connectors`（files/feishu/platforms）→ `pipeline`（chunking/extraction/resolution/etl_facts/case_gen/run 双写编排）→ `store`（raw 不可变 / vector / graph / provenance+ingest_job）→ `retrieval`（router + 三路 + assemble；口径单一来源 metrics.py、汇总比脚手架 stats.py）→ `guards`（auth/permission/action_check/rbac/audit）→ `api`。数据流单向：connectors → `data/raw/`（不可变+hash）→ Postgres 先 Neo4j 后（幂等 MERGE，ingest_job 对账）→ 检索层只读。

`/ask` 链路：认证（resolve_identity，token > cookie > dev）→ **PermissionPlan**（guards/permission.py 是 permissions.yaml → 三路过滤器的唯一翻译点；SQL 谓词案例级优先品牌级兜底）→ 路由（强关键词信规则，弱置信 <0.8 走 LLM）→ 按步执行三路（graph 路命中实体带属性作 `entity` 证据，`deny_properties` 属性黑名单在该出口唯一执行）→ 事实行→图补 join（素材→负责人）→ assemble（去重/缺席路/人名脱敏）→ **agent 总结**（LLM 依据证据生成，带 [#N] 引用；失败回模板）→ audit。

**text2sql 双路**（`retrieval/text2sql.py`）：LLM 自由生成 → `validate_sql` 五道闸静态校验（仅 SELECT/单语句/视图白名单/列白名单——剥 AS 别名与字符串字面量/强制 LIMIT）→ `enforce_predicate` 行谓词包裹 → `enforce_semantics` 注入 `NOT unmatched` → ro 账号执行；任何失败回落**口径感知模板**（指标词/方向反转——成本型越低越好/平台/时间窗/空窗回退注明）。响应 `sql_source` 标注来源。

**权限两平面**：数据面（类/属性/指标列/行过滤）真源 `permissions.yaml` + `.env`；界面权限（菜单/按钮/自定义角色）真源在 DB（app_menu/app_role/app_role_action）。门判一律 `display_role`（账号原始角色）判 `role_allows`——resolve_identity 返回数据面映射后的基角色，直接拿它判门会让 base=admin 的自定义角色绕过 action 配置获写权；角色 CRUD 例外走 `require_system_admin`。自定义角色**角色级零记录**才整体继承基角色 action 集。

## 不可违背的约定（细则以 README §十二为准）

- provenance 四元组强制，authority 由 source_type 查表（代码从 `ontology/authority.yaml` 加载，手给不符值抛异常）
- 权限 fail-closed；外部角色全白名单 + 人名脱敏；指标列派生联动（deny cost 连带 cpa/roi，另两组 impressions→cpm/ctr、clicks→ctr/cvr）
- 汇总比铁律：比率型指标跨行聚合一律 sum(分子)/sum(分母)，禁止对行比率求 avg；口径收口 `retrieval/metrics.py` 单一来源
- AdKG 是决策点不是执行点：`/actions/check` 只裁决（allow/deny + audit_id）
- 实体 ID `{class}:{slug}`；平台 ID 只作 external_id 进 entity_alias；抽取产物**必须先过对齐**（`scripts/enrich_aligned.py` 的 L1 / case_gen 草稿路）才能入图——未对齐直接入图会污染检索（实测教训）；对齐 L3 LLM 判别未实现（L1/L2 + 人审兜底）
- LLM：智谱 **coding 端点** `glm-5.3-flash`（同 key 普通端点仅 glm-4-flash）；批任务（抽取/judge）走 `batch_chat_json`（模型 glm-4-flash；`ADKG_LLM_BATCH_BASE_URL` 未配时回落主端点——现状实际仍打 coding 端点，分流需显式配置）；嵌入**本地** bge-small-zh-v1.5（512 维，需 `HF_ENDPOINT=https://hf-mirror.com`，模型已缓存）；LLM 失败一律降级不阻塞（§7.2 矩阵）；请求路限时档 12/15/30/60s（探测/路由/text2sql 生成/总结），单次不重试
