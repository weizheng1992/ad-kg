-- ==================================================================
-- AdKG 004 达人报价历史（spec §15）：每次报价入库（录入/导入/平台抓取）追加快照，
-- 详情页出报价随时间曲线。只追加，不改写（历史即事实）。
-- 幂等：IF NOT EXISTS；数据由 load_seed（种子轨迹）与三条入库口运行时追加。
-- ==================================================================

CREATE TABLE IF NOT EXISTS creator_quote_history (
    id           uuid PRIMARY KEY DEFAULT uuidv7(),
    creator_id   text NOT NULL,
    date         date NOT NULL,
    quote_20s    int  NOT NULL,
    source_type  text NOT NULL,
    source_id    text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (creator_id, date, source_type)
);
CREATE INDEX IF NOT EXISTS idx_cqh_creator ON creator_quote_history(creator_id, date);
