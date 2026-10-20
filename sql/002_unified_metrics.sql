-- ==================================================================
-- AdKG 002 统一口径视图（README §八 事实层 / §六 Metric）
-- 两平台事实表 → unified_metrics；列语义锚点 = ontology Metric 定义
-- （expr / grain / dedup_rule / valid_scope 落在 schema.yaml），
-- 视图实现与 Metric 公式的一致性由 mappings/ 保证（Phase 3 起回归）。
--
-- Text2SQL 只对本视图与白名单视图生成（§7.3 五道闸）；
-- per-role 视图（指标列权限的落点）Phase 4/5 再加，本期不建。
-- 幂等：DROP + CREATE（OR REPLACE 不允许在既有列之前插列，2026-10-20 实测）
-- ==================================================================

DROP VIEW IF EXISTS unified_metrics;
CREATE VIEW unified_metrics AS
SELECT
    platform, date, creative_local_id, creative_id, campaign_id, case_id, brand_id, product_id,
    cost, impressions, clicks, conversions,
    -- 口径列：公式锚点 = Metric 定义；分母为零置 NULL，不编数
    clicks::numeric      / NULLIF(impressions, 0) AS ctr,
    conversions::numeric / NULLIF(clicks, 0)       AS cvr,
    cost                 / NULLIF(conversions, 0)  AS cpa,
    (creative_id IS NULL)                          AS unmatched
FROM (
    SELECT 'douyin' AS platform, date, creative_local_id, creative_id,
           campaign_id, case_id, brand_id, product_id,
           cost, impressions, clicks, conversions
    FROM creative_metrics_daily_douyin
    UNION ALL
    SELECT 'xhs' AS platform, date, creative_local_id, creative_id,
           campaign_id, case_id, brand_id, product_id,
           cost, impressions, clicks, conversions
    FROM creative_metrics_daily_xhs
) t;

-- unmatched = 1（本体 ID 未换算上）的行：单平台查询仍是有效事实，
-- 跨平台对比须过滤 WHERE NOT unmatched（§12.5），标记列让消费方显式做这件事
-- 两平台不可比的指标在映射层不映射、本视图列留空（§六 Metric）
