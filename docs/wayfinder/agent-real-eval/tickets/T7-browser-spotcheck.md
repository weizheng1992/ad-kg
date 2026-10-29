---
type: task
status: open
assignee:
blocked-by: [T5-casegen-scenarios]
labels: [wayfinder:task]
---

# T7 浏览器实弹抽查

## Question

API 脚本测不到真实入口的全链路：登录会话 → web 问答 → SSE 流式事件渲染 → 卡片呈现 → 案例草稿**人工确认**按钮 → commit。本票用浏览器实弹（agent-browser 技能）**抽查**（非全量，制图拍板 e=抽查通道）：

- 抽查路径（一条主链）：真实账号登录 → agent 助手页发 1 题真实措辞查询 → 看 SSE 流式事件逐步渲染（thought/工具调用/回复）→ 证据引用可展开
- 案例生成链 1 条：对话产草稿 → **前端确认交互** → commit 成功 → 图上可查（依赖 T5 场景已通）
- 顺手记录：前端渲染有无事件丢失/卡片错形/脱敏展示异常——**只记录，不修**（发现的前端缺陷单独报给用户，不入本图 scope）
- 环境前提：docker 全家桶 + API :8000 + web :5173（bun run dev）

## 验收

- 主链 + 案例链浏览器各走通一遍，截图留痕入 `docs/reports/`（随 T8 收官引用）
- 发现的前端缺陷列清单（不阻塞本图，除非阻断主链）
