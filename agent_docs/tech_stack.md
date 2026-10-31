# Tech Stack

Last verified: 2026-10（选型理由全文见 README §五——本文件只留指针级备注）

## Stack

| Area | Choice | Notes |
|------|--------|-------|
| Frontend | React 19 + Vite 8 + Tailwind v4 + shadcn/ui + echarts（bun 管理；pnpm 与 Node 22.23 不兼容） | 演示 + 自助看数 + 知识运营一体；echarts 只用于图谱力导向 |
| Backend | Python 3.11+ / uv · FastAPI 0.146 · Pydantic v2；七层单向数据流 ontology→connectors→pipeline→store→retrieval→guards→api | 数据流单向：connectors → data/raw（不可变+hash）→ PG 先 Neo4j 后（幂等 MERGE）→ 检索层只读；层间只通过 adkg/models.py 交互 |
| Database | PostgreSQL 18 + pgvector 0.8（向量/事实/溯源，adkg_rw/adkg_ro 双账号）+ Neo4j 2025.09 LTS（图） | 选 Neo4j 看 Cypher 多跳表达力与可视化演示，非规模刚需（量级假设见 §五）；本机 docker compose :5433 / :7474-7687 |
| Auth | service token（Bearer 直连路，smartServe/eval 用）+ web 会话 cookie（app_session 7 天滑动）；resolve_identity 优先级 token > cookie > dev | 单人维护相称，不起 OAuth/JWT；每账号绑唯一 role + Person，管理员自由切换身份已移除（不留后门） |
| Styling | Tailwind v4 + shadcn/ui（web/src/components/ui 13 件） | 按钮显隐统一 useCan(action)，与后端 role_allows 同一门 |
| Deployment | 本机 docker compose（PG :5433 / Neo4j :7474-7687 / 星图·模拟 :8100）；A 机 nginx 唯一公网面 + systemd + GitHub Actions 自动发布（docs/deployment.md） | 智能在线、资产在本地：LLM 走 API、嵌入本地，数据资产全本地零云成本 |

## Commands

- Setup: `cp .env.example .env && uv sync && docker compose up -d && uv run python scripts/init_db.py && ADKG_USER_PASSWORD=xxx uv run python scripts/init_users.py && uv run python scripts/gen_seed.py && uv run python scripts/load_seed.py`
- Dev: `uv run uvicorn adkg.api.main:app --port 8000`（改代码要重启，默认无 --reload）；前端 `cd web && bun run dev`（:5173 代理 → :8000）
- Test: `HF_HUB_OFFLINE=1 uv run pytest`（本机必设，否则 hf-mirror 卡死）；`bunx promptfoo@latest eval -c promptfooconfig.json -j 1 --no-cache`
- Typecheck: Python 侧无独立 typecheck（靠 Pydantic 运行时校验 + ruff + pytest）；web 侧 `cd web && bunx tsc -b`
- Lint/format: `ruff check .`（基线 ruff.toml：E4/E7/E9/F，tests 豁免 E402）；web 侧 `bunx oxlint`
- Build: `cd web && bun run build`（tsc -b && vite build）
- Browser/device check: `cd web && bun run dev` 后走页面（登录 → 看板/达人库/案例/管理台；agent 悬浮窗 SSE 流式，可配合 mock-douyin :8100 演示抓取）

## AI Runtime

- Provider/runtime: 智谱 OpenAI 兼容双端点（交互 coding 端点 glm-5.3-flash / 批任务 glm-4-flash `batch_chat_json`）+ 本地 bge-small-zh-v1.5 嵌入（512 维）
- Model can see:
  - Public: 无公网暴露面
  - User-owned: 检索出的证据行/文档 chunk（已过 PermissionPlan 行列过滤 + 人名脱敏）
  - Never send: 凭据、全量库导出、越权行（权限收口在上游过滤器，不靠 prompt）
- Tools/actions: 只读检索 + 总结（答案带 #N 编号引用）；写路径仅 ingest 断言/案例草稿且必过对齐或人审；`/actions/check` 只裁决不执行
- Approval gates: 人审队列 review_queue（冲突/补录）；案例草稿 commit 属 ae/admin 动作门
- Retention/training setting to verify: key 进 .env 永不入库；本机不外发数据（嵌入本地生成）
- Fallback: LLM 失败一律降级回模板不阻塞（README §7.2 矩阵）；请求路单次不重试各限时档（12/15/30/60s）

## Important Patterns

- Data fetching: web 与后端只有一条通路——web → HTTP API 服务层（含认证），不直连 Neo4j/Postgres
- State management: web 会话 session context（useCan 按钮显隐）；后端无长驻状态，PG 连接池共享（min1/max8）
- Forms/validation: 服务端 Pydantic 收口；外部输入在边界校验；text2sql 过五道闸静态校验后才执行
- Error handling: API 结构化错误；LLM 降级不阻塞；audit_log 只追加留痕
- Logging/monitoring: audit 唯一 INSERT 收口（guards/audit.py）；data/logs 承载 launchd 同步日志；deploy/alerts/health_alert.sh
- 单一来源清单：本体 ontology/ · 指标口径 retrieval/metrics.py · 汇总脚手架 stats.py · 权限翻译 guards/permission.py · HAVING 阈值 metrics.STAT_HAVING——改口径只动单源，禁止同形复制
