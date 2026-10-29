# AdKG — 本体驱动的广告营销知识中台

> 把"文档知识"与"平台效果数据"按同一套领域本体建模，用知识图谱 + 向量 + Text2SQL 三路召回回答跨系统问题，并以本体为边界对 Agent 的检索与操作做管控，全链路可溯源。

**▶ 在线演示**：<http://152.136.165.95>（数据全合成）

- 业务域：App 引流效果广告（抖音 / 小红书投放），主线实体是**案例**（proposal → live → closed）
- 定位：知识与管控层。它不是 Agent 引擎，而是 Agent 引擎（如 smartServe）"查什么、能动什么"的依据
- 状态：**已建成上线**——八步路线（7.1）2026-10-19 收官；真实系统化升级（spec M1–M12）2026-10-24 交付；A 机单机运行，push main 自动发布（docs/deployment.md）
- 新读者导览见 `docs/introduction.md`（项目详细介绍，可独立阅读）；本 README 是设计与约定的唯一规范

目录：[一、为什么使用](#一为什么使用) · [二、核心设计思想](#二核心设计思想) · [三、架构总览](#三架构总览) · [四、目录结构](#四目录结构) · [五、技术栈与规模假设](#五技术栈与规模假设) · [六、本体概览](#六本体概览) · [七、数据流程](#七数据流程) · [八、五层存储](#八五层存储) · [九、如何使用](#九如何使用) · [十、快速开始](#十快速开始) · [十一、使用达到的效果](#十一使用达到的效果) · [十二、约定](#十二约定) · [十三、与 smartServe 的关系](#十三与-smartserve-的关系)

---

## 一、为什么使用

### 1.1 现有方案的失效面

双路召回（wiki 结构化条目 + RAG 向量检索）解决"文档里写了什么"没有问题，但广告业务里有四类问题它答不了或不敢答：

| 类型 | 典型问题 | 双路 RAG 为什么不够 |
|---|---|---|
| 多跳关系 | A 品牌对接人名下还有哪些 live 案例？ | 答案是一条跨实体的关系链，不在任何单篇文档里 |
| 事实数据 | 上月抖音 CPA 最差的三个素材是哪些？ | 答案在平台报表 / 数仓里，不在文档里 |
| 口径冲突 | 同一素材抖音和小红书的 CTR 能比吗？质保 30 天还是 90 天？ | 两平台字段定义不同；文档新旧版本矛盾，相似度检索无法仲裁 |
| 操作管控 | 帮我删掉 B 案例的这条素材 | Agent 执行动作需要权限边界、约束校验和审计 |

**判断标准**：单类命中各有便宜解（事实数据加一路 Text2SQL 就够），两类以上才需要共享语义模型；只是文档问答，双路 RAG 就是终点，上图谱反而是负资产。广告业务四类全中——命中类型标注见 `eval/golden_set.jsonl`（38 题，种子期 20 题），是标注结果不是断言。

### 1.2 与替代方案对比

| 能力 | 双路 RAG | 双路 RAG + Text2SQL* | 现成知识库平台** | 纯 GraphRAG | AdKG |
|---|---|---|---|---|---|
| 文档问答带引用 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 多跳关系（跨实体链） | ✗ | ✗（文档抽取的关系进不了 SQL） | ✗ | ✓（仅文本抽取的图） | ✓（文本 + 结构化源） |
| 效果指标查询 | ✗ | ✓（裸查数仓，无口径约束） | ✗ | ✗ | ✓ 语义层约束下的 Text2SQL |
| 多源口径统一与冲突仲裁 | ✗ | ✗ | ✗ | ✗ | ✓ 映射层 + authority 仲裁 |
| 权限粒度 | 文档目录级 | 文档目录级 | 应用 / 知识库级 | ✗ | ✓ 本体类 / 属性 / 指标列 / 行级 |
| Agent 操作管控 | ✗ | ✗ | 工具级开关 | ✗ | ✓ 约束校验 + 审计 |
| AIGC 合规闭环 | ✗ | ✗ | ✗ | ✗ | ✓ 生成前查规范、生成后写回违反关系 |
| 换行业复用 | 重建 | 重建 | 重建 | 重建 | 只换资产，代码不动（清单见 9.6） |

\* 最便宜的拼装方案：解决"查数"，不解决"关系与口径"——它同时是 11.3 的消融基线。
\*\* 指典型 RAG 编排平台的默认能力，不代表其上限。它们解决单域文档问答没有问题，缺的是**语义层**——多团队的权限、多 Agent 的协作语言、多域的联邦，没有语义层都会退化成目录权限和 prompt 拼接。

### 1.3 适用规模：多团队 · 多 Agent · 多域

**多团队——本体权限模型的主场。** 效果广告代理业务天然多角色：AE、优化师、创意、客户方、财务、管理层，同一个问题"上月效果怎么样"，六类人应得到不同的行数和字段。传统做法是给每个文档目录打密级、每张报表配权限；本体做法只有两件事：**类 / 属性级权限**（创意看不到成本字段）+ **关系级行过滤**（沿 `responsible_for`、`for_brand` 收窄实例范围）。权限不再是散落的配置，而是本体里的不变量：默认不可见，显式授权才可见。各角色的具体用法见 [9.2](#92-六类角色的日常用法)。

**多 Agent——本体是 Agent 之间的共同语言。** 自然的分工有检索问答、投放分析、素材 AIGC、案例撰写、复盘归因五类 Agent。本体为它们解决四个真问题：

1. 统一世界模型：所有 Agent 读写同一套实体 ID 和指标口径，否则实体对齐的债会随 Agent 数量翻倍
2. 权限一视同仁：权限矩阵对人和对 Agent 是同一张；Agent 受托替人调用时，生效权限取 Agent role 与终端用户 role 的**交集**（最小权限；求交为设计目标，现状单 role 调用 + 审计双身份，见 9.1）。**管控收口在知识层**——散在各 Agent 的 prompt 里，每加一个 Agent 就多一份泄露面；收口在本体，Agent 来多少个都是同一套闸门
3. 交接即结构：Agent 之间 handoff 传本体化的结构（实体 + 关系 + provenance），不传自由文本，下游可验证再接
4. 写冲突有仲裁：两个 Agent 对同一实体写入，按 authority 排序，低者进 `review_queue` 人审；同分比 confidence、再比时间取新（见 [12.2](#122-权威度authorityyaml)）——断言写回、达人录入/导入、案例物化与文档抽取四条写入路统一接此规则（2026-10-28 抽取路补齐）

**多域——演进出来的，不是设计出来的。** 先分清两种"多域"：域内子域（投放、素材、客户）一个本体分模块即可；跨业务域（广告 + 电商 + 客服）才需要架构决策。当前覆盖口径：主线 13 类覆盖投放 / 素材 / 客户；财务仅属性级覆盖（`gross_margin`、`settlement_status`），独立结算类二期再议。

| 模式 | 适用条件 | 做法 |
|---|---|---|
| 单本体多命名空间 | 域间共享核心实体，有跨域问题 | 共享"客户 / 组织 / 商品"顶层词汇表，各域模块挂上去 |
| 多本体联邦 + 桥接 | 域间松耦合，偶尔跨域查 | 每域独立 schema，桥接层定义跨域等价关系 |
| 每域独立实例 | 强隔离要求（合规、多租户交付） | 共用代码和基础设施，schema 各自演进 |

判断标准三条：有没有跨域问题、有没有共享实体、有没有隔离要求。两个反模式：一开始就建企业级大一统本体（永远定不完 schema）；各域各建没有顶层词汇表（同一个客户在每个域里是三个不同的人）。正确路径是先把广告一个域做深做透，第二个域真进来时再按标准选模式。

### 1.4 一句话价值

从"能搜到文档"升级到"能回答跨系统的问题，每个答案可追溯、每个操作有边界"。单 Agent 比拼的是能不能答对，多 Agent 比拼的是协作语言和管控边界——这两样都必须沉到知识层。

## 二、核心设计思想

1. **本体不是数据的集合，而是独立于数据源的语义模型。** 数据源通过映射（`ontology/mappings/`）接入本体；schema（T-Box）与实例（A-Box）分离。
2. **图存关系与指针，事实表存数值。** 主数据（品牌、商品、案例、素材）进图；效果指标留在事实表，按 ID 回填到图节点。禁止把业务库全量灌进图谱——那只会得到一份永远过期的副本。
3. **管控前置。** 权限挂在实体类和关系上，默认不可见、显式授权才可见（fail-closed）；操作执行前对本体约束做校验——**AdKG 是决策点不是执行点**：只裁决、审计，不代执行；AIGC 素材生成前先查规范节点，生成后把违反关系写回图。
4. **provenance 强制。** 任何节点、关系、事实、chunk 入库都必须带来源四元组，否则拒绝入库。这是溯源、审计、冲突仲裁的前提，事后补不回来。
5. **原始层不可变。** 原始文件和 API 原始响应落盘后不改；抽取 prompt、schema 或嵌入模型迭代后可全量重跑（换嵌入模型须重刷全部 chunk 向量，新旧不可比）。
6. **评估先行。** golden set 先于功能开发存在，每阶段跑分记入 `eval/runs/`，用它量化收益。

## 三、架构总览

```text
                  ┌───────────────────────────────────────────────┐
                  │        使用方 / Agent 引擎                    │
                  │   smartServe engine-py · 前端 · 其他业务系统│
                  └──────────────────────┬────────────────────────┘
                                         │ HTTP API（token / 会话 cookie 认证）
┌────────────────────────────────────────▼───────────────────────────────────────────────────────┐
│ 服务层   adkg/api   44 端点：/ask · /graph · /actions/check · /guideline/check · /ingest/* ·    │
│                     /agent/chat(/stream SSE) · 数据面(/creators /cases /brands /settlements    │
│                     /stats) · 认证与管理(/auth /admin /menus /roles)                           │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 管控层   adkg/guards   认证收口 · 权限过滤（本体级）· 操作前约束校验 · RBAC · 审计（只追加）    │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 召回层   adkg/retrieval   router（本体理解→路由）→ vector │ graph │ text2sql → assemble        │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 存储层   adkg/store   raw │ vector(pgvector) │ graph(Neo4j) │ provenance/ingest_job │          │
│                     creator_quotes │ pg_pool（事实表由 pipeline/etl_facts 直写）               │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 加工层   adkg/pipeline   chunking → extraction → resolution · etl_facts · case_gen · run       │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 接入层   adkg/connectors   files · feishu · platforms（warehouse 留作扩展）                    │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 本体层   ontology/   schema · mappings · authority · permissions                                │
│                           ↑ 唯一语义真源，横贯以上所有层                                        │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 四、目录结构

设计原则：**资产与代码分离**（`ontology/`、`eval/`、`sql/` 是资产，先于代码固化）；**代码按层分包**，层与层只通过明确的数据模型（`adkg/models.py`）交互；每层一个目录，每个文件一个职责。

```text
ad-kg/
├── README.md                      # 唯一规范（设计与约定）
├── CLAUDE.md                      # 开发者速查（命令 / 架构大图 / 铁律）
├── pyproject.toml / uv.lock       # uv 管理的 Python 项目
├── docker-compose.yml             # PG18(pgvector) + Neo4j + 星图·模拟 三服务
├── promptfooconfig.json           # 多角色矩阵评测（24 用例，真 HTTP 打 /ask）
├── .env.example                   # 连接串、LLM key、service token 模板
│
├── ontology/                      # 【资产】本体：唯一语义真源
│   ├── schema.yaml                #   13 类、17 关系、Case 状态机约束、动作词表(schema#actions)
│   ├── authority.yaml             #   来源权威度五级 + 同分裁决链，冲突仲裁用
│   ├── permissions.yaml           #   角色 → 可见类 / 属性 / 指标列 / 操作 / 行过滤（人和 Agent 共用）
│   └── mappings/
│       ├── douyin.yaml            #     巨量引擎字段 → 统一指标口径
│       └── xiaohongshu.yaml       #     聚光平台中文表头 → 同一套口径（映射层翻译）
│
├── adkg/                          # 【代码】Python 包
│   ├── models.py                  #   层间契约：Provenance（authority 查表派生）/ Entity / Relation /
│   │                              #   Fact / PermissionPlan / RouterPlan
│   ├── llm.py                     #   LLM/嵌入适配：coding 端点 glm-5.3-flash、批任务普通端点
│   │                              #   glm-4-flash（batch_chat_json）、本地 bge 嵌入
│   ├── connectors/                #   接入层：只拿原始数据，不做语义解释
│   │   ├── base.py                #     Connector 协议：fetch() → RawRecord（必带 provenance）
│   │   ├── files.py               #     本地 Markdown / 导出文件
│   │   ├── feishu.py              #     云文档：revision 增量 + 共享文件夹模式
│   │   └── platforms.py           #     平台后台导出 CSV（按文件名认平台，双 adapter 之一）
│   ├── pipeline/                  #   加工层：原始数据 → 向量 + 图 + 事实
│   │   ├── chunking.py            #     Markdown 按标题切段、超长二切、剥 frontmatter
│   │   ├── extraction.py          #     LLM 抽取：类/谓词/三元组契约三道滤 + 置信度分级
│   │   ├── extraction_prompt.py   #     抽取 prompt 独立成文件（改 prompt 不动逻辑）
│   │   ├── resolution.py          #     对齐消歧 L1（规则归一+alias）/ L2（嵌入相似）；L3 留作扩展
│   │   ├── etl_facts.py           #     平台 CSV → 映射翻译 → alias 换算 → 维度物化 → 事实表
│   │   ├── case_gen.py            #     文档→案例草稿 / agent 种子物化 / 人审确认入图
│   │   └── run.py                 #     双写编排：raw→PG→Neo4j、ingest_job 状态机、收尾对账
│   ├── store/                     #   存储层适配器
│   │   ├── raw.py                 #     原始层：不可变落盘 + sha256 旁写
│   │   ├── vector.py              #     pgvector：chunks+provenance 同事务，(doc_id,chunk_index) 幂等
│   │   ├── graph.py               #     Neo4j：MERGE 写入 + 六个读侧图查询（维度物化/负责人/违规…）
│   │   ├── provenance.py          #     ingest_job 状态机 + review_queue + 批次对账
│   │   ├── creator_quotes.py      #     达人报价快照写路径（同日同源只追加）
│   │   └── pg_pool.py             #     API 层共享连接池（min1/max8）
│   ├── retrieval/                 #   召回层
│   │   ├── router.py              #     规则路由优先，弱置信走 LLM；意图→计划映射单源
│   │   ├── graph_search.py        #     1/2/3 跳邻域；属性证据出口（deny_properties 唯一执行点）
│   │   ├── vector_search.py       #     pgvector cosine + 每类配额 + 权限子句下推 + 关键词兜底
│   │   ├── text2sql.py            #     双路：LLM 生成过五道闸；失败回落口径感知模板
│   │   ├── assemble.py            #     去重/缺席路/人名脱敏；permission_applied 汇总
│   │   ├── metrics.py             #     指标口径单一来源（词表/方向/汇总比/可算性白名单）
│   │   └── stats.py               #     汇总比统计脚手架（6 个汇总函数，5 个路由模块共享；超时统一）
│   ├── guards/                    #   管控层
│   │   ├── http.py                #     resolve_identity 认证收口（token > cookie > dev）
│   │   ├── auth.py                #     service token → role
│   │   ├── sessions.py / passwords.py   #   web 会话（7 天滑动）与 scrypt 口令
│   │   ├── permission.py          #     permissions.yaml → PermissionPlan 唯一翻译点
│   │   ├── action_check.py        #     操作前校验 schema#constraints（状态机/删除约束）
│   │   ├── rbac.py                #     界面权限门（display_role 判门 / role_allows）
│   │   └── audit.py               #     审计唯一 INSERT 收口（只追加）
│   └── api/                       #   服务层 FastAPI
│       ├── main.py
│       └── routes/                #     16 个路由模块 44 端点（ask/agent/graph/actions/guideline/
│                                  #     ingest/auth/menus/roles/admin/creators/cases/brands/
│                                  #     settlements/stats/creative）+ platform_browser（星图抓取）
│
├── sql/                           # 【资产】迁移 001–010（init_db 幂等执行）
│   ├── 001_init.sql               #   九张核心表：provenance/entity_alias/chunks/review_queue/
│   │                              #   audit_log/ingest_job/两平台事实表/product_orders_daily
│   ├── 002_unified_metrics.sql    #   两平台事实 → 统一口径视图（text2sql 唯一生成面）
│   ├── 003_auth.sql               #   app_user / app_session（web 会话）
│   ├── 004_quote_history.sql      #   creator_quote_history
│   ├── 005_menus.sql / 007_menu_tree.sql     # app_menu 页面/按钮树
│   ├── 006_rbac.sql               #   app_role / app_role_action（自定义角色）
│   ├── 008_admin_view.sql         #   management 回填 admin_view 读门
│   ├── 009_creator_seq.sql        #   达人编号 PG 序列（灭 MAX+1 并发撞号）
│   └── 010_case_stage_grant.sql   #   management/ae 回填 case_stage_change
│
├── eval/                          # 【资产】评估
│   ├── golden_set.jsonl           #   38 题（multi_hop 17 / fact 10 / concept 4 / attribution 4 / operation 3）
│   ├── run_eval.py                #   跑分：进程内打 /ask，规则判据 + LLM judge 双轨
│   ├── agent_scenarios.jsonl      #   agent 场景集（query/stat/comparison/casegen 四型，真实措辞打 /agent/chat）
│   ├── agent_eval.py              #   agent 跑分：ReAct 全链路判分（judge+数值锚+场景断言；--rounds 两轮防抖）
│   ├── run_ablation.py            #   消融：vec_only / vec_sql / full 三配置归因
│   ├── judge.py                   #   LLM judge prompt 与解析
│   ├── recalc_golden.py           #   库值锚点重算（dry-run diff / --yes 落盘，幂等）
│   ├── recalc_agent.py            #   agent 场景数值锚重算（协议同 recalc_golden，口径复用 metrics.agg_expr）
│   └── runs/                      #   评测结果（gitignore）
│
├── data/
│   ├── seed/                      #   合成种子 13 CSV（brands_products / org_people / cases_campaigns /
│   │                              #   case_persons / audiences / creators / case_creators / creator_products /
│   │                              #   quote_history / assertions / creative_metrics_daily_{douyin,xhs} /
│   │                              #   product_orders_daily）；文档由 gen_seed 直写 data/raw
│   ├── raw/                       #   原始层落盘（gitignore；68 篇 md = 60 案例 + 8 规范）
│   └── logs/                      #   launchd 同步日志
│
├── docs/                          #   introduction.md（项目详细介绍）· deployment.md（部署运维）·
│                                  #   specs/（拍板 spec）· reports/（夜间检查等运行报告）
│
├── scripts/
│   ├── gen_seed.py                #   生成确定性合成种子（固定随机流，同日重跑逐字节一致）
│   ├── init_db.py                 #   执行 sql/ + 双账号(adkg_rw/adkg_ro) + Neo4j 约束；幂等
│   ├── init_users.py              #   web 登录账号（与 permissions.yaml bindings 对账，漂移即退）
│   ├── load_seed.py               #   导入种子：主数据入图 + 文档路 + 事实路 + 交易路；幂等
│   ├── sync_feishu.py             #   飞书增量同步（双判幂等跳过 + supersedes 版本链）
│   ├── enrich_aligned.py          #   对齐抽取：历史 chunk → L1 对齐 → 只写两端都命中的关系
│   ├── gen_golden.py              #   从种子数据生成评测题（答案由查询回填）
│   └── com.adkg.feishu-sync.plist #   launchd 模板（每 10 分钟）
│
├── web/                           #   前端（React 19 + Vite 8 + Tailwind v4 + shadcn/ui，bun 管理）
│   └── src/
│       ├── routes/                #     路由表 + RequireAuth
│       ├── pages/                 #     login / dashboard / creators / cases / brands / settlements /
│       │                          #     admin（含 people / permissions / menus）
│       ├── features/              #     agent（悬浮窗 SSE）/ graph（echarts 力导向）/ shared
│       ├── components/            #     ui/（shadcn 13 件）· layout/（AppLayout）
│       └── lib/                   #     api.ts · session.tsx(useCan) · nav.tsx · labels.ts
│
├── mock-douyin/                   #   星图·模拟（:8100，纯 stdlib，agent 抓取目标站，零外连）
├── deploy/                        #   nginx/adkg-demo.conf · systemd/adkg-api.service · alerts/health_alert.sh
├── .github/workflows/ci.yml       #   PR 跑 pytest；push main 自动发布 A 机
└── tests/                         #   28 文件 255 用例；越权零泄漏、缺 provenance 拒绝等写成不变量测试
```

seed 里两个 `creative_metrics_daily_*.csv` 各含同一素材的记录（同 internal_id、两个平台的 external_id）——跨平台口径验收的锚点（见 [12.5](#125-实体-id-规则)）。

web 与后端只有一条通路：web → HTTP API 服务层（含认证），不直连 Neo4j / Postgres（十三的边界）；部署态全靠会话 cookie（~~nginx 按 `X-Adkg-Role` 注入 token~~ 已于 2026-10-24 撤销），本地演示 `ADKG_DEV_AUTH=off`。

## 五、技术栈与规模假设

| 组件 | 选型 | 理由 | 备选 |
|---|---|---|---|
| 语言 / 包管理 | Python 3.11+ / uv | 与 LangGraph 生态同源，smartServe 已用 uv | — |
| 服务框架 | FastAPI（锁定 0.146）+ Pydantic v2 | 结构化输出校验、OpenAPI 自动生成 | — |
| 认证 | service token（Bearer 直连路）+ web 会话 cookie（app_session，7 天滑动）| resolve_identity 三级解析 token > cookie > dev；单人维护相称，不起 OAuth/JWT | — |
| 向量 / 事实 / 溯源 | PostgreSQL 18 + pgvector 0.8 | 一个库同时承载向量、事实表、溯源表，单人维护成本最低；异步 I/O 提升读吞吐，uuidv7 直接做主键；Text2SQL 只对库内白名单视图生成 | Qdrant / Milvus |
| 嵌入 | BAAI/bge-small-zh-v1.5 · 本地（512 维、cosine、HNSW）| 中文小模型够检索用；load_seed / sync_feishu 当场生成无需回填；换模型重刷全部向量并重标 τ（7.4）；首跑设 `HF_ENDPOINT=https://hf-mirror.com`，已缓存后设 `HF_HUB_OFFLINE=1` | bge-m3 / 百炼 API |
| 重排（可选） | bge-reranker | 仅对 vector 路候选精排（概念 / 规范类），graph 链路不进重排 | — |
| 图 | Neo4j 2025.09 LTS Community | multi-hop Cypher 表达力强；自带浏览器可视化，演示友好；日历版本制下取 LTS 线 | Postgres 三元组表（本规模下可替代，见下） |
| LLM | 智谱 OpenAI 兼容双端点：交互路 **coding 端点 glm-5.3-flash**，批任务（抽取/judge/草稿）**glm-4-flash**（batch_chat_json，同 key）| coding 端点限流严故批任务分流——需配 `ADKG_LLM_BATCH_BASE_URL`，未配时回落主端点；全部调用限时单发、失败一律降级（7.2） | 其他 OpenAI 兼容服务 |
| 原始层 | 本地目录 | 单机够用；多人时换 MinIO，接口不变 | MinIO |
| 前端 | React 19 + Vite 8 + Tailwind v4 + shadcn/ui + echarts，**bun 管理**（pnpm 与 Node 22.23 不兼容）| 演示 + 自助看数 + 知识运营一体 | — |
| 评测 | pytest + promptfoo + 自研 run_eval / run_ablation / recalc_golden | 规则判据 + LLM judge 双轨；消融归因；库值锚点重算 | — |
| Agent 编排 | 不内置 | 编排在 smartServe engine-py；本项目只暴露 API | — |

**规模假设**（拍板值，非实测，按代投 App 引流、单人维护估计）：品牌 ~50、案例 ~200/年、素材 ~5k、事实行 ~百万级/年、chunk ~1 万、golden set 20 题起（现 38 题）。该量级下 Postgres 三元组表也扛得住——选 Neo4j 看重的是 Cypher 多跳表达力与可视化演示，不是规模刚需；量级再涨两个数量级时重估。演示数据用 `data/seed/` 合成种子，量级取上表零头。

**运行形态**（拍板）：**智能在线、资产在本地**——LLM 走 OpenAI 兼容 API（`llm.py` 一个适配层，key 进 `.env`）、嵌入本地；数据资产全在本地：seed 进 repo、双库在 docker、raw 在磁盘，零云成本。Postgres 两套账号：`adkg_rw` 应用读写、`adkg_ro` 只读（text2sql 执行 / 汇总比统计 / /graph 路由三处消费，五道闸第一闸），由 `scripts/init_db.py` 创建；`adkg_ro` 另被 REVOKE audit_log / app_user / app_session，`adkg_rw` 对 audit_log 收回 UPDATE/DELETE（只追加落账号级）。部署时该 PG18 实例**同时承载 smartServe 两库**（`agent_platform` / `agent_merchant`，独立账号 `agent_user`；同机走 docker 网络 `shared-infra` 直连，两机走内网 IP:5433）——省一份 PG 实例，库间靠账号与 database 边界隔离；拓扑与自动发布见 `docs/deployment.md`。

**数据三层**：① **合成 seed**——`scripts/gen_seed.py` 生成静态文件（2026-10-24 扩容：品牌 8+16、案例 20+40 覆盖全部 stage、达人 20+40、素材 ~80+160 含 1 对双平台同素材、事实行 ~0.9k+2.24k/表、SKU 3+6——**扩容全部追加且独立随机流**，旧数据逐字节不变，golden 实体域锚定零扰动；规范混入真实广告法条文）。CSV 提交进 repo（`data/seed/`）；**文档（案例 md + 规范 md）由 gen_seed 直写 `data/raw/`**——生成器模板即文档真源，产物不占 git，clone 后先 `gen_seed` 再 `load_seed`。事实日期为**滚动窗口**：gen_seed 取生成日近 12 个月、止于上月末（扩容批次整月铺满 1–28 日，近 30 天/上月窗口两侧都有数），对齐素材在最近月各保 ≥3 天（top-N 口径 `HAVING count>=3` 常青命中）——相对时间问句（上月/近 N 天）不因时间流逝空窗；日期只改分布不改数值，全量口径聚合稳定，同日重跑逐字节一致；② **手工"CRM 导出"**——`data/seed/org_people.csv` 由 `load_seed` 直读入图标 system_of_record（文件路通用入口是 connectors/files + run_docs 管线），演示 CRM 通道；③ **真实业务数据**——平台走后台导出文件路（官方 API 需真实代理商授权，留给部署方，connector 双 adapter 成真 seam），飞书自建应用按 revision 增量——两种来源：`FEISHU_DOCS` 显式 token 列表，或 `FEISHU_FOLDER` **共享文件夹模式**（应用加为文件夹协作者一次，全公司可往里放文档，同步自动列目录逐篇摄取、类型过滤只吃 docx，零逐篇授权）。

## 六、本体概览

核心类控制在 13 个，从"案例创建"主线反推（2026-10-24 spec §3 增 `Creator`），详细定义见 `ontology/schema.yaml`：

| 类 | 说明 | 关键属性 | 主要来源 |
|---|---|---|---|
| Brand / Product | 广告主、商品（App / SKU 双形态），主数据，关系的载体 | 名称、品类、目标人群年龄（target_age，如「22-40」）；App 形态：app_id、平台；SKU 形态：spec（规格）、detail（详情摘要）、price（客单价）——投放统计经 `Case→for_product` 上卷到商品粒度（事实表物化 `product_id`） | CRM、案例文档、商品后台导出 |
| **Case** | 主线实体，`stage ∈ {proposal, live, closed, lost, terminated}` | stage、bd_budget、gross_margin、settlement_status | 案例系统、proposal 文档 |
| Campaign / Creative | 投放计划、素材 | 计划名（name）、status、daily_budget；素材名（name）、is_aigc、derived_from | 平台 API、导出表 |
| Channel / LandingPage / Audience | 投放上下文：广告位 / 流量场景、落地页、定向人群 | 广告位类型；url；定向包描述 | 平台、配置 |
| **Metric** | 指标**口径定义**（非数值）：CTR / CVR / CPA / ROI 的统一公式 | expr、grain、dedup_rule、valid_scope | 语义层手工定义 |
| Guideline | 创意规范、品牌 VI、广告法条款；可机判规范带结构化阈值属性 | 类型、max_duration 等阈值 | 文档 |
| Person | AE / 优化师 / 客户对接人，权限与责任归属（不存联系方式） | 姓名、组织角色 | 组织系统 |
| **Creator** | 达人 / 创作者主数据（spec 2026-10-24）：**平台级主数据——类白名单即可见、不设 row_filter**，合作历史经 Case 行过滤收敛 | 名称、平台、视频方向（niches）、粉丝数、20s/图文报价、30 天 GMV、城市、评分 | 数据平台抓取（connectors/platforms + mock-douyin 模拟）、CRM |
| DocVersion | 文档版本链，`supersedes` | rev | 云文档同步 |

关键关系（17 种）：`Case→for_brand→Brand`、`Case→for_product→Product`（N:1）、`Brand→has_product→Product`、`Case→collabs_with→Creator`（N:M，spec §3）、`Creator→promotes→Product`（N:M 带货）、`Campaign→belongs_to→Case`、`Campaign→uses→Creative`、`Campaign→in_channel→Channel`（N:1，与事实表的平台维度区分，不重复建模）、`Campaign→targets→Audience`（N:M）、`Creative→links_to→LandingPage`（N:1）、`Creative→complies_with / violates→Guideline`、`Creative→derived_from→Creative`、`Person→responsible_for→Case`、`Person→belongs_to_brand→Brand`（内部对接人归属）、`Person→external_for→Brand`（外部客户账号绑定，N:M，变更走人审）、`DocVersion→supersedes→DocVersion`（版本链）。`平台字段→maps_to→Metric` 是 mappings 层的映射谓词，不是图关系。

Metric 是 `unified_metrics` 视图列的语义锚点，也是 router 识别指标词与 Text2SQL 可用指标白名单的依据；视图实现与 Metric 公式的一致性由 `mappings/` 保证；两平台不可比的指标在映射层不映射、视图列留空。`expr / grain / dedup_rule / valid_scope` 落在 schema.yaml。**聚合口径铁律**：比率型指标（ctr / cvr / cpa / cpm）跨行聚合一律**汇总比** `sum(分子) / NULLIF(sum(分母), 0)`（如 cpa = sum(cost) / sum(conversions)），**禁止对行比率再求 avg**——小分母行会带偏总量结论；该铁律同时约束 Text2SQL 模板与 LLM 自由生成（粒度上卷到 campaign / case / brand 同样适用）。**口径单一来源（2026-10-23 收敛）**：指标词汇与聚合口径收口 `adkg/retrieval/metrics.py`——维度列/指标词表/平台词/方向语义/汇总比聚合表达式/可算性白名单，Text2SQL 模板、图侧统计卡（§9.7）、权限指标列宇宙（§12.4）共用一处；graph ↔ text2sql 双写曾是多起口径实弹的温床（cvr 裸 sum、orders 放大、词表漂移）。**收口补完（2026-10-24）**：最X/方向词族（`RANK_WORDS` 等——router 意图词与 text2sql 方向判定同源，曾三份拷贝）、案例统计全家桶 `STAT_FAMILY`（(cost, ctr, cvr, cpa) 曾两处硬编码）、交易 join 形状（`TRADE_SELECT` + `uc_clicks_sql`——orders/gmv 与投放 clicks 的 product×day 预聚合对齐，graph 统计卡与 text2sql 交易模板同款）并入 metrics.py；全局类豁免改 schema 驱动（`models.global_classes` → PermissionPlan 字段，`{Metric, Guideline, Channel}` 字面量消灭）。**交易口径分列**：购买率（purchase_rate = orders / clicks）是**交易侧**指标（grain=product×day，数据源=商品后台导出，§五 数据三层③ seam；演示期合成种子），与投放侧转化率（cvr = conversions / clicks，平台回传的转化目标）**分列定义、不得混用**。

关键约束（`guards/action_check.py` 读取）：Case 状态迁移 `proposal→live｜lost`、`live→closed｜terminated`，closed / lost / terminated 为终态不可逆；lost 默认排除出可比案例检索（retrieval 按 stage 过滤）但保留复盘归因；terminated 必填终止原因；live / closed 的 Case 不可删除 Creative；任何写入必须带 provenance。完整迁移表进 `schema.yaml#constraints`。

## 七、数据流程

### 7.1 建设路线（八步，与路线图合一）

| Phase | 做什么 | 产物 | 预估 | 状态 |
|---|---|---|---|---|
| 0 | 列 20 个真实问题并标注命中类型；golden set 骨架；本 README | `eval/golden_set.jsonl`、README | 2d | **完成**（20 题五类 5/4/4/4/3） |
| 1 | 定本体、关系、约束；permissions、authority；`sql/`（含 audit_log、ingest_job）；docker-compose；models.py；run_eval 骨架；纸面评审 | `ontology/`、`sql/`、空库 | 4d | **完成** |
| 2a | 文档路·本地：files connector、chunking、extraction、resolution 前两级、向量 + 图入库 | 图里第一张关系网 | 6d | **完成**（抽取回归实测：glm-4-flash 批端点 6 篇 → 71 实体/57 关系，置信度分级与白名单滤噪生效；标注集 precision/recall 量化待真实数据扩集时做） |
| 2b | 文档路·飞书：feishu 按 revision 增量、LLM 判别级对齐 | 云文档自动入库 | 4d | **完成**（connector + 版本链 + 定时增量（launchd / 同步即嵌入）就绪，10 篇文档双端同步闭环；L3 LLM 判别级对齐未做——对齐靠 L1/L2 + 人审兜底，resolution.py 注明留作扩展） |
| 3 | 数据路：platforms connector、近 12 个月历史回填（后台导出文件路）、etl_facts、`unified_metrics` | 同一素材两平台可比 | 4d | **完成**（演示级：锚点素材两平台同口径可比；platforms API adapter 留给真实部署方） |
| 4 | 召回与权限：认证、permission 过滤与下推、router、三路检索、融合排序、assemble、`/ask` | `/ask` 能答混合问题 | 6d | **完成**（规则路由 + 三路 + PermissionPlan 下推；LLM 路由弱置信兜底已接） |
| 5 | 管控收口：`/actions/check`、audit、AIGC 闭环 | 越权被过滤、违规被拦截 | 5d | **完成**（裁决/机判/断言写回实测：live 删素材被拦、超时长违规、低置信进人审） |
| 6 | 评估：golden set 扩题、三基线跑分、对比报告、docs | 一张收益对比表 | 3d | **完成**（38 题终评（2026-10-24）：规则判据口径 multi_hop 17/17 全过；LLM judge 要点命中 32–34/35（跨 run 抖动）、整体 95%±抖动；消融归因见表下；库值锚点重算脚本化 `recalc_golden.py`（2026-10-27）；50 题全量留待真实数据接入后扩） |

Phase 2 起每阶段收尾跑 run_eval 记入 `eval/runs/`——"评估先行"落地为每阶段有分数。合计约 34 人日（单人粗估，不装精确）。

### 7.2 运行流程

数据侧三条常驻通道：

- 云文档**定时增量**：`scripts/sync_feishu.py` 可手动跑，也可 launchd 挂 `StartInterval`（plist 模板在 `scripts/`，默认 10 分钟，装在本机 macOS、服务器侧不配）。每轮按 `(source_id, version)` 幂等跳过：`ingest_job` 两段都已 done **且** chunks 仍有该文档块才跳过（不重分块、不重写 provenance；TRUNCATE 后 ingest_job 残留 done 时自动重灌自愈），只有新 revision 才进流水线；chunk 面**恒为最新版**（`(doc_id, chunk_index)` 冲突更新），历史版本在 raw（`@rev` 键）+ DocVersion `supersedes` 链里，不删除；嵌入随同步用本地模型当场生成，不依赖事后回填
- 平台数据每日 T+1 ETL；上线首日先经后台导出文件路一次性回填近 12 个月（**平台报表接口回溯窗口有限，窗口外没有第二来源**，这一路不适用"数据留原地"），之后只做增量
- Agent 对话中暴露的"文档没写 / 写错了"回流成 `review_queue` 条目，人审后入库

使用侧一条链路：

```text
提问 → 认证（token→role）→ router（识别实体、意图、可见范围）→ 三路召回（每路召回前先过权限过滤）
     → assemble（只见过滤后结果）→ 带 provenance 的回答
操作类请求 → /actions/check → permission → action_check → 放行（附约束依据与 audit_id）/ 拒绝 → 审计
```

**降级矩阵**（原则进 README，超时 / 重试参数留代码）：

| 故障 | 处置 |
|---|---|
| router 置信度低 | 三路全跑，assemble 去重兜底 |
| router / LLM 超时 | 规则路由（意图关键词模板）兜底 |
| LLM 慢 / 限流（交互路） | 请求路 LLM 调用（探测 / 路由 / text2sql 生成 / agent 总结）**单次不重试、各自限时**，总结超时回模板、超预算（已耗时 ≥60s）不再发起；端到端压在网关 150s 内（2026-10-22 实测：coding 端点同调用 10~90s 方差，30s×3 重试叠加曾致 504，访客 14s 即弃连）。限时档：探测 12s / 路由 15s / text2sql 生成 30s / **总结 60s**（2026-10-23 调整：35s 档在该端点分布下约五成超时）；`/agent/chat` ReAct 每轮 generate 限时 60s、整循环墙钟 120s（超限带已有 trace 收敛）；`/ingest` 抽取调用显式单发限时 |
| 单路超时 / 异常 | 降级拼装，答案标注缺席路（响应 `degraded` 字段） |
| text2sql 失败 | 生成单次不重试；执行失败回落口径感知模板（`sql_source=template(fallback)`），模板仍败才空证据并明示"事实数据缺席"——不编数 |
| T+1 ETL 失败 | 原始层已存 API 原始响应，次日自动补跑，缺口行留状态标记 |
| 抽取失败 | 登记 ingest_job 待重放（原始层保底） |
| Neo4j 不可用 | graph 步跳过并标注缺席路、其余路照常（2026-10-27 兑现：三路执行统一 try/except，单路异常不再穿透为整问 500）；Postgres 不可用则服务不可用（事实与向量同库，接受该单点） |
| 端点未捕获异常 | 全局 handler 统一返回 **JSON 500**（`detail` 带异常类名）——Starlette 默认纯文本 body 会让消费方 `.json()` 抛 SyntaxError 掩盖真错（2026-10-21 实测教训） |

### 7.3 路由决策

| 意图类型 | 示例 | 主路线 | 辅助 |
|---|---|---|---|
| 事实聚合 | 上月 CPA 最差的素材 | text2sql | — |
| 关系链 | 对接人名下的 live 案例 | graph | vector 补充描述 |
| 概念 / 规范 | 创意规范对视频时长的要求 | vector | graph 定位规范节点 |
| 归因混合 | 效果差的素材与规范有没有关系 | graph → text2sql → vector **串行**：graph 圈实体 → 实体 ID 作 text2sql 条件 → vector 取规范原文 | — |
| 操作类 | 删除某素材 | `/actions/check` 校验 → 放行 / 拒绝 | — |

操作类不进 `/ask`：由调用方直接调 `/actions/check`，`/ask` 识别为操作意图时返回端点指引而非答案。

路由护栏约定（规则版，LLM 路由只在弱置信时兜底）：① **锚词让贤**——图锚词（名下/负责/对接）与指标词同现时（"李昂名下消耗最高的素材"），fact 置信降至 0.75 交 LLM 裁决，杜绝锚点被事实路静默丢弃；② **定义尾短路**——问句带释义尾（什么意思/怎么算/定义是什么）时归 concept，即使句中含操作词或指标词；③ **状态限定词如实标注**——"被暂停/已下线"类状态限定进不了 SQL 过滤器，事实证据挂 note 说明"状态限定未参与过滤"；④ 释义/规范词与聚合词冲突时以硬聚合信号（消耗/CPA/排名/最差等）为准查数，定语型指标词（跑量素材/爆量视频）不作硬信号。`/agent/chat` 响应下发 `can_commit_case`（服务端按案例生成角色 + `create_case` 动作同源判定），前端不本地硬抄角色表。

**融合与排序**：路内排序（向量按相似度、图按 confidence × 跳数惩罚、事实按指标）→ 跨路去重合并（v1 用保序去重替代 RRF）→ 同一事实按 authority 仲裁（[12.2](#122-权威度authorityyaml)）。router 输出各意图置信度，最高低于阈值 → 三路全跑兜底；响应 `routes_used` 各项带得分，评测可归因到路。路由计划 **RouterPlan**（steps 带依赖与置信度、fallback 标志）是 models.py 一等类型，`ask.py` 只解释执行——路由评测直接对 plan 断言，不起整条 LLM 链路。

**权限下推**：`guards/permission.py` 把 permissions.yaml 翻译成 **PermissionPlan**（metadata_filter / 可见 ID 集 / SQL 谓词 + 列白名单 + **属性黑名单** / 脱敏规则），vector、graph、text2sql 三路与 assemble 出口**只消费 plan、不读权限矩阵**——过滤在召回层内生效，assemble 只见过滤后结果，对外仅布尔 `permission_applied`（计数与明细进审计）。graph 路命中实体的**自身属性作为 `entity` 证据项**随关系一起返回（`Product.target_age` 这类属性型问题由此可答），属性白名单（外部 `allow_properties`，fail-closed）与黑名单（内部 `deny_properties`）都在该出口执行——这是它们唯一的执行点。SQL 谓词**案例级优先、品牌级兜底**（optimizer 的"负责案例"粒度 ≠ 对接品牌，品牌级会错杀）；text2sql 的生成 SQL 经五道闸校验后还由系统**注入语义不变量**（NOT unmatched、行谓词）——不信任生成的 SQL。越权值不得参与聚合：top-N / 均值一律算在过滤后集合上。翻译收口在一处，越权测试集只打 PermissionPlan 这一个 interface。**执行侧同样收口在 plan**（2026-10-28）：`gate / gate_detail / require_visible / filter_visible / project` 五方法 + `mask_person` 掩码——CRUD 端点不再手推「我被拒了吗 / 类可见吗 / 哪些字段能出门」（此前 ~8 处手抄已漂：403/404 不一致、client 的 Case.lost_reason 详情路丢失，统一后一并修正）。

### 7.4 实体对齐（四级漏斗）

工程上最耗时的一环，预算见 7.1 Phase 2，各级有判定标准：

| 级 | 做法 | 判定 |
|---|---|---|
| 1 规则归一 | ID 直接映射；名称清洗（去平台前后缀、全半角、casefold） | entity_alias 命中即接受 |
| 2 相似候选 | embedding top-k（top 5） | 相似度 ≥τ 进下一级（τ 随嵌入模型在 seed 上标定，初值 0.75） |
| 3 LLM 判别 | 候选对交给 LLM | ≥0.8 接受；0.5–0.8 人审；<0.5 拒绝（**未实现，留作扩展**） |
| 4 人审 | review_queue | 产物：entity_alias 行 |

产物：entity_alias 表 + 人审条目。验收：seed 内已知同素材对 100% 命中；抽样对齐正确率 ≥95%（进 11.3）。事实路同走此漏斗，以规则级 ID 归一为主（entity_alias 直接换算），embedding / LLM 只兜名称对齐；对不上的行标 unmatched 进 review_queue、不进跨平台对比。**铁律：抽取产物必须先过对齐（L1）才能入图**——未对齐直接入图会污染检索（`scripts/enrich_aligned.py` 是历史 chunk 的对齐落地，`case_gen` 在草稿路执行同样纪律）。

## 八、五层存储

| 层 | 存什么 | 落点 | 特性 |
|---|---|---|---|
| 原始层 | 原始文件、API 原始响应 | `data/raw/` | 不可变（同 key 不同内容抛错）、带 hash、可重跑 |
| 向量层 | chunk 文本、embedding、metadata | Postgres `chunks` | 回答"写了什么"；chunk 带 class / brand_id / case_id，检索按角色过滤；未分类 chunk 视为公共内容可检索 |
| 图层 | 节点（单 Entity 标签 + class 属性 + provenance 内联）、关系（带 confidence） | Neo4j | 回答"谁和谁有关系"；entity_id 唯一约束 + class 索引 |
| 事实层 | `creative_metrics_daily_*`（platform × campaign × creative × day，一行一素材一平台一天）+ `unified_metrics` 视图 | Postgres | 回答"多少、趋势"；表内物化 campaign_id / case_id / brand_id / product_id 冗余列（etl_facts 从图侧关系回填）——campaign / case / brand 级聚合与 row_filter 谓词的落点，不另建事实表；Text2SQL 只对视图生成 |
| 溯源层 | `provenance`、`entity_alias`、`review_queue`、`audit_log`、`ingest_job`（另 auth/RBAC/菜单/报价 6 表——全库 15 表 + 1 视图） | Postgres | 审计（只追加、保留 ≥1 年、仅 admin 可读）、仲裁、对齐 |

**双写一致性**：一次抽取写 Postgres（chunks / facts / provenance）与 Neo4j 两库。顺序 Postgres 先、Neo4j 后；幂等键 = provenance 的 `source_id + version`（version 缺省取 fetched_at 日期），图层一律 MERGE；`ingest_job` 记录每条原始记录两库落库状态，run.py 按 job 重放补偿，失败不跨库留影；每批次收尾对账——图层带 provenance 的节点 / 关系数 vs provenance 表计数，差异写 review_queue（批量溯源下不追求相等，差异供人审）。

**备份与重建**：`data/raw/` 是全系统唯一不可再生源，每日增量同步到第二位置（外置盘 / 对象存储，RPO 24h），落盘 hash 兼作完整性校验（多人换 MinIO 时改跨桶复制，约定不变）；Postgres 每日 pg_dump 一次，覆盖向量 / 事实 / 溯源 / 审计；图层可从 raw + ontology 全量重建（重建即全量重跑），Neo4j 低频 dump 排 ETL 前维护窗口。raw 丢失 = 业务历史丢失，任何迁移先迁 raw。

## 九、如何使用

### 9.1 身份与鉴权

- **认证**：静态 service token（每 role 一枚，`ADKG_TOKEN_<ROLE>` 环境变量），网关 / 引擎注入 `Authorization` 头；AdKG 校验 token → role，**不信任请求体自报的身份**。未带凭证 401；有凭证但无 Person 绑定，按最小权限只读全局类（Metric、Guideline、Channel，见 12.4）。token 本体进 `.env` / 密管，仓库里只有 bindings 映射结构（[12.4](#124-权限矩阵permissionsyaml)）
- **Web 会话登录**（2026-10-24，spec §2）：web 前端走 `/auth/login`——账号在库（`app_user`，stdlib scrypt + 等时哑校验），`app_session` 表支撑 HttpOnly cookie（7 天滑动、可吊销、登录成败均审计）；`guards/http.py::resolve_identity` 优先级 **token > cookie > dev**，Bearer 直连路（smartServe / eval）不受影响
- **user ↔ Person**：绑定落 permissions.yaml `bindings` 段（token 路由 person；零绑/多绑时回退 body/query 自报），作 row_filter 起点
- **外部客户**：独立签发的只读 token（与内部隔离），凭证只标识主体、不含 brand_id；租户绑定走 `Person→external_for→Brand`（N:M，一家客户多品牌即多条），变更走 review_queue 人审并记审计；token 设有效期，吊销 = 从 bindings 移除映射并记审计
- **Agent 受托**（设计目标）：凭证携带 agent_id 与终端用户身份，生效权限取两 role **交集**（最小权限）、行过滤取更严者——**求交当前未实现**：现状单 role 调用，仅审计记双身份（audit_log.agent_id）
- **本地开发**：`ADKG_DEV_AUTH=off` 时允许 body 传 role（仅限本地）
- **收口（2026-10-23）**：token→role + 绑定 person / dev 兜底的认证解析统一走 `guards/http.py::resolve_identity`（各端点不再自抄认证块——散抄曾致漏门）；审计写入统一走 `guards/audit.py::audit`（四端点各抄一份 INSERT 是漏账温床，verdict 枚举由库约束兜底）；Agent 工具面注册表化（`_TOOLS` 名→描述+handler 同时驱动 system prompt、未知工具提示与分发——加工具只改一处）
- **收口补完（2026-10-24）**：①`role ∈ planner.roles` 预检并入 `resolve_identity`（各端点的"未知角色 401"不再自抄，actions/guideline 两个漏网端点同补）；②planner / graph 惰性单例挂 `app.state`（`guards/http.py::get_planner / get_graph`——http 层曾反向 import `routes.ask._planner`，且 planner 与 actions 各建一份 GraphStore）；③`audit()` 增 `agent_id`（/actions/check 双身份）与外部 `conn`（/ingest/case-commit 与别名注册同事务落账）参数并返回 `audit_id`——最后两处手写 INSERT 消灭

### 9.2 六类角色的日常用法

| 角色 | 日常怎么用 | 典型问法 | 得到什么 |
|---|---|---|---|
| AE / 销售 | 提案前检索可比案例；续约预警 | "有没有和 A 品牌同品类的 App 下载案例，效果前三的？" | 案例清单 + 效果数字 + 来源，仅限自己权限内的案例；不可见成本毛利 |
| 优化师 | 每日投放巡检；素材淘汰决策 | "我负责的计划里 CPA 连续 3 天上升的有哪些？" | 事实表直查结果，仅限 responsible_for 的 Case 下的 Campaign（沿 belongs_to 级联） |
| 创意 / AIGC | 生成前查规范；找爆款参考 | "这个品牌信息流视频的时长和结尾规范是什么？" | 规范原文引用；生成后断言写回 `violates`，可查可溯源 |
| 客户方（外部） | 自助看数 | "我品牌本月抖音的消耗和转化" | 仅 external_for 锚定的 Brand 子图，其他品牌零可见；跨品牌命中即拒绝并告警 |
| 财务 / 商务 | 项目毛利、回款状态 | "C-2026-008 的结算进度" | 结算相关字段（属性级：毛利与结算状态，v1 不含期次明细） |
| 管理层 | 大盘与客户健康度 | "各客户健康度排名，哪些有流失风险" | 跨品牌聚合视图 |

同一个问题不同角色得到不同的行和字段，这不是功能，是本体权限的副作用。

### 9.3 三个使用入口

1. **直接调 API**：业务系统或前端集成 `/ask`、`/graph`、`/actions/check`、`/guideline/check`。
2. **Agent 引擎接入**：smartServe engine-py 把 `/ask`、`/graph`、`/actions/check`、`/guideline/check` 注册为工具；Agent 以自身 role + 受托用户身份调用，权限矩阵对它和对人一样生效。
3. **知识运营入口**：`/ingest` 录入 + `review_queue` 人审，知识运营同学在这里处理冲突、补录缺口。

### 9.4 API 示例

问答（归因混合类，三路都用上）：

```http
POST /ask
Authorization: Bearer <service-token>
{"question": "A 品牌去年抖音哪些素材效果差？和创意规范有没有关系？"}
```

```json
{
  "answer": "去年 A 品牌抖音投放中 creative_992、creative_1007 两条素材 CPA 高于均值 60% 以上。其中 creative_992 违反创意规范 G-03（前 3 秒无品牌露出）……",
  "evidence": [
    {"type": "fact", "ref": "unified_metrics / 2025-12 / creative_992", "fields": {"cpa": 86.0, "ctr": 0.009},
     "provenance": {"source_type": "platform_api", "source_id": "douyin:report:20260101", "fetched_at": "2026-01-02T03:00:00+08:00", "authority": 80}},
    {"type": "relation", "ref": "(creative_992)-[:violates]->(guideline:G-03)",
     "provenance": {"source_type": "conversation", "source_id": "aigc_check:7731", "fetched_at": "2025-12-20T10:12:00+08:00", "authority": 20, "confidence": 0.91}},
    {"type": "doc", "ref": "chunk:guideline_general#G-03", "quote": "信息流视频前 3 秒须出现品牌标识……",
     "provenance": {"source_type": "official_doc", "source_id": "feishu:doc:xxx@rev12", "fetched_at": "2025-11-30T09:00:00+08:00", "authority": 60}}
  ],
  "routes_used": [{"route": "graph", "score": 0.93}, {"route": "text2sql", "score": 0.87}, {"route": "vector", "score": 0.81}],
  "permission_applied": true,
  "degraded": []
}
```

`answer` 为 **markdown 文本**：agent 总结结论先行、每条事实带 `[#N]` 引用；清单/排名/多条对比用表格输出，前端按 markdown 渲染（LLM 不可用时降级为纯文本模板摘要，`answer_source` 标注 agent/template）。

操作类请求走独立的裁决端点（AdKG 只裁决，不代执行）：

```http
POST /actions/check
Authorization: Bearer <service-token>
{"op": "delete_creative", "target": "Creative:creative_992", "agent_id": "agent:aigc-01"}
```

```json
{"decision": "deny",
 "reason": "constraint violated: live/closed 状态的 Case 不可删除 Creative（schema.yaml#constraints）",
 "audit_id": "01JGZ8K7Q4M3NP2T5V9WXBCDRE"}
```

放行时返回 `{"decision": "allow", "reason": "…", "audit_id": "…"}`；调用方自行执行后 `POST /actions/receipt {audit_id, outcome ∈ done/failed/skipped, note}` 回写结果——审计只追加，回执写新行（`action=action_receipt`、`target=audit:<原id>`、`verdict=outcome`，011 迁移扩枚举）引用原裁决行，裁决与回执两段闭环（2026-10-28 落地）。动作词表 `read / create_creative / pause_campaign / delete_creative …` 见 `schema.yaml#actions`。

AIGC 闭环两个端点：`POST /guideline/check` 生成前返回适用规范 + 机判阈值结果（时长 / 尺寸等结构化项，不做语义比对）；`POST /ingest/assertion` 生成后写回断言（`{"subject": "Creative:creative_1007", "predicate": "violates", "object": "Guideline:G-03", "confidence": 0.91}`，provenance 为 conversation / 20）。语义 / 多模态比对归 smartServe 的 AIGC Agent 或人工，AdKG 收口规范检索与断言写回，过权限与审计。

文档→案例三端点（Agent 对话的确认入图链路，亦供 HTTP 消费方直用；定时同步只入 chunks 不建实体，这组端点补"文档 → 图谱实体"最后一跳）：

- `GET /ingest/docs?q=`：列已同步飞书文档（chunks 聚合 + ingest_job 版本；标题取 chunk#0 首行）
- `POST /ingest/case-draft` `{"doc_id": "feishu:doc:xxx"}`：LLM 抽 Brand / Product / Case 草稿 + [7.4](#74-实体对齐) L1 对齐——命中既有实体复用其 id（`existing: true`），未命中的 Person 一律丢弃（未对齐不入图，[12](#十二约定) 铁律）；**不写任何库**
- `POST /ingest/case-commit` `{"draft": {…}}`：人工确认后入图。服务端重校验（**身份重推导**——existing / same_doc / eid 不采信客户端，从图上按 L1 对齐 + case_id_for 重推；谓词 / 三元组契约 / 属性白名单），新实体 provenance 为 **official_doc / 60**（低于 system_of_record，冲突仲裁保护主数据）、`source_id=doc_id` 可溯源；注册 `entity_alias(name)`；写 audit。同文档重复 commit 幂等（身份重推导全对齐命中 → 节点零重写；边 MERGE）

素材草稿两端点（表单式生成，Agent 对话内同样能力经工具提供）：商品知识（vector 路）× 最好相关案例素材（text2sql top 口径 + 图上下文过滤同类目）× 创意规范（机判阈值）→ LLM 生成素材草稿（前 3 秒钩子 / 分镜脚本 / 投放文案，带证据编号与 provenance）。证据三路全过 PermissionPlan 过滤（§12.4）；草稿为灵感件，投放前须过 `/guideline/check` 机判与人工审。

对话式 agent：`POST /agent/chat` `{"messages": [...]}`——web「Agent 助手」唯一对话入口，**问答与生成合一**。ReAct 循环（纯 JSON 契约）自选只读工具（ask_knowledge / list_brands / search_product_knowledge / search_best_creatives / get_guidelines / list_synced_docs，全部过 PermissionPlan；问答经 ask_knowledge 走 `/ask` 三路管线），产出 `case_draft`（前端确认后仍走 `/ingest/case-commit` 服务端重校验入图——铁律不因 agent 而绕过）或 `creative_drafts`；工具调用轨迹随响应返回可溯源。

### 9.5 知识怎么进去

| 通道 | 入口 | 机制 |
|---|---|---|
| 手动整理的文件 | `connectors/files`（run_docs 管线，load_seed / 手动触发） | 解析 → 分块 → 向量 + 抽取入图 |
| 云文档 | `connectors/feishu` 定时 | 按 revision 增量，新版本 `supersedes` 旧版 |
| 平台效果数据 | `connectors/platforms` 每日 | T+1 ETL 进事实表，经 `mappings/` 统一口径 |
| 达人主数据（星图·模拟） | agent 工具 `fetch_creator_from_platform`（spec §6） | Playwright 无头浏览器真实点击抓取，逐步截图进轨迹；platform_api / 80 幂等 MERGE 入图——连接器主数据同步，非 agent 断言 |
| 达人主数据（手工/表格） | web 达人库「录入」表单与「导入 CSV」（spec §13.1） | conversation/20 与 official_doc/60 低权威入库，平台抓取可覆盖；同一权威仲裁（高权威在场不覆盖，冲突去重进 review_queue） |
| CRM / 组织系统主数据 | 定期导出文件落 data/ 由 `load_seed` 入图（演示期即 `data/seed/org_people.csv`） | 解析入图标 system_of_record——authority 顶层级有真实数据来源 |
| 数仓 / 业务库 | `connectors/warehouse`（**规划，未实现**） | 只读 schema 建映射（供 router 理解字段语义），不搬数不直查；指标查询统一走事实层视图（FDW 直查留作扩展） |
| Agent 断言（AIGC 比对结果等） | `/ingest/assertion` | 带低 authority provenance 入图，冲突按 [12.2](#122-权威度authorityyaml) 进 review_queue |
| 飞书文档里的新品牌 / 商品 / 案例 | web Agent 对话（`/ingest/case-draft` → `case-commit`） | 定时同步只入 chunks；草稿经人确认后建实体入图（official_doc / 60），Person 未对齐不入图 |
| 对话中暴露的缺口 | Agent 自动写 `review_queue` | 人审通过后入库 |

每条记录落地都带 provenance 四元组（见 [12.1](#121-provenance-四元组任何入库必带)），缺失即拒绝入库。

### 9.6 开发者扩展

| 要做的事 | 改哪里 | 不用动哪里 |
|---|---|---|
| 接一个新平台（如快手） | 新增 `connectors/kuaishou.py` + `mappings/kuaishou.yaml` + `sql/` 新平台事实表（002 视图增并） | `adkg/` 代码三层（pipeline、store、retrieval）零改动 |
| 加一个实体类或关系 | `ontology/schema.yaml` | 抽取 prompt 和校验自动读 schema；新增属性默认不可见（12.4 fail-closed）；Neo4j 无 schema 迁移成本 |
| 接一个新 Agent | `permissions.yaml` 加一个 role + bindings 一条 | 该 Agent 的可见范围和可执行操作即被定义，管控自动收口 |
| 换一个行业 | **重写**：`ontology/` 四件（schema / mappings / authority / permissions）+ `sql/` 事实表与 002 视图 + `scripts/gen_seed.py`（种子 CSV 与 raw 文档单源） + golden_set 题目 | **复用**：`adkg/` 代码、run_eval 评估协议、connector 接入模式（新数据源按第一行增删） |

换行业的重写边界只在此处声明，全文其他提到处均指回本表。

### 9.7 前端与运营台（web/）

> **2026-10-24 起升级为真实系统**（spec：`docs/specs/2026-10-24-真实系统化升级-spec.md`）：服务端登录 + 侧边栏多页面（达人库/客户/财务结算/数据看板/管理后台按里程碑交付）+ Agent 全局悬浮窗。定位从「演示件」改为「自助看数、演示、知识运营」的真系统；内部用户的日常对话主力仍是 smartServe（见十三），web 的 agent 悬浮窗作自包含入口。部署边界（nginx 唯一公网面）见 `docs/deployment.md` §四。

| 页面 | 谁用 | 端点 |
|---|---|---|
| 数据看板 `/` | management/ae/optimizer/finance（client 只看自己品牌） | `/stats/overview`（M5） |
| 达人库 `/creators` | management/ae/optimizer（finance 结算视角） | `/creators`（M2，Creator 本体扩展）；**数据闭环（M8，spec §13.1）**：录入 `POST /creators`（conversation/20）与 CSV 导入 `POST /creators/import`（official_doc/60），与平台抓取（80）、种子（100）构成四来源梯度——列表「来源」列 + 详情来源卡；高权威在场不覆盖、冲突去重进 review_queue |
| 案例 `/cases` | management/ae/optimizer/client（client 只看自己品牌） | `/cases` + `/cases/{id}`（M9，spec §13.2 全生命周期）：列表批量指标（汇总比）+ 详情六段（概要/内容 chunks/指标/状态流转条含拒因/收益与素材明细/合作达人）；行过滤后分页（锚点角色首页不被不可见案例占满）；阶段迁移控件由详情下发的 `stage_flow.transitions` 驱动（schema#constraints 派生，前端不手抄状态机） |
| 客户 `/brands` | management/ae；client 只看自己 | `/brands`（M3） |
| 财务结算 `/settlements` | management/finance | `/settlements`（M4） |
| Agent 助手（全局悬浮窗，SSE 流式） | 所有人（证据与草稿随角色过滤） | `/agent/chat/stream`（事件契约：thought / tool_start / tool_step 浏览子步含截图 / tool_result / reply / draft / done / error；ReAct 循环生成器化，`/agent/chat` 聚合同流保旧契约；工具面新增 `fetch_creator_from_platform`——Playwright 无头真实点击星图·模拟、逐步截图、幂等入图，spec §6） |
| 图谱展开 `/graph` | management/ae/optimizer/creative | `/graph/entity`（Case/Product/Creative 类实体响应附 `stats`：指标汇总比——cost/ctr/cvr/cpa/天数 + 覆盖平台；Product 另附交易段 orders/gmv/购买率（§六 交易口径分列）；行权限过滤，client 视角越权对象不出数；Creative 投放未对齐时不出卡——§7.4 对齐漏斗的诚实边界） |
| 规范检查 | 创意 / AIGC | `/guideline/check` |
| 管理后台 `/admin` | management/admin（读门 `admin_view`） | 审计流水（action/verdict/role/关键词筛选）+ 人审队列（只读 + approve/reject 处置，门 review_resolve）+ 账号一览（写操作在人员管理页）；矩阵视图已迁权限管理页 |
| 数据平台（模拟） 外链 | management/ae/optimizer | mock-douyin 服务（M2，星图·模拟） |

后台管理 = 知识运营台 + **三大管理页**（spec §16–§19，2026-10-25 table-tree 重构）：

- **人员管理 `/people`**：账号在库（`app_user`，scrypt 哈希）；admin 专属写——开户 / 改密（吊销既有会话）/ 停用启用 / 改绑角色（换绑即吊销会话），一切落审计；搜索（账号/姓名）+ 角色筛选，开户改密走 Dialog。
- **权限管理 `/permissions`**：左角色列表、右「页面→按钮」树形授权（真 Checkbox：页面勾写 `app_menu.roles`、按钮勾写 `app_role_action`，整批保存双写）；自定义角色 CRUD（`app_role`，数据面等同基角色）；底部「数据面权限矩阵」折叠区 = `permissions.yaml` 只读投影（两平面分离的可视证据）。
- **菜单管理 `/menus`**：页面→按钮两级 table-tree（自研组件，菜单/权限两页复用）——label / 图标（白名单内）/ 排序 / 启停；path 与 action 词表白名单锁定不开放增删（菜单 = 前端路由镜像，凭空造菜单只会指向 404）。
- **门与显隐**：`/admin/*` 读门统一 `role_allows('admin_view')`（management 只读、admin 全权），写权 admin 独占；前端按钮显隐统一 `useCan(action)`（`/my-actions`，与后端 role_allows 同一门）。数据面（类白名单/指标/行过滤）真源仍是 `permissions.yaml` + `.env`——**两平面分离**：数据面配置即真源，界面权限（菜单/按钮/自定义角色）真源在 DB。
- **角色门判原始角色（2026-10-26 夜检修复）**：action/端点门一律以 `display_role`（账号原始角色，含自定义）判 `role_allows`——`resolve_identity` 返回的是数据面映射后的基角色，直接拿它判门会让 base=admin 的自定义角色绕过自身 action 配置获得全部写权。角色 CRUD（创建/配置/删除角色）例外：`require_system_admin` 硬门，系统 admin 本尊独占（§18「写仅 admin」），自定义角色即便 base=admin 也不得管理角色。
- **自定义角色回落语义（§18 字面收口）**：**角色级零记录**才整体继承基角色的 action 集；只要有任意一条自身配置即白名单语义，未勾选项不回落——权限树取消勾选真实收权（此前逐 action 回落使取消勾选无效）。
- **admin 自留权不可摘**：`update_role` 守卫 admin 的播种 action 集（account_manage / menu_manage / admin_view / review_resolve / creator_write / creator_export / case_stage_change）不可移除，防自锁。
- **权限树整批保存事务化（2026-10-26 勘误 §19「双写」）**：`PUT /admin/permissions` 单请求单事务同落 `app_role`（label/description/actions）与 `app_menu`（可见集），半途失败整体回滚——两请求双写曾致半途失败两库不一致。

**认证与角色头**：web 走**服务端会话**（spec §2）——`POST /auth/login` 校验 `app_user`（stdlib scrypt + 等时哑校验防用户名探测），签发 `app_session` 表支撑的 HttpOnly cookie（7 天滑动续期、可吊销）；`resolve_identity` 解析优先级 **token > cookie > dev**，登录成败均落审计。~~X-Adkg-Role 换 token~~ **已撤**（2026-10-24）：nginx 不再按头注入 Authorization，web 全靠会话 cookie；`Authorization: Bearer` 直连路保留给 smartServe / eval。每账号绑定唯一 role + Person，**演示期的管理员自由切换身份已移除**（真系统不留后门）；本地开发 `ADKG_DEV_AUTH=off` 不变。

## 十、快速开始

```bash
docker compose up -d                         # Postgres:5433  Neo4j:7474/7687  星图·模拟:8100
uv sync
cp .env.example .env                         # 填 LLM key、service token；本地开发可 ADKG_DEV_AUTH=off
uv run python scripts/init_db.py             # 建表（001–010）+ 双账号 + Neo4j 约束；幂等
ADKG_USER_PASSWORD=xxx uv run python scripts/init_users.py   # web 登录账号（不设密码则随机生成打印一次）
export HF_ENDPOINT=https://hf-mirror.com     # 嵌入模型下载；模型已缓存后改设 HF_HUB_OFFLINE=1 断网防卡
uv run python scripts/gen_seed.py            # 生成种子：CSV 进 data/seed，文档直写 data/raw（幂等，clone 后首跑）
uv run python scripts/load_seed.py           # 导入种子数据（含同素材双平台与 violates 断言样例）；幂等
uv run uvicorn adkg.api.main:app --port 8000 # http://127.0.0.1:8000/docs（改代码后要重启，默认没挂 --reload）
cd web && bun run dev                        # 前端 :5173（vite 代理 → :8000；用 bun，pnpm 与 Node 22.23 不兼容）
```

验证与评测：

```bash
HF_HUB_OFFLINE=1 uv run pytest                              # 全量 255（库不在线自动跳集成）
uv run python eval/run_eval.py                              # golden set 38 题（规则判据 + LLM judge）
uv run python eval/agent_eval.py                            # agent 场景集（/agent/chat ReAct 真 LLM；--types 选型 --rounds N 防抖）
uv run python eval/recalc_agent.py                          # agent 场景数值锚重算（dry-run diff；--yes 落盘）
uv run python eval/run_ablation.py                          # 消融：multi_hop 图谱增益归因
bunx promptfoo@latest eval -c promptfooconfig.json -j 1 --no-cache   # 多角色矩阵 24 用例（必须串行+关缓存）
uv run python scripts/sync_feishu.py                        # 飞书增量同步（.env FEISHU_DOCS / FEISHU_FOLDER）
```

演示用 `data/seed/` 合成数据；真实部署先做 12 个月历史回填（7.2），两条路径分开。

## 十一、使用达到的效果

> 11.1 / 11.2 为演示脚本与目标态叙事；11.3 表是**设定的目标值**，实测小结见表下（Phase 6 终评，2026-10-24）。

### 11.1 演示级效果（六个画面）

1. 问"A 品牌去年抖音哪些素材效果差、和创意规范有没有关系"，一次回答给出素材清单、效果数字、违反的规范条目，每条标来源——现在要开三个系统人工拼。
2. 问"A 品牌对接人是谁，他名下还有哪些 live 案例"，目标秒级返回关系链（纯 graph 路；内部角色，外部角色姓名脱敏）。
3. 同一素材两平台指标同口径放在一张表里，不再各说各话。
4. 没权限的人问 B 品牌的数据，被本体权限过滤，回答里不出现；同一问题不同角色得到不同行数；外部客户跨品牌命中即拒绝并告警。
5. 试图删除 live 案例的素材，被约束拦截并留下审计记录。
6. 生成 AIGC 素材前 Agent 调 `/guideline/check` 拿适用规范与机判阈值，生成后语义比对归 AIGC Agent，`violates` 断言经 `/ingest/assertion` 写回——违规可查、可溯源。

### 11.2 前后对比

| 任务 | 现在（人工 / 双路 RAG） | 目标态 |
|---|---|---|
| 提案前找历史可比案例 | 半天翻文档、问同事 | 分钟级，自带效果数据和来源 |
| 跨系统拼一条关系链 | 开 3 个系统约 5 分钟 | 一次问答（时延口径见 11.3） |
| 两平台口径对比 | 手工对 Excel，口径易错 | `unified_metrics` 自动统一 |
| 素材合规检查 | 人工对照规范 | 生成前机判提示，生成后断言可追溯 |
| 回答的依据 | "模型说的" | 每个数字带来源、时间、权威度，可点回原文 |
| 新 Agent / 新人接入 | 口径和权限口口相传 | 权限矩阵 + 指标口径即配置 |

### 11.3 量化验收

以下为**设定的目标值**，验收跑 `eval/run_eval.py`（LLM judge 按要点打分 + 人工抽检 20%，一致率 <90% 以人工为准并修 rubric）：

| 指标 | 目标 | 说明 |
|---|---|---|
| golden set 回答正确率 | ≥ 80% | 判据 = 要点命中 + 数字一致 + 引用可溯源（[12.3](#123-评测集格式golden_setjsonl)） |
| 引用可溯源率 | 100% | 硬性，缺来源即判错 |
| multi_hop 子集命中 | 多于双路基线 | 双路+Text2SQL 在 multi_hop 上零贡献，增益归因图谱（消融见 7.1） |
| fact 子集 vs 双路+Text2SQL | 预期打平 | 消融边界——图谱不靠它赢，标出边界比全赢更可信 |
| concept 子集召回命中率 | 比双路 ≥ +15 pt | vector 主路线的兜底指标 |
| 路由准确率 | ≥ 90% | 对照 `expected_routes`；走错的由三路全跑兜底 |
| 越权泄漏 | 0 | 构造题含三类：外部客户跨品牌、跨两跳（client 问其他品牌 Campaign 消耗）、越权值参与聚合 |
| 口径一致性 | 人工核对零错误 | 同一素材两平台在 `unified_metrics` 下可比 |
| 抽取 precision / recall | ≥ 0.85 | 人工标注集回归，改 prompt / schema 必跑 |
| 实体对齐抽样正确率 | ≥ 95% | 抽样对（7.4） |

**实测小结**（Phase 6 终评，2026-10-24，38 题）：规则判据口径 multi_hop 17/17 全过；LLM judge 要点命中 32–34/35（跨 run 抖动；历史抖动源为判据串债与 judge 波动，见 `eval/runs/` 存档）；本地复跑 37/38（时点产物）。回归底座：pytest 255 绿（截至 2026-10-27）、promptfoo 多角色矩阵 24 用例全绿（时点记录；批任务永不上服务器，docs/deployment.md §五）。

非功能目标（设计值）：graph 路 p95 ≤ 5s、text2sql 路 ≤ 15s、归因混合 ≤ 30s；每问 LLM 调用 ≤ 3 次；并发 ≤ 10。部署口径：演示与内部为单机 docker-compose，不承诺 SLA；客户方外部自助看数为演进项（独立部署 + 网络隔离）；全量重跑抽取约 10⁷ token 量级（满配规模假设，seed 更小）。

### 11.4 收益本质

三层目的，对应三类听众：

- **业务**：覆盖案例创建全生命周期——proposal 阶段快速检索可比案例支撑提案，live 阶段素材合规自动管控，closed 阶段复盘归因有数据有依据；顺手解决抖音、小红书口径不统一的老问题。
- **技术**：用可量化的方式验证"本体 + 图谱 + 三路召回 + 管控"相对纯 RAG 到底多了什么，沉淀可复用资产：本体 schema、源到本体的映射、评估协议。换行业只换资产、代码不动（清单见 9.6）。
- **作品**：与 smartServe 构成"Agent 引擎 + 知识中台"的完整叙事，有架构图、有 demo 画面、有对比数字。

## 十二、约定

### 12.1 provenance 四元组（任何入库必带）

```text
source_type : system_of_record | platform_api | official_doc | wiki | conversation
              （CRM / 案例系统 / 组织系统等内部主数据源归 system_of_record）
source_id   : 文档 ID / 文件 hash / API 请求标识
fetched_at  : ISO 时间
authority   : 由 source_type 查表得出（12.2），不单独配置（模型层强制，手给不符值抛异常）
---- 可选 ----
source_url  : 可回跳地址
version     : 文档 revision / 数据批次（缺省取 fetched_at 日期作幂等键）
confidence  : 抽取置信度 0–1（事实表恒为 1）；≥0.7 入图、0.4–0.7 进 review_queue、<0.4 丢弃
```

### 12.2 权威度（`authority.yaml`）

`system_of_record(100) > platform_api(80) > official_doc(60) > wiki(40) > conversation(20)`，五级与 source_type 一一对应。同一实体字段冲突时取高者（**当前在低权威写路径实现**：`/ingest/assertion`、达人录入——高者在场不覆盖、冲突进 review_queue；常规 MERGE 为直接覆盖）。**同分规则**（tie_breaker 链，`authority.yaml` 声明的仲裁契约）：authority 相同（如两个 Agent 同为 conversation）比 confidence，高者暂胜；缺失或相等比 fetched_at 取新者；仍不能判定则双方标 `conflicted` 进 review_queue。

### 12.3 评测集格式（`golden_set.jsonl`）

```json
{"id": "G01", "type": "multi_hop", "question": "A 品牌对接人名下还有哪些 live 案例？",
 "data_window": "滚动近 12 月",
 "expected_routes": ["graph"], "must_hit": ["Person", "Case"],
 "expected_answer": {"points": ["对接人姓名", "live 案例清单"], "must_entities": ["Case:C-2025-118"], "must_numbers": []},
 "notes": "默认分母：该对接人名下全部 live 案例"}
```

`type ∈ {multi_hop, fact, concept, attribution, operation}`；20 题种子按 5/4/4/4/3 起步，Phase 6 扩至 **38 题**（multi_hop 17 / fact 10 / concept 4 / attribution 4 / operation 3）；50 题全量（multi_hop ≥15）留待真实数据接入后扩。rubric：正确 = 要点命中 + 数字一致 + 引用可溯源。`data_window` 标明题目依赖的数据窗口——种子为滚动窗口（止于上月），窗口类题（上月/近 N 天）的期望数字随数据重生成联动改写。**库值锚点重算脚本化（`eval/recalc_golden.py`）**：种子扩容 / 口径调整后按当前库（PG / Neo4j 直查）重算期望里的数值与实体锚——dry-run 出 diff、`--yes` 落盘、幂等；日常回归仍用 `run_eval.py` 对拍不重算。

**agent 场景集（`eval/agent_scenarios.jsonl`，2026-10-29 起，wayfinder 图「agent 真实化评测」）**：与 golden 单问一答互补的第二评测面——真实措辞打 `/agent/chat` ReAct 全链路（真实 LLM 多轮工具、真实角色权限，不 mock 不降级）。`type ∈ {query, stat, comparison, casegen}`：query=真实措辞查询（口语/行话/模糊指代/一问夹两事，含越权问法）；stat=统计聚合（排序/汇总/时间窗口语变体）；comparison=对比（双实体/双平台/双期间，双边数值锚+结论方向断言）；casegen=案例生成生命周期（draft 字段断言 → `/ingest/case-commit` → 图上落点断言——建号约定/关系/authority/别名——跑后清理不留脏数据）。判据三件：judge 要点（复用 `judge.py`，证据=reply+trace 工具结果）、`must_numbers` 数值锚（容差 ±max(0.06, 1%) 同 golden；锚点重算走 `eval/recalc_agent.py`，协议同 recalc_golden、聚合口径复用 `metrics.agg_expr` 单源）、场景断言。**验收口径：每型分别 ≥90% 且数值锚全中、连续两轮达标**（`--rounds`，防 LLM 时延/质量单轮抖动）；casegen 按场景断言全过计。降级（degraded）进报告清单，不静默算过。

### 12.4 权限矩阵（`permissions.yaml`）

一行一个 role，人和 Agent 共用。身份来源：`bindings` 段只存 token 标识 → role / Person 的映射结构，token 本体进 `.env` / 密管（git 资产不放明文密钥）；**token 路由 person 取 bindings 唯一绑定**（零绑/多绑时回退 body/query 自报兜底——当前每 role 恰一条绑定，不触发）。默认策略：**内部角色类白名单 + 属性黑名单；外部角色（客户方）一律白名单 `allow_properties`，schema 新增属性默认不可见（fail-closed）**。指标列权限：内部 `metrics_deny` / 外部 `metrics_allow`，作用域 = `unified_metrics` 列 + Text2SQL 可选字段（per-role 视图）。**派生联动**：deny 一列时同步 deny 含它的派生列（deny cost 连带 cpa / roi，防乘法反推；同理 impressions→cpm/ctr、clicks→ctr/cvr）；gross_margin 为内部核算列，Case 属性与指标列两处同步 deny。**行权限 fail-closed（2026-10-23）**：配置了 `row_filter` 的角色在 person 缺失、图中无此人或展开结果为空时产出 **deny-all plan**（`PermissionPlan.deny_all=True`——graph / vector 路零证据、text2sql 恒假谓词），而非跳过行过滤；`/graph/entity` 主实体与 `/ask` graph 路属性证据同过类白名单与可见集闸（全局类豁免）；`/creative/brands` 与 Agent 品牌工具按可见 Brand 裁剪；`/ingest/assertion` 要求 `actions` 含 `write_assertion`；`/ingest/case-commit` 案例生成角色门（CASEGEN_ROLES：admin/management/optimizer/ae）之上再要求 `actions` 含 `create_case`（2026-10-27 收口：曾只查角色门，optimizer 无该动作也能 commit；`/agent/chat` 下发的 `can_commit_case` 同源判定，前端不再见点了必 403 的按钮）；审计随写落账。

```yaml
bindings:
  tok-optimizer-li: {role: optimizer, person: Person:li}

optimizer:                          # 内部角色：类白名单 + 属性黑名单
  classes: [Case, Campaign, Creative, Channel, Metric, Guideline, Creator]
  deny_properties: [Case.bd_budget, Case.gross_margin]
  metrics_deny: [gross_margin]
  actions: [read, create_creative, pause_campaign, delete_creative]
  row_filter: Person(responsible_for)->Case<-belongs_to-Campaign-uses->Creative

client:                             # 外部角色：一律白名单
  external: true                    #   外部标记：驱动 assemble/graph 出口人名脱敏
  classes: [Case, Campaign, Creative, Metric]
  allow_properties: [Case.stage, Case.lost_reason, Campaign.status]
  metrics_allow: [cost, ctr, cvr, conversions]
  actions: [read]
  row_filter: Person(external_for)->Brand<-for_brand-Case<-belongs_to-Campaign
```

`row_filter` 语义 = **锚点 + 路径 + 方向**（支持多跳与反向路径）；全局类（Metric、Guideline、Channel）不挂锚点、不参与 row_filter，类白名单内即全量可见；行过滤沿关系**级联收窄**：Case 收窄后 belongs_to / uses 下游随之收窄，未连通实例默认不可见。row_filter 的翻译收口在 `permission.py` 一处，产出 PermissionPlan：graph / vector 路消费过滤器，text2sql 路注入 SQL 谓词（7.3）。动作词表与 9.4 一致，落在 `schema.yaml#actions`。

### 12.5 实体 ID 规则

- 内部主键平台无关、本体命名空间内唯一，格式 `{class}:{slug}`（`Case:C-2026-008`、`Creative:creative_992`、`Guideline:G-03`）
- 平台 ID 一律作 external_id 进 `entity_alias(source, external_id, internal_id)`，不进任何主键
- 事实表带 `platform + creative_local_id` 及物化的 campaign_id / case_id / brand_id 冗余列（etl_facts 按图侧关系回填，见八），本体 ID 经 entity_alias 换算后进 `unified_metrics`；对不上标 unmatched 进 review_queue、不进跨平台对比
- token → Person 绑定落 permissions.yaml `bindings` 段（9.1；row_filter 锚点直接用绑定 person ID）
- seed 预置同一素材双平台样例（画面 3 与口径一致性验收的锚点）

### 12.6 数据边界与保留

- **出库最小化**：发往 LLM 的只有抽取 chunk 文本、问题文本、Text2SQL 的 schema 与问题；数值 / 成本 / 毛利只在本地 Postgres 执行——Text2SQL 天然数值不出库，这是相对"数仓喂 LLM"方案的现成加分项
- **Person 敏感**：不存联系方式；Person 节点对外部角色整体不可见（client 的 classes 不含 Person）；chunk 与答案文本中出现的姓名字样在 assemble 出口掩码（实现留代码层）
- **保留与删除**（设计约定，非法律承诺）：事实与审计 ≥1 年，audit_log 只追加；合同终止按 Brand 删图层与事实层，原始层标记废弃、不再参与召回

## 十三、与 smartServe 的关系

| | smartServe（agent-all） | AdKG（本项目） |
|---|---|---|
| 角色 | Agent 引擎：LangGraph 多 Agent 编排、工具调用、对话 | 知识中台：本体、图谱、三路召回、管控 |
| 调用 | 持 service token 调 `/ask` `/graph` `/actions/check` `/guideline/check`，注册为工具；Agent 受托调用带双身份（9.1） | 为引擎提供"查什么、能动什么"的依据 |
| 写操作 | `/actions/check` 只裁决（allow / deny + 依据 + audit_id）；引擎执行后回传结果与平台回执，补写审计 | 不代执行（决策点不是执行点） |
| AIGC | 语义 / 多模态比对归素材 AIGC Agent 或人工 | 收口规范检索（`/guideline/check`）与断言写回（`/ingest/assertion`），过权限与审计 |
| 故障边界 | AdKG 不可用时**fail-closed**：知识类请求报错并明示原因，不旁路、不缓存降级 | 底层存储凭据不向引擎暴露；PG 仅经 WireGuard 隧道可达 B 机，隔离靠账号与 database 边界（agent_user 无 adkg 库权限）；可用性由 AdKG 自身负责（compose 跑库 + systemd Restart=always 跑 API），不转嫁给调用方 |

换行业的重写边界见 9.6：复用代码与评估协议，重写本体与数据资产——这是本项目作为方法论的可复用边界。
