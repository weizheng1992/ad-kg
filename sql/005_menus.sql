-- ==================================================================
-- AdKG 005 侧边栏菜单（spec §17 菜单管理）：菜单项数据驱动——
-- path/icon 锁定白名单（对应真实路由），label/roles/sort/enabled 可由 admin 调。
-- 首访懒播种默认（= 代码内 DEFAULT_MENUS，与导航矩阵一致）；幂等。
-- 注意：菜单可见性是导航体验层，不是权限闸——路由真闸在后端各端点。
-- ==================================================================

CREATE TABLE IF NOT EXISTS app_menu (
    path       text PRIMARY KEY,          -- 路由路径（白名单锁定）
    label      text NOT NULL,
    icon       text NOT NULL,             -- 图标名（前端 lucide 白名单）
    roles      text NOT NULL,             -- 可见角色，逗号分隔（角色名无逗号）
    sort       int  NOT NULL,
    enabled    boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT now()
);
