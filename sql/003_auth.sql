-- ==================================================================
-- AdKG 003 Web 认证（spec docs/specs/2026-10-24-真实系统化升级-spec.md §2）
-- 账号在库（app_user，scrypt 哈希）+ DB 会话（app_session，可吊销/滑动续期）
-- 最小账号面：无管理 UI，开户走 scripts/init_users.py（README §9.7 拍板重述）
-- 幂等：IF NOT EXISTS，可重复执行
-- ==================================================================

CREATE TABLE IF NOT EXISTS app_user (
    id            text PRIMARY KEY,         -- u_<username>
    username      text NOT NULL UNIQUE,
    password_hash text NOT NULL,            -- scrypt$<salt-b64>$<hash-b64>
    display_name  text NOT NULL,
    role          text NOT NULL,            -- permissions.yaml 的 role 名
    person        text,                     -- Person:<slug> 绑定（audit user_id / 行权限锚点）
    disabled      boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_session (
    token        text PRIMARY KEY,          -- secrets.token_urlsafe(32)，只在 cookie 里
    user_id      text NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_app_session_user ON app_session(user_id);
