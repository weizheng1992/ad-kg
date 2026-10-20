-- ==================================================================
-- AdKG 001 初始化（README §八 五层存储）
-- Postgres 18 + pgvector 0.8；主键用 PG18 原生 uuidv7()（时间有序，
-- 正好做 audit_log / ingest_job 的主键，§五）
-- 幂等：全部 IF NOT EXISTS，可重复执行
-- ==================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ------------------------------------------------------------------
-- 溯源层：provenance（四元组强制在应用层校验，表结构兜底 NOT NULL）
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS provenance (
    id          uuid PRIMARY KEY DEFAULT uuidv7(),
    source_type text NOT NULL CHECK (source_type IN
        ('system_of_record', 'platform_api', 'official_doc', 'wiki', 'conversation')),
    source_id   text NOT NULL,
    fetched_at  timestamptz NOT NULL,
    authority   int  NOT NULL,            -- 由 source_type 查表得出（§12.2）
    source_url  text,
    version     text,                     -- 缺省取 fetched_at 日期（§八 双写幂等键）
    confidence  real CHECK (confidence BETWEEN 0 AND 1)
);

-- ------------------------------------------------------------------
-- 溯源层：entity_alias —— (source, external_id) → internal_id 正主（§12.5）
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_alias (
    source        text NOT NULL,          -- 平台 / 系统 / token 标识
    external_id   text NOT NULL,
    internal_id   text NOT NULL,          -- 本体 ID {class}:{slug}
    PRIMARY KEY (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_alias_internal ON entity_alias (internal_id);

-- ------------------------------------------------------------------
-- 向量层：chunks —— class / brand_id / case_id 是权限下推元数据列（§八）
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    id           uuid PRIMARY KEY DEFAULT uuidv7(),
    doc_id       text NOT NULL,
    chunk_index  int  NOT NULL,
    text         text NOT NULL,
    entity_class text,
    brand_id     text,
    case_id      text,
    embedding    vector(512),             -- bge-small-zh-v1.5 · cosine（§五）
    provenance_id uuid NOT NULL REFERENCES provenance (id),
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (doc_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_brand  ON chunks (brand_id);
CREATE INDEX IF NOT EXISTS idx_chunks_case   ON chunks (case_id);
CREATE INDEX IF NOT EXISTS idx_chunks_class  ON chunks (entity_class);
CREATE INDEX IF NOT EXISTS idx_chunks_hnsw ON chunks
    USING hnsw (embedding vector_cosine_ops);

-- ------------------------------------------------------------------
-- 溯源层：review_queue —— 人审队列（冲突 / 对齐失败 / 缺口 / 对账差异 / 低置信断言）
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS review_queue (
    id          uuid PRIMARY KEY DEFAULT uuidv7(),
    kind        text NOT NULL CHECK (kind IN ('conflict', 'unmatched', 'gap', 'reconcile', 'low_confidence')),
    payload     jsonb NOT NULL,
    status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'approved', 'rejected')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by text
);

-- ------------------------------------------------------------------
-- 溯源层：audit_log —— 只追加（§八：保留 ≥1 年、仅 admin 可读）
-- UPDATE/DELETE 权限在 init_db.py 里对 adkg_rw 收回；表内不再做触发器
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id        uuid PRIMARY KEY DEFAULT uuidv7(),
    ts        timestamptz NOT NULL DEFAULT now(),
    user_id   text,                       -- 双身份：user + agent_id（§9.1）
    role      text NOT NULL,
    agent_id  text,
    action    text NOT NULL,
    target    text,
    verdict   text CHECK (verdict IN ('allow', 'deny', 'filtered', 'info')),
    reason    text,
    trace_id  text
);

-- ------------------------------------------------------------------
-- 溯源层：ingest_job —— 双写一致性的落库状态与幂等键（§八）
-- 幂等键 = (source_id, version)；run.py 按 job 重放补偿
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ingest_job (
    id            uuid PRIMARY KEY DEFAULT uuidv7(),
    source_id     text NOT NULL,
    version       text NOT NULL,      -- 缺省取 fetched_at 日期，由写入方给值（§八）
    raw_ref       text,                   -- data/raw/ 落盘路径或 hash
    pg_status     text NOT NULL DEFAULT 'pending' CHECK (pg_status     IN ('pending', 'done', 'failed')),
    neo4j_status  text NOT NULL DEFAULT 'pending' CHECK (neo4j_status  IN ('pending', 'done', 'failed')),
    error         text,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, version)
);

-- ------------------------------------------------------------------
-- 事实层：素材粒度（platform × campaign × creative × day，一行一素材一平台一天）
-- 维度列 campaign_id / case_id / brand_id 由 etl_facts 从图侧关系物化（§八）；
-- creative_id 为 NULL 即 unmatched —— 002 视图过滤，不进跨平台对比（§12.5）
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS creative_metrics_daily_douyin (
    date              date NOT NULL,
    campaign_local_id text NOT NULL,
    creative_local_id text NOT NULL,
    creative_id       text,               -- 经 entity_alias 换算的本体 ID
    campaign_id       text,
    case_id           text,
    brand_id          text,
    cost              numeric(14, 2) NOT NULL,
    impressions       bigint NOT NULL,
    clicks            bigint NOT NULL,
    conversions       bigint NOT NULL,
    provenance_id     uuid NOT NULL REFERENCES provenance (id),
    PRIMARY KEY (date, campaign_local_id, creative_local_id)
);

-- 维度物化补列（幂等）：product_id 由 case→for_product 推导（§八；2026-10-20 商品粒度统计）
ALTER TABLE creative_metrics_daily_douyin ADD COLUMN IF NOT EXISTS product_id text;
ALTER TABLE creative_metrics_daily_xhs   ADD COLUMN IF NOT EXISTS product_id text;

-- 商品交易事实（§六 交易口径分列：购买率 = orders / clicks，需与投放点击按 product×day join）
CREATE TABLE IF NOT EXISTS product_orders_daily (
    date           date NOT NULL,
    product_id     text NOT NULL,
    orders         bigint NOT NULL,
    gmv            numeric(14, 2) NOT NULL,
    provenance_id  uuid NOT NULL REFERENCES provenance (id),
    PRIMARY KEY (date, product_id)
);

-- 小红书侧：列结构与抖音对称（中文表头的设计留给 seed CSV——平台导出是中文表头，
-- 由 etl_facts 按 mappings/xiaohongshu.yaml 翻译后进本表，映射层的演示在那一路）
CREATE TABLE IF NOT EXISTS creative_metrics_daily_xhs (
    date              date NOT NULL,
    campaign_local_id text NOT NULL,
    creative_local_id text NOT NULL,
    creative_id       text,
    campaign_id       text,
    case_id           text,
    brand_id          text,
    cost              numeric(14, 2) NOT NULL,
    impressions       bigint NOT NULL,
    clicks            bigint NOT NULL,
    conversions       bigint NOT NULL,
    provenance_id     uuid NOT NULL REFERENCES provenance (id),
    PRIMARY KEY (date, campaign_local_id, creative_local_id)
);
