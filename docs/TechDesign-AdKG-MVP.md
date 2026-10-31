# TechDesign-AdKG-MVP（薄指针，非规范）

```json
{
  "schemaVersion": 1,
  "documentType": "techdesign",
  "appName": "AdKG",
  "stack": {
    "frontend": "React 19 + Vite 8 + Tailwind v4 + shadcn/ui + echarts（bun 管理；pnpm 与 Node 22.23 不兼容）",
    "backend": "Python 3.11+ / uv · FastAPI 0.146 · Pydantic v2；七层单向数据流 ontology→connectors→pipeline→store→retrieval→guards→api",
    "database": "PostgreSQL 18 + pgvector 0.8（向量/事实/溯源，adkg_rw/adkg_ro 双账号）+ Neo4j 2025.09 LTS（图）",
    "auth": "service token（Bearer 直连路，smartServe/eval 用）+ web 会话 cookie（app_session 7 天滑动）；resolve_identity 优先级 token > cookie > dev",
    "styling": "Tailwind v4 + shadcn/ui（web/src/components/ui 13 件）",
    "deployment": "本机 docker compose（PG :5433 / Neo4j :7474-7687 / 星图·模拟 :8100）；A 机 nginx 唯一公网面 + systemd + GitHub Actions 自动发布（docs/deployment.md）"
  },
  "commands": {
    "setup": "cp .env.example .env && uv sync && docker compose up -d && uv run python scripts/init_db.py && ADKG_USER_PASSWORD=xxx uv run python scripts/init_users.py && uv run python scripts/gen_seed.py && uv run python scripts/load_seed.py",
    "dev": "uv run uvicorn adkg.api.main:app --port 8000（改代码要重启，默认无 --reload）；前端 cd web && bun run dev（:5173 代理 → :8000）",
    "test": "HF_HUB_OFFLINE=1 uv run pytest（本机必设，否则 hf-mirror 卡死）；bunx promptfoo@latest eval -c promptfooconfig.json -j 1 --no-cache",
    "lint": "ruff check .（基线 ruff.toml：E4/E7/E9/F，tests 豁免 E402）；web 侧 bunx oxlint",
    "build": "cd web && bun run build（tsc -b && vite build）"
  },
  "aiScope": "LLM 智谱双端点：交互路 coding 端点 glm-5.3-flash、批任务（抽取/judge/草稿）glm-4-flash 走 batch_chat_json；嵌入本地 bge-small-zh-v1.5；LLM 失败一律降级不阻塞、请求路单次不重试各限时档；铁律（权限/汇总比/provenance）不交给 LLM 裁量"
}
```


> **本文件不是规范。** AdKG 技术设计的唯一真源是 [README.md](../README.md)（§四–§八、§十二）与 `docs/specs/` 拍板 spec；本文件仅为 vibeworkflow 工具链（`npx vibeworkflow` / `doctor`）提供入口锚点，不新增任何决策内容。任何与 README 冲突之处，以 README 为准。

## 技术设计内容指针

| 设计要素 | 真源位置 |
|---|---|
| 架构总览（七层单向数据流） | README §三 |
| 目录结构（资产与代码分离） | README §四 |
| 技术栈选型与规模假设（拍板值） | README §五 |
| 数据流程 / 路由决策 / 实体对齐漏斗 | README §七（7.2–7.4） |
| 五层存储 | README §八 |
| 约定细则（provenance / 权限 / 汇总比 / 实体 ID） | README §十二 |
| 真实系统化升级（登录/达人/案例/结算/RBAC） | `docs/specs/2026-10-24-真实系统化升级-spec.md` |
| 部署拓扑与自动发布 | `docs/deployment.md` |
| 开发者速查（命令 / 铁律） | `AGENTS.md`（速查唯一载体；无 CLAUDE.md，Claude Code ≥2.1.277 原生回落读它） |

## Handoff Context（均为指针）

- **stack**：Python 3.11+ / uv · FastAPI · PostgreSQL 18 + pgvector · Neo4j 2025.09 · 智谱双端点 LLM · 本地 bge 嵌入 · web 侧 React 19 + bun（明细见 README §五）
- **不可违背约定**：README 唯一规范（变更先改 README 再写代码）、provenance 四元组、权限 fail-closed、汇总比 sum(分子)/sum(分母)、AdKG 是决策点不是执行点——细则以 AGENTS.md「不可违背的约定」+ README §十二为准
- **验证**：pytest 全量 + golden set + promptfoo 矩阵 + agent 场景集（命令见 AGENTS.md「测试与评测」）
- **mode**：既有系统增量演进，不走新项目规划
