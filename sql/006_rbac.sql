-- ==================================================================
-- AdKG 006 RBAC（spec §18）：角色可建可配——自定义角色（继承基角色数据面）
-- + 角色的按钮/操作权限。系统角色自 permissions.yaml 播种（source=system）。
-- 数据面（类白名单/指标/行过滤）真源仍是 permissions.yaml：自定义角色在数据面
-- 等同其基角色（guards/http.py 解析时映射），菜单与按钮权限在 DB。
-- ==================================================================

CREATE TABLE IF NOT EXISTS app_role (
    name        text PRIMARY KEY,          -- 角色名（登录用；创建后不可改）
    label       text NOT NULL,
    source      text NOT NULL DEFAULT 'custom' CHECK (source IN ('system', 'custom')),
    base_role   text NOT NULL,             -- 数据面基角色（system 角色 base=自身）
    description text NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_role_action (
    role   text NOT NULL REFERENCES app_role(name) ON DELETE CASCADE,
    action text NOT NULL,                  -- 按钮权限键（rbac.py ACTIONS 词表）
    PRIMARY KEY (role, action)
);
CREATE INDEX IF NOT EXISTS idx_role_action_role ON app_role_action(role);
