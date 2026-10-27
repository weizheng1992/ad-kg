-- ==================================================================
-- AdKG 009 达人号序列（缺陷清单⑦b）：/creators 录入与 CSV 导入的自动编号原为
-- Neo4j MAX+1——并发开户/导入两侧同读同一 max 即撞号（MERGE 静默合单）。
-- 改由本序列原子分配：分配语句 setval(greatest(nextval, Neo4j最大+1)) 单条
-- 原子（见 adkg/api/routes/creators.py _next_creator_id），种子/平台抓取抬高
-- 分子时由 GREATEST 对齐，永不回退。renumber 不做（历史即事实）。
-- 幂等：IF NOT EXISTS。
-- ==================================================================

CREATE SEQUENCE IF NOT EXISTS creator_num_seq;
