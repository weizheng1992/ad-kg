# AdKG — 本体驱动的广告营销知识中台

> 把"文档知识"与"平台效果数据"按同一套领域本体建模，用知识图谱 + 向量 + Text2SQL 三路召回回答跨系统问题，并以本体为边界对 Agent 的检索与操作做管控，全链路可溯源。

- 业务域：App 引流效果广告（抖音 / 小红书投放），主线实体是**案例**（proposal → live → closed）
- 定位：知识与管控层。它不是 Agent 引擎，而是 Agent 引擎（如 smartServe）"查什么、能动什么"的依据
- 状态：**设计阶段**。本 README 是目录结构与框架的稳定基线，代码按路线图（7.1）逐步实现

目录：[一、为什么使用](#一为什么使用) · [二、核心设计思想](#二核心设计思想) · [三、架构总览](#三架构总览) · [四、目录结构（稳定基线）](#四目录结构稳定基线) · [五、技术栈与规模假设](#五技术栈与规模假设) · [六、本体概览](#六本体概览) · [七、数据流程](#七数据流程) · [八、五层存储](#八五层存储) · [九、如何使用](#九如何使用) · [十、快速开始（规划，代码就绪后生效）](#十快速开始规划代码就绪后生效) · [十一、使用达到的效果](#十一使用达到的效果) · [十二、约定](#十二约定) · [十三、与 smartServe 的关系](#十三与-smartserve-的关系)

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

**判断标准**：单类命中各有便宜解（事实数据加一路 Text2SQL 就够），两类以上才需要共享语义模型；只是文档问答，双路 RAG 就是终点，上图谱反而是负资产。广告业务四类全中——20 题的命中类型标注见 `eval/golden_set.jsonl`，是标注结果不是断言。

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
2. 权限一视同仁：权限矩阵对人和对 Agent 是同一张；Agent 受托替人调用时，生效权限取 Agent role 与终端用户 role 的**交集**（最小权限）。**管控收口在知识层**——散在各 Agent 的 prompt 里，每加一个 Agent 就多一份泄露面；收口在本体，Agent 来多少个都是同一套闸门
3. 交接即结构：Agent 之间 handoff 传本体化的结构（实体 + 关系 + provenance），不传自由文本，下游可验证再接
4. 写冲突有仲裁：两个 Agent 对同一实体写入，按 authority 排序，低者进 `review_queue` 人审；同分比 confidence、再比时间取新（见 [12.2](#122-权威度authorityyaml)）

**多域——演进出来的，不是设计出来的。** 先分清两种"多域"：域内子域（投放、素材、客户）一个本体分模块即可；跨业务域（广告 + 电商 + 客服）才需要架构决策。当前覆盖口径：主线 12 类覆盖投放 / 素材 / 客户；财务仅属性级覆盖（`gross_margin`、`settlement_status`），独立结算类二期再议。

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
                                         │ HTTP API（service token 认证）
┌────────────────────────────────────────▼───────────────────────────────────────────────────────┐
│ 服务层   adkg/api   /ask（只收查询）· /ingest · /graph · /actions/check · /guideline/check │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 管控层   adkg/guards   认证 · 权限过滤（本体级）· 操作前约束校验 · 审计（只追加）           │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 召回层   adkg/retrieval   router（本体理解→路由）→ vector │ graph │ text2sql → assemble        │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 存储层   adkg/store   raw │ vector(pgvector) │ graph(Neo4j) │ facts │ provenance               │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 加工层   adkg/pipeline   chunking → extraction → resolution → conflict · etl_facts            │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 接入层   adkg/connectors   files · feishu · platforms · warehouse                           │
├────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 本体层   ontology/   schema · mappings · authority · permissions                            │
│                           ↑ 唯一语义真源，横贯以上所有层                                      │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 四、目录结构（稳定基线）

设计原则：**资产与代码分离**（`ontology/`、`eval/`、`sql/` 是资产，先于代码固化）；**代码按层分包**，层与层只通过明确的数据模型（`adkg/models.py`）交互；每层一个目录，每个文件一个职责。

```text
ad-kg/
├── README.md
├── .gitignore                     # .env、data/raw/、eval/runs/、.venv、__pycache__/、web 构建产物
├── pyproject.toml                 # uv 管理的 Python 项目
├── docker-compose.yml             # Postgres(pgvector) + Neo4j
├── .env.example                   # 连接串、LLM key、service token 模板
│
├── ontology/                      # 【资产】本体：唯一语义真源
│   ├── schema.yaml                #   类、属性、关系、约束、动作词表
│   ├── authority.yaml             #   来源权威度排序，冲突仲裁用
│   ├── permissions.yaml           #   角色 → 可见类 / 属性 / 指标列 / 操作 的矩阵（人和 Agent 共用）
│   └── mappings/                  #   各数据源 → 本体映射
│       ├── douyin.yaml            #     巨量引擎字段 → Campaign / Creative / Metric
│       ├── xiaohongshu.yaml       #     聚光平台字段 → 同一套 Metric
│       ├── case_doc.yaml          #     案例文档结构 → Case / Brand / Product
│       └── warehouse.yaml         #     数仓 / CRM / 组织系统 schema → 本体类（只建映射不搬数）
│
├── adkg/                          # 【代码】Python 包
│   ├── __init__.py
│   ├── config.py                  #   环境与连接配置
│   ├── llm.py                     #   LLM 客户端适配（OpenAI 兼容接口）
│   ├── models.py                  #   Pydantic 模型：Entity / Relation / Chunk / Fact / Provenance / PermissionPlan / RouterPlan
│   │
│   ├── connectors/                #   接入层：只负责拿到原始数据，不做语义解释
│   │   ├── base.py                #     Connector 协议：fetch() → RawRecord（必带 provenance）
│   │   ├── files.py               #     本地 PDF / Word / Excel / Markdown（含平台后台导出文件）
│   │   ├── feishu.py              #     云文档增量同步（按 revision）
│   │   ├── platforms.py           #     巨量引擎 / 聚光 API，或后台导出文件
│   │   └── warehouse.py           #     数仓 / 业务库：只读 information_schema 建映射
│   │
│   ├── pipeline/                  #   加工层：原始数据 → 向量 + 图 + 事实
│   │   ├── chunking.py
│   │   ├── extraction.py          #     LLM 实体 / 关系抽取：结构化输出 + schema 校验，置信度分级（入图 / 人审 / 丢弃）
│   │   ├── resolution.py          #     实体对齐消歧：四级漏斗（事实路以 ID 归一为主）
│   │   ├── conflict.py            #     与已有事实冲突 → 人审队列
│   │   ├── etl_facts.py           #     平台数据按 mappings 进事实表，经 entity_alias 换算本体 ID
│   │   └── run.py                 #     流水线编排：按 ingest_job 重放补偿与对账
│   │
│   ├── store/                     #   存储层：五层各一个适配器
│   │   ├── raw.py                 #     原始层：本地目录 / 对象存储，不可变
│   │   ├── vector.py              #     pgvector（chunk 带 class / brand_id / case_id，检索按角色过滤）
│   │   ├── graph.py               #     Neo4j
│   │   ├── facts.py               #     事实表 + unified_metrics 统一口径视图
│   │   └── provenance.py          #     溯源表 + 实体别名 + 人审队列 + 审计日志
│   │
│   ├── retrieval/                 #   召回层
│   │   ├── router.py              #     本体理解 → 路由计划（含串行依赖与置信度）
│   │   ├── vector_search.py
│   │   ├── graph_search.py        #     multi-hop Cypher（消费 PermissionPlan 的可见 ID 集）
│   │   ├── text2sql.py            #     五道闸：只读账号 · 仅 SELECT · 视图/列白名单 · PermissionPlan 谓词注入 · LIMIT+超时
│   │   └── assemble.py            #     三路结果按本体拼装（含可选重排），出口按 plan 脱敏，汇总 provenance
│   │
│   ├── guards/                    #   管控层
│   │   ├── auth.py                #     service token → role / Person 绑定
│   │   ├── permission.py          #     permissions.yaml → PermissionPlan 工厂：一份矩阵翻译为三路过滤器 + 脱敏规则
│   │   ├── action_check.py        #     操作前校验 schema.yaml 中的约束
│   │   └── audit.py               #     审计日志（只追加，ULID 主键）
│   │
│   └── api/                       #   服务层 FastAPI
│       ├── main.py
│       └── routes/
│           ├── ask.py             #     POST /ask：三路召回，只收查询类，返回带 provenance 的答案
│           ├── ingest.py          #     POST /ingest/doc · /ingest/facts · /ingest/assertion（断言写回）
│           ├── graph.py           #     GET  /graph/entity：实体、关系展开、来源
│           ├── actions.py         #     POST /actions/check：操作裁决 allow/deny + 约束依据 + audit_id
│           └── guideline.py       #     POST /guideline/check：生成前查规范 + 机判阈值校验（时长/尺寸等）
│
├── sql/                           # 【资产】建表脚本
│   ├── 001_init.sql               #   chunks / facts / provenance / entity_alias / review_queue / audit_log / ingest_job
│   └── 002_unified_metrics.sql    #   两平台事实表 → 统一口径视图
│
├── eval/                          # 【资产】评估
│   ├── golden_set.jsonl           #   20 题种子评测集（扩至 50 挂 Phase 6）
│   ├── run_eval.py                #   跑分：三路 vs 双路 / 双路+Text2SQL 消融（fact / multi_hop / concept 三子集）
│   └── runs/                      #   评测结果（gitignore）
│
├── data/
│   ├── seed/                      #   合成种子数据，可提交
│   │   ├── brands_products.csv
│   │   ├── org_people.csv         #   手工维护的"CRM 导出"：人员与品牌对接关系（system_of_record）
│   │   ├── cases_campaigns.csv    #   案例-计划-素材主数据：Case / Campaign / Creative 及其关系
│   │   ├── creative_metrics_daily_douyin.csv   # 素材粒度事实（platform × campaign × creative × day）
│   │   ├── creative_metrics_daily_xhs.csv      # 故意用中文表头，演示映射层的作用
│   │   ├── assertions.csv         #   预置 violates 断言样例（画面 6 演示锚点）
│   │   ├── cases/                 #   案例文档（markdown）
│   │   └── guidelines/            #   创意规范、品牌 VI、广告法条款
│   └── raw/                       #   原始层落盘（gitignore）
│
├── docs/                          #   Phase 6 起沉淀：评测报告、决策记录（届时再定文件名）
│
├── scripts/                       # 一次性脚本
│   ├── gen_seed.py                #   生成合成种子数据（静态文件，可重生成）
│   ├── init_db.py                 #   执行 sql/，建 Neo4j 约束与索引、Postgres 双账号
│   └── load_seed.py               #   导入 data/seed/（含同素材双平台样例）
│
└── tests/                         #   单测（mappings 解析 / PermissionPlan / action_check / provenance 必填）
                                   #   + 集成冒烟（compose 起库 → load_seed → /ask 三例）；越权零泄漏、缺 provenance 拒绝写成不变量测试
```

seed 里两个 `creative_metrics_daily_*.csv` 各含同一素材的记录（同 internal_id、两个平台的 external_id）——跨平台口径验收的锚点（见 [12.5](#125-实体-id-规则)）。

可选扩展（不在稳定基线内，详见 [9.7](#97-前端与运营台webphase-5-后)）：`web/` 前端（React + Vite），Phase 5 后薄演示版、Phase 6 起按需加厚：

```text
web/
├── src/
│   ├── pages/    # ask（问答+证据）· graph（图谱展开）· guideline（规范检查）· review（人审队列）· ops（上传/审计）
│   └── lib/      # API client：由 FastAPI OpenAPI 生成 TS 类型，API 变更编译期报错
```

接入只有一条路：web → HTTP API 服务层（含认证），不直连 Neo4j / Postgres（十三的边界）；浏览器侧认证走反代（nginx / Caddy）登录后注入 Authorization 头，本地演示 `ADKG_DEV_AUTH=off`。

## 五、技术栈与规模假设

| 组件 | 选型 | 理由 | 备选 |
|---|---|---|---|
| 语言 / 包管理 | Python 3.11+ / uv | 与 LangGraph 生态同源，smartServe 已用 uv | — |
| 服务框架 | FastAPI 1.x + Pydantic v2 | 结构化输出校验、OpenAPI 自动生成 | — |
| 认证 | 静态 service token（每 role 一枚）+ 网关注入 | 单人维护相称，不起 OAuth/JWT | — |
| 向量 / 事实 / 溯源 | PostgreSQL 18 + pgvector 0.8 | 一个库同时承载向量、事实表、溯源表，单人维护成本最低；异步 I/O 提升读吞吐，UUIDv7 直接做 audit_log / ingest_job 主键；Text2SQL 只对库内白名单视图生成 | Qdrant / Milvus |
| 嵌入 | Qwen3-Embedding-0.6B · API（1024 维、cosine、HNSW） | MTEB v2 开源榜首、中文强；OpenAI 兼容 API（硅基流动 / 百炼）即插即用，本地权重留作备选；同一模型兼供 7.4 实体对齐的相似候选 | bge-m3（轻量、dense+sparse 多功能）/ 本地权重 |
| 重排（可选） | bge-reranker | 仅对 vector 路候选精排（概念 / 规范类），graph 链路不进重排 | — |
| 图 | Neo4j 2025.09 LTS Community | multi-hop Cypher 表达力强；自带浏览器可视化，演示友好；日历版本制下取 LTS 线 | Postgres 三元组表（本规模下可替代，见下） |
| LLM | OpenAI 兼容接口（GLM / 其他） | 抽取、路由、Text2SQL、评估 judge 共用一个适配层 | — |
| 原始层 | 本地目录 | 单机够用；多人时换 MinIO，接口不变 | MinIO |
| Agent 编排 | 不内置 | 编排在 smartServe engine-py；本项目只暴露 API | — |

**规模假设**（拍板值，非实测，按代投 App 引流、单人维护估计）：品牌 ~50、案例 ~200/年、素材 ~5k、事实行 ~百万级/年、chunk ~1 万、golden set 20 题起。该量级下 Postgres 三元组表也扛得住——选 Neo4j 看重的是 Cypher 多跳表达力与可视化演示，不是规模刚需；量级再涨两个数量级时重估。演示数据用 `data/seed/` 合成种子，量级取上表零头。

**运行形态**（拍板）：**智能在线、资产在本地**——LLM / 嵌入 / 重排全走 OpenAI 兼容 API（`llm.py` 一个适配层，key 进 `.env`），不部署本地模型；数据资产全在本地：seed 进 repo、双库在 docker、raw 在磁盘，零云成本。Postgres 两套账号：`adkg_rw` 应用读写、`adkg_ro` 只读（text2sql 五道闸第一闸 + 评测），由 `scripts/init_db.py` 创建。

**数据三层**：① **合成 seed**——`scripts/gen_seed.py` 生成**静态文件提交进 repo**（品牌 8、案例 20 覆盖全部 stage、素材 ~80 含 1 对双平台同素材、事实行 ~2k/表；规范混入真实广告法条文）；② **手工"CRM 导出"**——`data/seed/org_people.csv` 走 `/ingest/doc` 标 system_of_record，演示 CRM 通道；③ **真实业务数据**——平台走后台导出文件路（官方 API 需真实代理商授权，留给部署方，connector 双 adapter 成真 seam），飞书自建应用按 revision 增量（Phase 2b）。

## 六、本体概览

核心类控制在 12 个，从"案例创建"主线反推，详细定义见 `ontology/schema.yaml`：

| 类 | 说明 | 关键属性 | 主要来源 |
|---|---|---|---|
| Brand / Product | 广告主、商品（App / SKU），主数据，关系的载体 | 品类；app_id、平台 | CRM、案例文档 |
| **Case** | 主线实体，`stage ∈ {proposal, live, closed, lost, terminated}` | stage、bd_budget、gross_margin、settlement_status | 案例系统、proposal 文档 |
| Campaign / Creative | 投放计划、素材 | status、daily_budget；is_aigc、derived_from | 平台 API、导出表 |
| Channel / LandingPage / Audience | 投放上下文：广告位 / 流量场景、落地页、定向人群 | 广告位类型；url；定向包描述 | 平台、配置 |
| **Metric** | 指标**口径定义**（非数值）：CTR / CVR / CPA / ROI 的统一公式 | expr、grain、dedup_rule、valid_scope | 语义层手工定义 |
| Guideline | 创意规范、品牌 VI、广告法条款；可机判规范带结构化阈值属性 | 类型、max_duration 等阈值 | 文档 |
| Person | AE / 优化师 / 客户对接人，权限与责任归属（不存联系方式） | 姓名、组织角色 | 组织系统 |
| DocVersion | 文档版本链，`supersedes` | rev | 云文档同步 |

关键关系：`Case→for_brand→Brand`、`Case→for_product→Product`（N:1）、`Brand→has_product→Product`、`Campaign→belongs_to→Case`、`Campaign→uses→Creative`、`Campaign→in_channel→Channel`（N:1，与事实表的平台维度区分，不重复建模）、`Campaign→targets→Audience`（N:M）、`Creative→links_to→LandingPage`（N:1）、`Creative→complies_with / violates→Guideline`、`Creative→derived_from→Creative`、`Person→responsible_for→Case`、`Person→belongs_to_brand→Brand`（内部对接人归属）、`Person→external_for→Brand`（外部客户账号绑定，N:M，变更走人审）。`平台字段→maps_to→Metric` 是 mappings 层的映射谓词，不是图关系。

Metric 是 `unified_metrics` 视图列的语义锚点，也是 router 识别指标词与 Text2SQL 可用指标白名单的依据；视图实现与 Metric 公式的一致性由 `mappings/` 保证；两平台不可比的指标在映射层不映射、视图列留空。`expr / grain / dedup_rule / valid_scope` 落在 schema.yaml。

关键约束（`guards/action_check.py` 读取）：Case 状态迁移 `proposal→live｜lost`、`live→closed｜terminated`，closed / lost / terminated 为终态不可逆；lost 默认排除出可比案例检索（retrieval 按 stage 过滤）但保留复盘归因；terminated 必填终止原因；live / closed 的 Case 不可删除 Creative；任何写入必须带 provenance。完整迁移表进 `schema.yaml#constraints`。

## 七、数据流程

### 7.1 建设路线（八步，与路线图合一）

| Phase | 做什么 | 产物 | 预估 | 状态 |
|---|---|---|---|---|
| 0 | 列 20 个真实问题并标注命中类型；golden set 骨架；本 README | `eval/golden_set.jsonl`、README | 2d | **进行中** |
| 1 | 定 12 类本体、关系、约束；permissions、authority；`sql/`（含 audit_log、ingest_job）；docker-compose；models.py；run_eval 骨架；纸面评审 | `ontology/`、`sql/`、空库 | 4d | **完成** |
| 2a | 文档路·本地：files connector、chunking、extraction（30 段人工标注回归，precision/recall ≥0.85 才放量）、resolution 前两级、向量 + 图入库；人工只校 schema 和前 50 实体 | 图里第一张关系网 | 6d | **进行中**（关系网已点亮；LLM 抽取回归待 key） |
| 2b | 文档路·飞书：feishu 按 revision 增量（外部依赖：自建应用审批与文档授权）、LLM 判别级对齐 | 云文档自动入库 | 4d | 待开始 |
| 3 | 数据路：platforms connector、近 12 个月历史回填（后台导出文件路）、etl_facts、`unified_metrics` | 同一素材两平台可比 | 4d | 待开始 |
| 4 | 召回与权限：认证、permission 过滤与下推、router、三路检索、融合排序、assemble、`/ask` | `/ask` 能答混合问题 | 6d | 待开始 |
| 5 | 管控收口：`/actions/check`、audit、AIGC 闭环 | 越权被过滤、违规被拦截 | 5d | 待开始 |
| 6 | 评估：golden set 扩至 50 题（multi_hop ≥15）、三基线跑分、对比报告、docs | 一张收益对比表 | 3d | 待开始 |

Phase 2 起每阶段收尾跑 run_eval 记入 `eval/runs/`——"评估先行"落地为每阶段有分数。合计约 34 人日（单人粗估，不装精确）。

### 7.2 运行流程

数据侧三条常驻通道：

- 文档按 revision 增量同步，新版本 `supersedes` 旧版本而不是删除
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
| 单路超时 / 异常 | 降级拼装，答案标注缺席路（响应 `degraded` 字段） |
| text2sql 失败 | 重试一次，仍败则明示"事实数据缺席"——不编数、不降级发查询模板 |
| T+1 ETL 失败 | 原始层已存 API 原始响应，次日自动补跑，缺口行留状态标记 |
| 抽取失败 | 登记 ingest_job 待重放（原始层保底） |
| Neo4j 不可用 | graph 路跳过并标注；Postgres 不可用则服务不可用（事实与向量同库，接受该单点） |

### 7.3 路由决策

| 意图类型 | 示例 | 主路线 | 辅助 |
|---|---|---|---|
| 事实聚合 | 上月 CPA 最差的素材 | text2sql | — |
| 关系链 | 对接人名下的 live 案例 | graph | vector 补充描述 |
| 概念 / 规范 | 创意规范对视频时长的要求 | vector | graph 定位规范节点 |
| 归因混合 | 效果差的素材与规范有没有关系 | graph → text2sql → vector **串行**：graph 圈实体 → 实体 ID 作 text2sql 条件 → vector 取规范原文 | — |
| 操作类 | 删除某素材 | `/actions/check` 校验 → 放行 / 拒绝 | — |

操作类不进 `/ask`：由调用方直接调 `/actions/check`，`/ask` 识别为操作意图时返回端点指引而非答案。

**融合与排序**：路内排序（向量按相似度、图按 confidence × 跳数惩罚、事实按指标）→ 跨路 RRF 合并 → 同一事实按 authority 仲裁（[12.2](#122-权威度authorityyaml)）。router 输出各意图置信度，最高低于阈值 → 三路全跑兜底；响应 `routes_used` 各项带得分，评测可归因到路。路由计划 **RouterPlan**（steps 带依赖与置信度、fallback 标志）是 models.py 一等类型，`ask.py` 只解释执行——路由评测直接对 plan 断言，不起整条 LLM 链路。

**权限下推**：`guards/permission.py` 把 permissions.yaml 翻译成 **PermissionPlan**（metadata_filter / 可见 ID 集 / SQL 谓词 + 列白名单 / 脱敏规则），vector、graph、text2sql 三路与 assemble 出口**只消费 plan、不读权限矩阵**——过滤在召回层内生效，assemble 只见过滤后结果，对外仅布尔 `permission_applied`（计数与明细进审计）；text2sql 路的谓词由系统拼进 WHERE——**不信任生成的 SQL**。越权值不得参与聚合：top-N / 均值一律算在过滤后集合上。翻译收口在一处，越权测试集只打 PermissionPlan 这一个 interface。

### 7.4 实体对齐（四级漏斗）

工程上最耗时的一环，预算见 7.1 Phase 2，各级有判定标准：

| 级 | 做法 | 判定 |
|---|---|---|
| 1 规则归一 | ID 直接映射；名称清洗（去平台前后缀、大小写、全半角） | entity_alias 命中即接受 |
| 2 相似候选 | embedding top-k | 相似度 ≥τ 进下一级（τ 随嵌入模型在 seed 上标定，Qwen3 初值 0.75） |
| 3 LLM 判别 | 候选对交给 LLM | ≥0.8 接受；0.5–0.8 人审；<0.5 拒绝 |
| 4 人审 | review_queue | 产物：entity_alias 行 |

产物：entity_alias 表 + 人审条目。验收：seed 内已知同素材对 100% 命中；抽样 50 对齐正确率 ≥95%（进 11.3）。事实路同走此漏斗，以规则级 ID 归一为主（entity_alias 直接换算），embedding / LLM 只兜名称对齐；对不上的行标 unmatched 进 review_queue、不进跨平台对比。

## 八、五层存储

| 层 | 存什么 | 落点 | 特性 |
|---|---|---|---|
| 原始层 | 原始文件、API 原始响应 | `data/raw/` | 不可变、带 hash、可重跑 |
| 向量层 | chunk 文本、embedding、metadata | Postgres `chunks` | 回答"写了什么"；chunk 带 class / brand_id / case_id，检索按角色过滤 |
| 图层 | 节点（带本体 class 与 provenance）、关系（带 confidence） | Neo4j | 回答"谁和谁有关系" |
| 事实层 | `creative_metrics_daily_*`（platform × campaign × creative × day，一行一素材一平台一天）+ `unified_metrics` 视图 | Postgres | 回答"多少、趋势"；表内物化 campaign_id / case_id / brand_id 冗余列（etl_facts 从图侧关系回填，关系变更时刷新）——campaign / case / brand 级聚合与 row_filter 谓词的落点，不另建事实表；Text2SQL 只对视图与白名单视图生成 |
| 溯源层 | `provenance`、`entity_alias`、`review_queue`、`audit_log`、`ingest_job` | Postgres | 审计（只追加、保留 ≥1 年、仅 admin 可读）、仲裁、对齐 |

**双写一致性**：一次抽取写 Postgres（chunks / facts / provenance）与 Neo4j 两库。顺序 Postgres 先、Neo4j 后；幂等键 = provenance 的 `source_id + version`（version 缺省取 fetched_at 日期），图层一律 MERGE；`ingest_job` 记录每条原始记录两库落库状态，run.py 按 job 重放补偿，失败不跨库留影；每批次收尾对账——图层带 provenance 的节点 / 关系数 vs provenance 表计数，差异写 review_queue。

**备份与重建**：`data/raw/` 是全系统唯一不可再生源，每日增量同步到第二位置（外置盘 / 对象存储，RPO 24h），落盘 hash 兼作完整性校验（多人换 MinIO 时改跨桶复制，约定不变）；Postgres 每日 pg_dump 一次，覆盖向量 / 事实 / 溯源 / 审计；图层可从 raw + ontology 全量重建（重建即全量重跑），Neo4j 低频 dump 排 ETL 前维护窗口，重建耗时 Phase 6 实测补齐。raw 丢失 = 业务历史丢失，任何迁移先迁 raw。

## 九、如何使用

### 9.1 身份与鉴权

- **认证**：静态 service token（每 role 一枚），网关 / 引擎注入 `Authorization` 头；AdKG 校验 token → role，**不信任请求体自报的身份**。未带凭证 401；有凭证但无 Person 绑定，按最小权限只读全局类（Metric、Guideline、Channel，见 12.4）。token 本体进 `.env` / 密管，仓库里只有 bindings 映射结构（[12.4](#124-权限矩阵permissionsyaml)）
- **user ↔ Person**：绑定落 entity_alias 表，作 row_filter 起点
- **外部客户**：独立签发的只读 token（与内部隔离），凭证只标识主体、不含 brand_id；租户绑定走 `Person→external_for→Brand`（N:M，一家客户多品牌即多条），变更走 review_queue 人审并记审计；token 设有效期，吊销 = 从 bindings 移除映射并记审计
- **Agent 受托**：凭证同时携带 agent_id 与终端用户身份；生效权限取 Agent role 与用户 role 的**交集**（最小权限），行过滤取更严者；审计记双身份
- **本地开发**：`ADKG_DEV_AUTH=off` 时允许 body 传 role（仅限本地）

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

操作类请求走独立的裁决端点（AdKG 只裁决，不代执行）：

```http
POST /actions/check
Authorization: Bearer <service-token>
X-ADKG-Actor: agent:aigc-01
{"op": "delete_creative", "target": "Creative:creative_992"}
```

```json
{"decision": "deny",
 "reason": "constraint violated: live/closed 状态的 Case 不可删除 Creative（schema.yaml#constraints）",
 "audit_id": "01JGZ8K7Q4M3NP2T5V9WXBCDRE"}
```

放行时返回 `{"decision": "allow", "basis": "…", "audit_id": "…"}`，调用方自行执行后回传结果与平台回执，补写同一条审计（裁决与回执分两段）。动作词表 `read / create_creative / pause_campaign / delete_creative …` 见 `schema.yaml#actions`。

AIGC 闭环两个端点：`POST /guideline/check` 生成前返回适用规范 + 机判阈值结果（时长 / 尺寸等结构化项，不做语义比对）；`POST /ingest/assertion` 生成后写回断言（`{"subject": "Creative:creative_1007", "predicate": "violates", "object": "Guideline:G-03", "confidence": 0.91}`，provenance 为 conversation / 20）。语义 / 多模态比对归 smartServe 的 AIGC Agent 或人工，AdKG 收口规范检索与断言写回，过权限与审计。

### 9.5 知识怎么进去

| 通道 | 入口 | 机制 |
|---|---|---|
| 手动整理的文件 | `/ingest/doc` 或 `connectors/files` | 解析 → 分块 → 向量 + 抽取入图 |
| 云文档 | `connectors/feishu` 定时 | 按 revision 增量，新版本 `supersedes` 旧版 |
| 平台效果数据 | `connectors/platforms` 每日 | T+1 ETL 进事实表，经 `mappings/` 统一口径 |
| CRM / 组织系统主数据 | 定期导出文件走 `/ingest/doc`（演示期即 `data/seed/org_people.csv`） | 解析入图标 system_of_record——authority 顶层级有真实数据来源 |
| 数仓 / 业务库 | `connectors/warehouse` | 只读 schema 建映射（供 router 理解字段语义），不搬数不直查；指标查询统一走事实层视图（FDW 直查留作扩展） |
| Agent 断言（AIGC 比对结果等） | `/ingest/assertion` | 带低 authority provenance 入图，冲突按 [12.2](#122-权威度authorityyaml) 进 review_queue |
| 对话中暴露的缺口 | Agent 自动写 `review_queue` | 人审通过后入库 |

每条记录落地都带 provenance 四元组（见 [12.1](#121-provenance-四元组任何入库必带)），缺失即拒绝入库。

### 9.6 开发者扩展

| 要做的事 | 改哪里 | 不用动哪里 |
|---|---|---|
| 接一个新平台（如快手） | 新增 `connectors/kuaishou.py` + `mappings/kuaishou.yaml` + `sql/` 新平台事实表（002 视图增并） | `adkg/` 代码三层（pipeline、store、retrieval）零改动 |
| 加一个实体类或关系 | `ontology/schema.yaml` | 抽取 prompt 和校验自动读 schema；新增属性默认不可见（12.4 fail-closed）；Neo4j 无 schema 迁移成本 |
| 接一个新 Agent | `permissions.yaml` 加一个 role + bindings 一条 | 该 Agent 的可见范围和可执行操作即被定义，管控自动收口 |
| 换一个行业 | **重写**：`ontology/` 四件（schema / mappings / authority / permissions）+ `sql/` 事实表与 002 视图 + `data/seed/` + golden_set 题目 | **复用**：`adkg/` 代码、run_eval 评估协议、connector 接入模式（新数据源按第一行增删） |

换行业的重写边界只在此处声明，全文其他提到处均指回本表。

### 9.7 前端与运营台（web/，Phase 5 后）

定位只做三件事：**自助看数、演示、知识运营**——不做对话。内部用户的日常主力界面是 smartServe 的对话（独立项目，见十三）；web 的问答页只作演示、评测可视化，以及无对话入口角色（财务、管理层）的兜底。

| 页面 | 谁用 | 端点 |
|---|---|---|
| 问答 + 证据 | 所有人 | `/ask` |
| 图谱展开 | AE、优化师 | `/graph/entity` |
| 规范检查 | 创意 / AIGC | `/guideline/check` |
| 人审队列 | 知识运营 | `review_queue` + `/ingest` |

后台管理 = 知识运营台，**不做用户管理**：必须有 review_queue 人审界面（冲突对比 + unmatched 对齐——12.2 仲裁与 7.4 对齐闭环的落地）；最好有文档上传与审计查看；角色与 token 留在 `permissions.yaml` + `.env`（配置文件即管理界面），身份生命周期在外部（网关 / 引擎），做用户管理 UI 是负资产。

## 十、快速开始（规划，代码就绪后生效）

```bash
docker compose up -d                         # Postgres:5433  Neo4j:7474/7687
uv sync
cp .env.example .env                         # 填 LLM key、service token；本地开发可 ADKG_DEV_AUTH=off
uv run python scripts/init_db.py             # 建表（含 audit_log、ingest_job）、Neo4j 约束
uv run python scripts/load_seed.py           # 导入种子数据（含同素材双平台与 violates 断言样例）
uv run uvicorn adkg.api.main:app --reload    # http://127.0.0.1:8000/docs
```

演示用 `data/seed/` 合成数据；真实部署先做 12 个月历史回填（7.2），两条路径分开。

## 十一、使用达到的效果

> 本章为**设计目标与演示脚本**，非实测数据；实测以 Phase 6 评测报告为准。

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

以下为**设定的目标值**，验收时跑 `eval/run_eval.py` 得出（LLM judge 按要点打分 + 人工抽检 20%，一致率 <90% 以人工为准并修 rubric）：

| 指标 | 目标 | 说明 |
|---|---|---|
| golden set 回答正确率 | ≥ 80% | 判据 = 要点命中 + 数字一致 + 引用可溯源（[12.3](#123-评测集格式golden_setjsonl)） |
| 引用可溯源率 | 100% | 硬性，缺来源即判错 |
| multi_hop 子集命中 | 多于双路基线 | 20 题种子仅验方向；双路+Text2SQL 在 multi_hop 上零贡献，增益归因图谱；扩至 50 题（multi_hop ≥15）后复测 |
| fact 子集 vs 双路+Text2SQL | 预期打平 | 消融边界——图谱不靠它赢，标出边界比全赢更可信 |
| concept 子集召回命中率 | 比双路 ≥ +15 pt | vector 主路线的兜底指标 |
| 路由准确率 | ≥ 90% | 对照 `expected_routes`；走错的由三路全跑兜底 |
| 越权泄漏 | 0 | 构造题含三类：外部客户跨品牌、跨两跳（client 问其他品牌 Campaign 消耗）、越权值参与聚合 |
| 口径一致性 | 人工核对零错误 | 同一素材两平台在 `unified_metrics` 下可比 |
| 抽取 precision / recall | ≥ 0.85 | 30 段人工标注集回归，改 prompt / schema 必跑 |
| 实体对齐抽样正确率 | ≥ 95% | 抽 50 对（7.4） |

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
authority   : 由 source_type 查表得出（12.2），不单独配置
---- 可选 ----
source_url  : 可回跳地址
version     : 文档 revision / 数据批次
confidence  : 抽取置信度 0–1（事实表恒为 1）；≥0.7 入图、0.4–0.7 进 review_queue、<0.4 丢弃
```

### 12.2 权威度（`authority.yaml`）

`system_of_record(100) > platform_api(80) > official_doc(60) > wiki(40) > conversation(20)`，五级与 source_type 一一对应。同一实体字段冲突时取高者，低者标 `conflicted` 保留供人审。**同分规则**：authority 相同（如两个 Agent 同为 conversation）比 confidence，高者暂胜；缺失或相等比 fetched_at 取新者；仍不能判定则双方标 `conflicted` 进 review_queue。

### 12.3 评测集格式（`golden_set.jsonl`）

```json
{"id": "G01", "type": "multi_hop", "question": "A 品牌对接人名下还有哪些 live 案例？",
 "data_window": "2025-01..2025-12",
 "expected_routes": ["graph"], "must_hit": ["Person", "Case"],
 "expected_answer": {"points": ["对接人姓名", "live 案例清单"], "must_entities": ["Case:C-2025-118"], "must_numbers": []},
 "notes": "默认分母：该对接人名下全部 live 案例"}
```

`type ∈ {multi_hop, fact, concept, attribution, operation}`，20 题种子按 5 / 4 / 4 / 4 / 3 分布，扩至 50 题（multi_hop ≥15）挂 Phase 6。rubric：正确 = 要点命中 + 数字一致 + 引用可溯源。`data_window` 标明题目依赖的数据窗口——超出已沉淀窗口的题在 Phase 0 当场改写，不留给评测日爆雷。

### 12.4 权限矩阵（`permissions.yaml`）

一行一个 role，人和 Agent 共用。身份来源：`bindings` 段只存 token 标识 → role / Person 的映射结构，token 本体进 `.env` / 密管（git 资产不放明文密钥）。默认策略：**内部角色类白名单 + 属性黑名单；外部角色（客户方）一律白名单 `allow_properties`，schema 新增属性默认不可见（fail-closed）**；CI 校验新增属性无 allow / deny 覆盖则报警（Phase 6）。指标列权限：内部 `metrics_deny` / 外部 `metrics_allow`，作用域 = `unified_metrics` 列 + Text2SQL 可选字段（per-role 视图）。**派生联动**：deny 一列时同步 deny 含它的派生列（deny cost 连带 cpa / roi，防乘法反推）；gross_margin 为内部核算列，Case 属性与指标列两处同步 deny。

```yaml
bindings:
  tok-optimizer-li: {role: optimizer, person: Person:li}

optimizer:                          # 内部角色：类白名单 + 属性黑名单
  classes: [Case, Campaign, Creative, Channel, Metric, Guideline]
  deny_properties: [Case.bd_budget, Case.gross_margin]
  metrics_deny: [gross_margin]
  actions: [read, create_creative, pause_campaign, delete_creative]
  row_filter: Person(responsible_for)->Case<-belongs_to-Campaign-uses->Creative

client:                             # 外部角色：一律白名单
  classes: [Case, Campaign, Creative, Metric]
  allow_properties: [Case.stage, Campaign.status]
  metrics_allow: [cost, ctr, cvr, conversion]
  actions: [read]
  row_filter: Person(external_for)->Brand<-for_brand-Case<-belongs_to-Campaign
```

`row_filter` 语义 = **锚点 + 路径 + 方向**（支持多跳与反向路径）；全局类（Metric、Guideline、Channel）不挂锚点、不参与 row_filter，类白名单内即全量可见；行过滤沿关系**级联收窄**：Case 收窄后 belongs_to / uses 下游随之收窄，未连通实例默认不可见。row_filter 的翻译收口在 `permission.py` 一处，产出 PermissionPlan：graph / vector 路消费过滤器，text2sql 路注入 SQL 谓词（7.3）。动作词表与 9.4 一致，落在 `schema.yaml#actions`。

### 12.5 实体 ID 规则

- 内部主键平台无关、本体命名空间内唯一，格式 `{class}:{slug}`（`Case:C-2026-008`、`Creative:creative_992`、`Guideline:G-03`）
- 平台 ID 一律作 external_id 进 `entity_alias(source, external_id, internal_id)`，不进任何主键
- 事实表带 `platform + creative_local_id` 及物化的 campaign_id / case_id / brand_id 冗余列（etl_facts 按图侧关系回填，见八），本体 ID 经 entity_alias 换算后进 `unified_metrics`；对不上标 unmatched 进 review_queue、不进跨平台对比
- token → Person 绑定同落 entity_alias（9.1）
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
| 故障边界 | AdKG 不可用时**fail-closed**：知识类请求报错并明示原因，不旁路、不缓存降级 | 底层存储凭据不向引擎暴露，绕过直查在部署上不可达；可用性由 AdKG 自身负责（单机 compose 重启恢复），不转嫁给调用方 |

换行业的重写边界见 9.6：复用代码与评估协议，重写本体与数据资产——这是本项目作为方法论的可复用边界。
