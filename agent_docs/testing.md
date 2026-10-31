# Testing

## Required Before Completion

- [ ] Relevant tests pass.
- [ ] Typecheck/build passes.
- [ ] User-visible changes are checked in a browser or device when applicable.
- [ ] No tests were skipped or weakened without human approval.
- [ ] Evidence is reported in the final response.

## Commands

- All tests: `HF_HUB_OFFLINE=1 uv run pytest`（本机必设离线变量；库不在线自动跳集成）
- Single test: `HF_HUB_OFFLINE=1 uv run pytest tests/test_retrieval.py -q`（单文件）；`uv run pytest -k "客户"`（按名筛选）
- Typecheck: Python 侧无独立 typecheck；web 侧 `cd web && bunx tsc -b`
- Lint/format: `ruff check .`（基线 ruff.toml）；web 侧 `bunx oxlint`
- Build: `cd web && bun run build`
- Browser/device check: `cd web && bun run dev` 走页面；评测三件套命令见 AGENTS.md「测试与评测」

## What To Test

| Change type | Minimum check |
|-------------|---------------|
| Pure logic | Unit test |
| API/data flow | Integration test |
| UI behavior | Browser/device check |
| Auth, billing, migrations, deployment | Human review plus focused test |
| AI/tool behavior | Prompt/tool eval plus data-boundary check |

本项目加码（README §十二 约定的落点）：

| 改动面 | 必跑 |
|--------|------|
| 权限/行过滤/脱敏 | 越权零泄漏不变量测试（tests/ 已成文）；fail-closed 验证 |
| 指标口径/汇总比 | golden set `uv run python eval/run_eval.py`；比率聚合 sum(分子)/sum(分母) 断言 |
| 种子数据扩容 | `uv run python eval/recalc_golden.py` dry-run 对账后落盘（锚点不手改） |
| agent 链路 | `uv run python eval/agent_eval.py --rounds 2`（每型 ≥90% 达标门） |
| LLM 降级行为 | 断言回模板路径（LLM 失败不阻塞） |

## AI Checks

- Direct prompt: 「我负责的计划里 CPA 连续 3 天上升的有哪些」→ 事实行直查结果，仅限 responsible_for 级联范围
- Bad/indirect prompt: client 角色问其他品牌 → 拒绝并零泄漏（跨品牌命中即拒绝，行过滤在上游）
- Auth-required prompt: 无 token/cookie → fail-closed 拒答，不降级为公开数据
- Failure case: LLM 超时/限流 → 回口径感知模板，响应 `sql_source` 标注来源；不重试不阻塞
- Tool/action check: `create_case` 仅 ae/admin 动作门；`/actions/check` 只返回 allow/deny + audit_id，不执行
- Data check: 输出与日志不得出现成本毛利（AE 视角）、人名（外部角色）、其他品牌行（client 视角）
