-- ==================================================================
-- AdKG 010 案例阶段变更授予面回填（2026-10-27 拍板，缺陷备忘余项⑩）：
-- update_stage（数据面，permissions.yaml）与 case_stage_change（按钮/写门，
-- app_role_action）同步开给 management 与 ae——与业务推进人对齐。
-- 与 008 不同，这里 per-action 插入是有意的：拍板即授予，覆盖此前的
-- 「仅 admin」配置（admin 既有授权不受影响，ON CONFLICT DO NOTHING 幂等）。
-- ==================================================================

INSERT INTO app_role_action (role, action)
SELECT 'management', 'case_stage_change'
WHERE EXISTS (SELECT 1 FROM app_role WHERE name = 'management')
ON CONFLICT DO NOTHING;

INSERT INTO app_role_action (role, action)
SELECT 'ae', 'case_stage_change'
WHERE EXISTS (SELECT 1 FROM app_role WHERE name = 'ae')
ON CONFLICT DO NOTHING;
