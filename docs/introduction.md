# AdKG 项目详细介绍

> 本文是面向新读者的导览：它是什么、为什么这样设计、数据怎么进来、一次问答怎么发生、权限怎么管、怎么跑起来。**规范真源是 [README.md](../README.md)（设计与约定）、[docs/deployment.md](deployment.md)（部署运维）、[docs/specs/](specs/)（拍板记录）**——本文与三者冲突时一律以 README 为准；本文不复述约定清单，只讲机制与脉络。

- **一句话**：把"文档知识"与"平台效果数据"按同一套领域本体建模，用知识图谱 + 向量 + Text2SQL 三路召回回答跨系统问题，并以本体为边界管控 Agent 的检索与操作，全链路可溯源
- **在线演示**：<http://152.136.165.95>（数据全合成，账号由 `scripts/init_users.py` 开通）
- **状态**：已建成并上线（八步建设路线 2026-10-19 收官；真实系统化升级 M1–M12 于 2026-10-24 全交付；A 机单机运行，push main 自动发布）

---

## 一、它是什么

### 1.1 定位

AdKG（Ad Knowledge Graph）是**本体驱动的广告营销知识中台**，业务域为 App 引流效果广告（抖音 / 小红书投放），主线实体是**案例**（proposal → live → closed）。它是**知识与管控层**：只暴露 HTTP API，不内置 Agent 编排——为 Agent 引擎（如独立仓库 smartServe）提供"**查什么、能动什么**"的依据。

三条边界记住就不会用错：

| 边界 | 含义 |
|---|---|
| 决策点不是执行点 | `/actions/check` 只裁决 allow/deny + 依据 + audit_id，执行归调用方；裁决与回执分两段——`POST /actions/receipt {audit_id, outcome}` 补写审计链新行引用原裁决（2026-10-28 落地） |
| 只暴露 HTTP API | web 前端、smartServe、其他业务系统一律走 API + 认证，不直连 Neo4j / Postgres |
| 检索层只读 | 写路径全部在 connectors → pipeline 一侧，数据流单向 |

### 1.2 解决什么问题

双路召回（wiki 条目 + RAG 向量）答"文档里写了什么"没问题，广告业务有四类问题它答不了：

| 类型 | 典型问题 | 双路 RAG 为什么不够 |
|---|---|---|
| 多跳关系 | A 品牌对接人名下还有哪些 live 案例？ | 答案是跨实体的关系链，不在任何单篇文档里 |
| 事实数据 | 上月抖音 CPA 最差的三个素材是哪些？ | 答案在平台报表里，不在文档里 |
| 口径冲突 | 同一素材抖音和小红书的 CTR 能比吗？ | 两平台字段定义不同；文档新旧版本矛盾，相似度检索无法仲裁 |
| 操作管控 | 帮我删掉 B 案例的这条素材 | Agent 执行动作需要权限边界、约束校验和审计 |

判断标准：单类命中各有便宜解（事实数据加一路 Text2SQL 就够），**两类以上才需要共享语义模型**。广告业务四类全中。与替代方案的逐项对比见 README §1.2。

### 1.3 和 smartServe 的分工

| | smartServe（agent-all 仓库） | AdKG（本仓库） |
|---|---|---|
| 角色 | Agent 引擎：LangGraph 多 Agent 编排、工具调用、对话 | 知识中台：本体、图谱、三路召回、管控 |
| 调用 | 持 service token 调 `/ask` `/graph` `/actions/check` `/guideline/check`，注册为工具 | 为引擎提供"查什么、能动什么" |
| 故障边界 | AdKG 不可用时 fail-closed：报错明示原因，不旁路不缓存降级 | 凭据不向引擎暴露；可用性由自身负责 |

## 二、核心概念速览

| 概念 | 一句话 | 细节 |
|---|---|---|
| 本体（ontology/） | 唯一语义真源，横贯全部七层代码 | 13 个实体类、17 种关系、Case 状态机约束、8 个数据面动作词；schema（T-Box）与实例（A-Box）分离 |
| provenance 四元组 | 任何入库必带 source_type / source_id / fetched_at / authority，缺失拒绝入库 | authority 由 source_type **查表派生**（手给不符值直接抛异常），不单独配置；溯源、审计、冲突仲裁的前提 |
| authority 权威度 | 五级：system_of_record(100) > platform_api(80) > official_doc(60) > wiki(40) > conversation(20) | 同一事实冲突取高者（运行时在断言写回/达人录入等低权威写路径执行；常规 MERGE 直接覆盖），低者进人审；同分比 confidence、再比 fetched_at 取新（authority.yaml 仲裁契约） |
| 实体 ID | 格式 `{class}:{slug}`（如 `Case:C-2026-008`），平台无关 | 平台 ID 一律只作 external_id 进 `entity_alias`，绝不进主键——跨平台对齐全靠这张别名表 |
| Metric 口径 | Metric 类存指标**定义**（公式/粒度/去重规则），不是数值 | 比率型指标跨行聚合一律**汇总比** `sum(分子)/NULLIF(sum(分母),0)`，禁止对行比率求 avg；口径单一来源收口 `adkg/retrieval/metrics.py` |
| PermissionPlan | permissions.yaml 一份矩阵翻译成三路检索过滤器 + 脱敏规则的**唯一翻译点**（guards/permission.py） | 三路与 assemble 出口只消费 plan、不读权限矩阵；SQL 谓词案例级优先品牌级兜底 |
| fail-closed | 默认拒绝，显式授权才放行 | 身份缺失 401；行权限展开失败产出 deny-all plan；schema 新增属性默认不可见 |
| 两平面分离 | 数据面权限（类/属性/指标/行过滤）真源在 `permissions.yaml` + `.env`；界面权限（菜单/按钮/自定义角色）真源在 DB | 权限管理页只是数据面的只读投影 |

## 三、系统架构

七层自上而下，本体层横贯所有层：

```text
              ┌───────────────────────────────────────────────┐
              │        使用方 / Agent 引擎                     │
              │   smartServe · web 前端 · 其他业务系统         │
              └──────────────────────┬────────────────────────┘
                                     │ HTTP API（token / 会话 cookie 认证）
┌────────────────────────────────────▼────────────────────────────────────┐
│ 服务层  adkg/api          44 端点：/ask · /graph · /actions/check ·       │
│                           /guideline/check · /ingest/* · /agent/chat* ·  │
│                           /creators · /cases · /brands · /settlements ·  │
│                           /stats · /auth/* · /admin/* · /menus 等        │
├──────────────────────────────────────────────────────────────────────────┤
│ 管控层  adkg/guards       认证收口 · PermissionPlan · 操作裁决 · RBAC ·   │
│                           审计（只追加）                                  │
├──────────────────────────────────────────────────────────────────────────┤
│ 召回层  adkg/retrieval    router（规则优先，弱置信走 LLM）→ graph │        │
│                           text2sql │ vector → assemble → agent 总结      │
├──────────────────────────────────────────────────────────────────────────┤
│ 存储层  adkg/store        raw │ vector(pgvector) │ graph(Neo4j) │         │
│                           provenance/ingest_job │ creator_quotes │ pg_pool│
├──────────────────────────────────────────────────────────────────────────┤
│ 加工层  adkg/pipeline     chunking → extraction → resolution（对齐）→     │
│                           etl_facts · case_gen · run（双写编排+对账）     │
├──────────────────────────────────────────────────────────────────────────┤
│ 接入层  adkg/connectors   files · feishu · platforms（只拿原始数据，      │
│                           不做语义解释）                                  │
├──────────────────────────────────────────────────────────────────────────┤
│ 本体层  ontology/         schema · authority · permissions · mappings     │
│                           ↑ 唯一语义真源，横贯以上所有层                  │
└──────────────────────────────────────────────────────────────────────────┘
```

目录导览（实际文件）：

| 位置 | 内容 |
|---|---|
| `ontology/` | schema.yaml（13 类 / 17 关系 / 状态机 / 动作词）、authority.yaml、permissions.yaml、mappings/{douyin,xiaohongshu}.yaml（平台列 → 统一指标；小红书是中文表头，在映射层翻译） |
| `adkg/models.py` | 层间 Pydantic 契约：Provenance / Entity / Relation / Fact / PermissionPlan / RouterPlan |
| `adkg/llm.py` | LLM 与嵌入适配层（见 §九） |
| `adkg/connectors/` | base（协议：fetch 产 RawRecord 必带 provenance）、files、feishu、platforms |
| `adkg/pipeline/` | chunking、extraction(+prompt)、resolution、etl_facts、case_gen、run |
| `adkg/store/` | raw、vector、graph、provenance（ingest_job/review_queue/对账）、creator_quotes、pg_pool |
| `adkg/retrieval/` | router、graph_search、vector_search、text2sql、assemble、metrics、stats |
| `adkg/guards/` | auth、http（resolve_identity 收口）、sessions、passwords、permission、action_check、audit、rbac |
| `adkg/api/` | main.py + routes/ 16 个路由模块（44 端点）+ platform_browser（星图·模拟抓取） |
| `sql/` | 001–010 迁移：001 九张核心表、002 unified_metrics 视图、003 会话认证、004 报价历史、005–008 菜单/RBAC、009 序列、010 授权回填 |
| `eval/` | golden_set.jsonl（38 题）、run_eval、run_ablation、judge、recalc_golden |
| `scripts/` | gen_seed、load_seed、init_db、init_users、sync_feishu、enrich_aligned、gen_golden、launchd plist |
| `web/` | 演示前端（§7） |
| `mock-douyin/` | 星图·模拟服务（:8100，纯 stdlib，agent 浏览工具的目标站，与真实抖音零连接） |
| `deploy/` | nginx/adkg-demo.conf、systemd/adkg-api.service、alerts/health_alert.sh |
| `tests/` | 28 个文件 255 个用例（截至 2026-10-27；库不在线自动跳集成） |

## 四、数据是怎么进来的

### 4.1 三层数据

1. **合成种子**——`scripts/gen_seed.py` 生成确定性合成数据（固定随机流，同日重跑逐字节一致）：品牌 24、案例 60、达人 60、素材 ~240、每平台事实行 ~3.1k、SKU 9；案例/规范文档（68 篇 md）由生成器直写 `data/raw/`。事实日期是**滚动近 12 个月窗口**，"上月/近 N 天"类问句不因时间流逝空窗
2. **手工"CRM 导出"**——`data/seed/org_people.csv` 由 `load_seed` 直读入图标 system_of_record（authority 最高级有真实通道）
3. **真实业务数据**——平台走后台导出文件路（官方 API 需真实代理商授权，connector 双 adapter 留给部署方）；飞书自建应用按 revision 增量

### 4.2 管线流程

```text
connector（原始数据+provenance）
  → data/raw/ 不可变落盘（同 key 同内容幂等，不同内容抛错；旁写 sha256）
  → chunking（Markdown 按标题切段，段内超 500 字再二切）
  → Postgres 先：chunks + provenance 入库（嵌入本地当场生成）
  → Neo4j 后：抽取产物幂等 MERGE 入图
  → ingest_job 记两库状态，批次收尾对账（PG 计数 vs 图计数，差异进人审）
```

关键机制：

- **双写顺序铁律**：单篇文档内 Postgres 先、Neo4j 后；失败不跨库留影，按 ingest_job 重放补偿
- **幂等键**：ingest_job/provenance 用 `(source_id, version)`；chunks 用 `(doc_id, chunk_index)`；图层用实体 ID MERGE；raw 用内容 hash
- **抽取三道滤**：类不在 schema 滤、谓词不在白名单滤、三元组端点契约不合法丢弃；置信度 ≥0.7 入图、0.4–0.7 进 review_queue 人审、<0.4 丢弃
- **对齐铁律**：抽取产物**必须先过对齐才能入图**（未对齐直接入图会污染检索）。四级漏斗：L1 规则归一 + alias 命中 → L2 嵌入相似（τ=0.75，top-5）→ L3 LLM 判别（≥0.8 接受）→ L4 人审；**当前代码实现 L1/L2，L3 未做**，L4 体现为 review_queue + 管理台处置
- **事实路 ETL**：平台 CSV 按映射翻译列名（含小红书中文表头）→ entity_alias 换算本体 ID → 从图反查 campaign/case/brand/product 物化进事实行 → 对不上的标 unmatched 进人审、不进跨平台对比
- **文档 → 案例两步走**：定时同步只入 chunks 不建实体；`/ingest/case-draft` 出草稿（LLM 抽取 + L1 对齐，Person 未对齐一律丢弃）、人工确认后 `/ingest/case-commit` 服务端重校验入图（official_doc/60 低权威，冲突时让位主数据）

### 4.3 飞书定时同步

`scripts/sync_feishu.py` 可手动跑，也可 launchd 挂每 10 分钟（plist 模板在 `scripts/`，装在本机 macOS，服务器侧不配）。每轮按 `(source_id, version)` 双判幂等跳过（ingest_job 两段 done **且** chunks 仍有该文档块）；只有新 revision 才进流水线。chunk 面恒为最新版，历史版本保留在 raw（`@rev` 键）+ DocVersion `supersedes` 版本链里。已实现 10 篇在册文档双端同步闭环（.env FEISHU_DOCS 口径；raw 另含历史文档版本）。

## 五、一次问答是怎么发生的

`POST /ask` 全链路（响应含 answer / evidence / routes_used / permission_applied / degraded / answer_source / sql_source）：

```text
提问 → 认证（token > cookie > dev，三级解析）
     → PermissionPlan（按角色把权限矩阵翻译成三路过滤器）
     → 路由（规则关键词优先，弱置信才走 LLM）
     → 按步执行三路（每路先过权限过滤）
     → 事实行 → 图补 join（素材 → 负责人 / 违反规范）
     → assemble（去重、缺席路标注、人名脱敏）
     → agent 总结（LLM 依据证据生成，带 [#N] 引用；失败回模板）
     → 审计
```

### 5.1 路由

| 意图 | 示例 | 路线 |
|---|---|---|
| 事实聚合 | 上月 CPA 最差的素材 | text2sql |
| 关系链 | 对接人名下的 live 案例 | graph（vector 补描述） |
| 概念 / 规范 | 视频时长规范是什么 | vector（graph 定位规范节点） |
| 归因混合 | 效果差与规范有没有关系 | graph → text2sql → vector **串行** |
| 操作类 | 删掉这条素材 | 不进 /ask，返回 /actions/check 指引 |

规则路由置信 0.85–0.95 直接信规则；只有 fact 带锚词（名下/负责/对接，降至 0.75）和 unknown（0.3）两类会花 15s 问 LLM。护栏：锚词让贤、定义尾短路（"XX 是什么意思"归 concept）、状态限定词如实标注不进 SQL、硬聚合信号优先。

### 5.2 三路召回

- **graph 路**：实体定位（ID / 名称 / slug / person 锚）→ 1/2/3 跳邻域 → 可见集过滤。命中实体的**属性作为 entity 证据**返回（`Product.target_age` 这类属性型问题由此可答）；属性黑名单 deny_properties 在该出口唯一执行；外部角色 Person.name 掩码为"＊＊"
- **text2sql 路（双路设计）**：LLM 自由生成 → `validate_sql` 五道闸静态校验 → 行谓词外层包裹 → 注入语义不变量（NOT unmatched）→ **只读账号**执行；任何失败回落**口径感知模板**（指标词/方向反转——成本型越低越好/平台/时间窗/空窗回退注明）。五道闸：① 只读账号 + 3s 超时 ② 仅 SELECT 单语句 ③ 视图白名单（仅 unified_metrics）+ 列白名单（剥 AS 别名与字符串字面量）④ 行谓词系统包裹（生成 SQL 提到 brand_id 不算已施加行过滤）⑤ 强制 LIMIT（缺省补 LIMIT 50）。响应 `sql_source` 标注来源：template / llm+五道闸 / template(fallback)
- **vector 路**：pgvector 余弦相似 + 每类配额（≤3）+ 权限子句下推（未分类 chunk 视为公共内容可检索）；嵌入不可用时降级关键词检索（ILIKE + Guideline 优先）——**降级检索不降权限**

### 5.3 融合与总结

assemble 按 ref 去重保序（v1 用保序去重替代 RRF），标注缺席路（degraded）；权限过滤对外仅布尔 permission_applied（计数与明细进审计）；agent 总结要求只依据证据、结论先行、markdown 表格、每条事实带 [#N] 引用、实体用中文名；证据里的本体 ID 批量转中文名。LLM 不可用或超时回模板摘要（answer_source: agent/template）。

### 5.4 时延预算与降级

请求路 LLM 调用**单次不重试、各自限时**：

| 调用 | 限时 |
|---|---|
| LLM 探测 | 12s |
| LLM 路由 | 15s |
| text2sql 生成 | 30s |
| agent 总结 | 60s（前序已耗 ≥60s 则不再发起） |
| /agent/chat ReAct | 每轮 60s，整循环墙钟 120s |

端到端压在 nginx 150s 内；SSE 独立 300s。任何 LLM 失败一律降级不阻塞：路由回规则、总结回模板、text2sql 生成失败回落口径感知模板、模板仍败才明示"事实数据缺席"——不编数。Neo4j 不可用：graph 步跳过并标注缺席路、其余路照常（三路执行统一 try/except，单路异常不穿透为整问 500）；Postgres 不可用则服务不可用（事实与向量同库，接受该单点）。

## 六、权限与管控

### 6.1 身份

- **Bearer token 路**（smartServe / eval 直连）：静态 service token（每 role 一枚，`ADKG_TOKEN_<ROLE>` 环境变量），token → role；person 取 bindings 唯一绑定（零绑/多绑时回退自报兜底），role 不采信请求体自报
- **Web 会话路**：`POST /auth/login` 校验 `app_user`（scrypt + 等时哑校验防用户名探测），签发 `app_session` 支撑的 HttpOnly cookie（7 天滑动、可吊销、登录成败均审计）
- **dev 兜底**：仅 `ADKG_DEV_AUTH=off` 时允许 body 传 role（本地开发）
- 解析优先级 **token > cookie > dev**，统一收口 `guards/http.py::resolve_identity`；未知角色 401

数据面 7 个角色：ae / optimizer / creative / client（外部）/ finance / management / admin。内部角色类白名单 + 属性黑名单；外部角色 client 一律白名单（allow_properties / metrics_allow）。指标列派生联动：deny cost 连带 cpa/roi（防乘法反推）。Agent 受托调用可带 agent_id（审计记双身份；权限取交集是最小权限设计目标，求交未实现）。

### 6.2 行权限与 fail-closed

row_filter 语义 = 锚点 + 路径 + 方向（如 `Person(responsible_for)->Case<-belongs_to-Campaign-uses->Creative`），展开成图可见集，沿关系级联收窄。三处 fail-closed：身份缺失 401；person 缺失 / 图中无此人 / 展开为空 → **deny-all plan**（graph/vector 零证据、text2sql 恒假谓词 1=0）；schema 新增属性默认不可见。SQL 谓词**案例级优先、品牌级兜底**（optimizer 的"负责案例"粒度 ≠ 对接品牌，品牌级会错杀）。

### 6.3 操作裁决与审计

`POST /actions/check`：权限前置（op 必须在该角色的动作词表内）→ ActionChecker 按 schema.yaml 约束裁决（Case 状态机 proposal→live|lost、live→closed|terminated 终态不可逆；live/closed 不可删 Creative；terminated 必填原因）→ 审计落账 → 返回 decision + reason + audit_id。审计全库唯一 INSERT 收口（guards/audit.py），audit_log 只追加（adkg_rw 账号级收回 UPDATE/DELETE），verdict 库级 CHECK 枚举。

### 6.4 脱敏

三处不同实现：graph 路 Person.name 属性掩码；assemble 出口对证据文本做人名 →"＊＊"替换（仅外部角色）；cases/brands 路由对 owners 置空。Person 不存联系方式，对外部角色整体不可见。

## 七、前端与运营台（web/）

技术栈：React 19 + react-router 8（库模式）+ Vite 8 + TypeScript + Tailwind v4（无 config，CSS 变量）+ shadcn/ui（源码内嵌 13 件）+ echarts（力导向图谱）；**包管理必须 bun**（pnpm 与 Node 22.23 不兼容）。

| 页面 | 谁用 | 端点 |
|---|---|---|
| 数据看板 `/` | management/ae/optimizer/finance（client 只看自己品牌） | `/stats/overview` |
| 达人库 `/creators` | management/ae/optimizer（finance 结算视角） | `/creators`；录入/CSV 导入构成四来源梯度（种子 100 > 平台抓取 80 > official_doc 60 > conversation 20） |
| 案例 `/cases` | management/ae/optimizer/client | `/cases` + `/cases/{id}`：列表汇总比指标 + 详情六段（含状态流转条/拒因）；阶段迁移由详情下发的 transitions 驱动，前端不手抄状态机 |
| 客户 `/brands` | management/ae；client 只看自己 | `/brands` |
| 财务结算 `/settlements` | management/finance | `/settlements` |
| 图谱 `/graph` | management/ae/optimizer/creative | `/graph/entity`（echarts 力导向；实体点击展开；统计卡汇总比 + 交易侧；被权限过滤的边计数可见） |
| Agent 助手（全局悬浮窗） | 所有人 | `/agent/chat/stream`（SSE 唯一端点：thought/tool_start/tool_step 含截图/tool_result/reply/draft/done/error；案例草稿确认走 /ingest/case-commit，can_commit_case 服务端下发） |
| 管理后台 `/admin` | management/admin（读门 admin_view） | 审计流水 + 人审队列处置 + 账号一览 |
| 人员/权限/菜单 `/people` `/permissions` `/menus` | admin（写门） | 账号 CRUD（改绑即吊销会话）；权限树双写单事务；菜单 table-tree（path/action 词表锁定） |

按钮显隐统一 `useCan(action)`（与后端 role_allows 同词表）；侧边栏由 `GET /menus` 数据驱动。角色由登录账号唯一决定（演示期自由切换身份已移除，真系统不留后门）。

## 八、评测体系

三件套（批任务，永不上服务器）：

| 件 | 是什么 | 当前值（截至 2026-10-27） |
|---|---|---|
| pytest | 回归底座 | 255 用例 / 28 文件（截至 2026-10-27；库不在线自动跳集成；本地跑前设 `HF_HUB_OFFLINE=1`） |
| golden set | `eval/run_eval.py` 进程内逐题打 /ask，规则判据 + LLM judge 双轨 | 38 题（multi_hop 17 / fact 10 / concept 4 / attribution 4 / operation 3）；README 记 2026-10-24 终评整体 95%±抖动（judge 要点命中 32–34/35、规则判据 multi_hop 17/17）；本地最新复跑 37/38 |
| promptfoo | 多角色矩阵，真 HTTP 打 /ask | 24 用例覆盖 6 角色（management 13 / client 6 / optimizer 2 / creative、finance、admin 各 1；客户场景/角色矩阵/多维度/边界注入四组）；必须 `-j 1 --no-cache` 串行关缓存 |

消融归因（`eval/run_ablation.py`）：vec_only（≈双路 RAG）/ vec_sql（≈双路+Text2SQL）/ full 三配置对拍——20 题种子期 multi_hop 子集 0/5 → 5/5，增益归因图谱；fact 子集与双路+Text2SQL 预期打平（消融边界——图谱不靠它赢，标出边界比全赢更可信）。

库值锚点重算（`eval/recalc_golden.py`）：种子扩容/口径调整后按当前库重算期望数值与实体锚（聚合口径复用 metrics.agg_expr，不自造口径），dry-run 出 diff、`--yes` 落盘、幂等。

## 九、LLM 与嵌入

| 项 | 选型 | 用法 |
|---|---|---|
| 交互路 LLM | 智谱 **coding 端点** `glm-5.3-flash` | 路由/总结/agent 对话/探测；单次不重试各自限时（§5.4） |
| 批任务 LLM | `glm-4-flash`（batch_chat_json） | 抽取/judge/草稿生成（coding 端点限流严——`ADKG_LLM_BATCH_BASE_URL` 未配时回落主端点）；同 key |
| 嵌入 | 缺省本地 `bge-small-zh-v1.5`（512 维、cosine、HNSW；配 `ADKG_EMBED_BASE_URL` 可切 OpenAI 兼容 API） | load_seed/sync_feishu 当场生成，无需事后回填；首跑设 `HF_ENDPOINT=https://hf-mirror.com`，已缓存后设 `HF_HUB_OFFLINE=1` 断网防卡 |

数值/成本/毛利只在本地 Postgres 执行——Text2SQL 天然数值不出库，这是相对"数仓喂 LLM"方案的现成加分项。

## 十、部署与运维

两机拓扑（详见 [docs/deployment.md](deployment.md)）：

- **A 机**（付费 2C4G，152.136.165.95）：PG18 + Neo4j + mock-douyin 走 docker compose，API 走宿主机 systemd（uv + uvicorn，无 --reload）；nginx 唯一业务公网面（80；另开 SSH 22 与 WireGuard UDP 51820 限 B 机），5433/8000/7474/7687 一律不对公网；内存全链压限（PG 768m / Neo4j 1280m / mock 128m / API MemoryMax 1.5G）
- **B 机**（免费 2C4G）：smartServe；两机 WireGuard 点对点隧道（A 机 10.10.0.1 / B 机 10.10.0.2）
- **本机 macOS**：launchd 每 10 分钟飞书增量同步；批任务（评测/promptfoo/批量抽取）都在本地跑

自动发布：push main 触发 GitHub Actions——runner 上 bun 1.4.0 构建 web → SSH 部署（pull + init_db 幂等建表 + 重启 API + web 静态原子轮换 + nginx conf 同步 reload + 健康断言最多 18×10s）；PR 只跑 pytest。失败进飞书群。

监控：A 机 crontab 每 5 分钟健康巡检（探活/磁盘>85%/内存>90%/负载>4，同一故障 30 分钟节流，异常进飞书群）。

## 十一、本地快速开始

```bash
docker compose up -d                         # PG18 :5433 · Neo4j :7474/7687 · 星图·模拟 :8100
uv sync
cp .env.example .env                         # 凭据永不入库
uv run python scripts/init_db.py             # 建表 + 双账号(adkg_rw/adkg_ro) + Neo4j 约束；幂等
ADKG_USER_PASSWORD=xxx uv run python scripts/init_users.py   # web 登录账号
export HF_ENDPOINT=https://hf-mirror.com     # 嵌入模型下载（已缓存后改设 HF_HUB_OFFLINE=1）
uv run python scripts/gen_seed.py            # 生成种子：CSV 进 data/seed，文档直写 data/raw（幂等，clone 后首跑）
uv run python scripts/load_seed.py           # 主数据+文档+事实入图入库；幂等
uv run uvicorn adkg.api.main:app --port 8000 # API（改代码后要重启，默认没挂 --reload）
cd web && bun run dev                        # 前端 :5173（vite 代理 → :8000）
```

评测：`HF_HUB_OFFLINE=1 uv run pytest`（全量 255）· `uv run python eval/run_eval.py`（golden set）· `bunx promptfoo@latest eval -c promptfooconfig.json -j 1 --no-cache`（24 用例）。

## 十二、能力边界与扩展

- **换行业**：只换资产（ontology 四件 + sql 事实表/视图 + gen_seed + golden set），代码不动——重写边界**只在 README §9.6 一处声明**，本文不另立版本
- **不做的**：Agent 编排（归 smartServe）、操作执行（只裁决）、AIGC 语义/多模态比对（归 AIGC Agent 或人工，AdKG 收口规范检索与断言写回）
- **已知留白**：对齐 L3 LLM 判别未实现（L1/L2 + 人审兜底）；平台官方 API adapter 留给真实部署方（演示走后台导出文件路 + mock 星图）；golden set 50 题全量留待真实数据接入后扩
- **适用规模**（拍板值非实测）：品牌 ~50、案例 ~200/年、素材 ~5k、事实行 ~百万级/年、chunk ~1 万——该量级下 Postgres 三元组表也扛得住，选 Neo4j 看重 Cypher 多跳表达力与可视化演示

## 附：文档地图

| 文档 | 内容 |
|---|---|
| [README.md](../README.md) | 唯一规范：设计思想、架构、本体、权限、全部约定（§十二） |
| [docs/deployment.md](deployment.md) | 两机部署、自动发布、网络闸门、监控报警 |
| [docs/specs/2026-10-24-真实系统化升级-spec.md](specs/2026-10-24-真实系统化升级-spec.md) | 真实系统化升级实现契约（§0–§20 拍板全集） |
| [docs/reports/](reports/) | 夜间检查、访客统计等运行报告 |
| 本文 | 项目详细介绍（导览） |
