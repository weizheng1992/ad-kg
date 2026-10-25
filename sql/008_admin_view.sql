-- ==================================================================
-- AdKG 008 admin_view 存量回填（spec §19 读门收口）：/admin/* 读端点自本轮起
-- 统一走 role_allows('admin_view')，management 需持有该 action 才维持只读入口。
-- ensure_seed 是「角色级零记录才播种」——角色已有任意记录时新 action 传播不到
-- 存量库，故补本迁移；语义与 ensure_seed 对齐：
--   ① management 在 app_role_action 已有任何记录（含管理员手工调过的配置）
--     则不动——铁律：不覆盖用户已删配置；
--   ② app_role 尚无 management 行（全新库）也跳过——应用层 ensure_seed 会按
--     SYSTEM_ROLE_ACTIONS 全量播种（本就含 admin_view），避免违反外键。
-- 幂等：重复执行结果不变。
-- ==================================================================

INSERT INTO app_role_action (role, action)
SELECT 'management', 'admin_view'
WHERE EXISTS (SELECT 1 FROM app_role WHERE name = 'management')
  AND NOT EXISTS (SELECT 1 FROM app_role_action WHERE role = 'management')
ON CONFLICT DO NOTHING;
