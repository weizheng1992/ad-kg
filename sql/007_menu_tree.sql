-- ==================================================================
-- AdKG 007 菜单树（spec §18.5）：app_menu 增 parent / type——页面→按钮两级树。
-- 页面条 type=page（parent 空，roles 控可见）；按钮条 type=button（挂 parent，
-- 可见性=角色是否持有对应 action，见 app_role_action）。
-- 幂等：IF NOT EXISTS / DO 块。
-- ==================================================================

ALTER TABLE app_menu ADD COLUMN IF NOT EXISTS parent text;
ALTER TABLE app_menu ADD COLUMN IF NOT EXISTS type text NOT NULL DEFAULT 'page';
ALTER TABLE app_menu ADD COLUMN IF NOT EXISTS action_key text;   -- button 条对应的 action 词表键
