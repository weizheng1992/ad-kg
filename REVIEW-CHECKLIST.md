# Review Checklist

Do not mark work complete until the relevant checks pass.

## Basic Checks

- [ ] Diff is focused on the requested task.
- [ ] No unrelated files were rewritten.
- [ ] No secrets, tokens, private logs, or production exports were exposed.
- [ ] Protected areas were not changed without approval.
- [ ] Tests/typecheck/build passed or failures are explained.
- [ ] UI changes were checked in a browser/device when applicable.

## Security

- [ ] Dependencies audited (`npm audit` or equivalent) — no unaddressed high-severity findings.
- [ ] All user input is validated and sanitized at the boundary (forms, API payloads, URL params).
- [ ] Auth-protected routes and actions were tested while logged out.
- [ ] Rate limiting (or equivalent abuse protection) considered for public endpoints.

## AI Checks

Use only if AI, MCP, tool calls, RAG, local models, or builders are involved.

- [ ] Model-visible data is documented.
- [ ] Retrieved docs/web/issues/uploads/tool output are treated as untrusted data.
- [ ] Risky actions require approval.
- [ ] Direct, bad/indirect, auth-required, failure, and tool/action checks passed.
- [ ] Logs/traces do not expose secrets or customer data.
- [ ] Provider retention/training settings were checked before launch.
- [ ] Builder output passed export, local build, secrets, auth/RLS, and rollback review.

## AdKG 项目特有

- [ ] 设计/接口/约定变更已**先改 README** 再动代码（README 是唯一规范）。
- [ ] 未引入第二规范源：agent_docs/ 与 docs/PRD·TechDesign 是薄指针，规范内容只落在 README。
- [ ] 单一来源未分叉：指标口径（metrics.py）、权限翻译（guards/permission.py）、汇总脚手架（stats.py）、HAVING 阈值（STAT_HAVING）改动只动单源。
- [ ] 评测数值锚改动走 `eval/recalc_*.py` dry-run 对账后 `--yes` 落盘（不手改锚点）。
- [ ] 权限/行过滤/脱敏改动跑越权零泄漏不变量测试（fail-closed 验证）。
- [ ] 评测数字为时点值，引用注明日期；pytest 全量计数与 AGENTS.md 时点值同批更新。
- [ ] 提交信息中文、不带任何 Claude 署名。

## Final Evidence

The final response should include:

- Files changed
- Commands run
- Test/build/browser results
- AI/tool eval results, if applicable
- Remaining risks
