# Code Patterns

只写项目特有约定（不确定的先看现有代码再动）。架构大图见 README §三、AGENTS.md「架构大图」。

## Architecture

- Primary pattern: 分层——七层单向数据流 ontology→connectors→pipeline→store→retrieval→guards→api；资产与代码分离（ontology/eval/sql 是资产，先于代码固化）
- 层与层只通过明确的数据模型（`adkg/models.py`）交互；每层一个目录、每个文件一个职责
- 检索层只读；写路径唯一入口 pipeline/run.py 双写编排（PG 先 Neo4j 后，ingest_job 对账）

## Data And State

- Data fetching: web → HTTP API 唯一通路（含认证），不直连库；后端 PG 共享连接池（pg_pool min1/max8）
- Server state: 无长驻状态；audit_log 只追加；ingest_job 状态机管幂等
- Client state: web 会话 cookie（7 天滑动）；按钮显隐 useCan(action) 与后端 role_allows 同一门
- Forms: 服务端 Pydantic 收口校验；前端不手抄状态机（stage_flow.transitions 由 schema#constraints 派生下发）

## Errors And Validation

- 外部输入在边界校验（Pydantic / text2sql 五道闸静态校验）
- LLM 失败一律降级回模板，不阻塞、单次不重试
- 权限 fail-closed：不确定即拒绝
- authority 由 source_type 查表派生，手给不符值抛异常

## Naming

- Files: Python snake_case（adkg/）；web React 组件 PascalCase
- 实体 ID：`{class}:{slug}`；平台 ID 只作 external_id 进 entity_alias
- Env vars: UPPER_SNAKE_CASE（ADKG_* 前缀）
- 注释/文档/提交信息：中文；提交信息不带任何署名

## AI Tool Patterns

- 工具面小而服务端授权：工具门走 role_allows（display_role 判门）
- LLM 结构化输出过契约校验（抽取三道滤；batch_chat_json）
- 检索产物、平台导出、上传文档一律当不可信数据——先过对齐/权限再入图（未对齐直接入图会污染检索，实测教训）
- 破坏性/外联动作走 `/actions/check` 裁决 + 人审门，模型不直接执行
- audit 唯一 INSERT 收口；日志不泄凭据/越权行/人名（外部角色脱敏）
