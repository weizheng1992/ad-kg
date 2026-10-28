-- ==================================================================
-- AdKG 011 回执 verdict 扩枚举（备忘⑮，2026-10-28 拍板「现在实现」）：
-- /actions/receipt 落地——执行方回写结果补审计链，outcome（done/failed/
-- skipped）作为新行 verdict 存储，可直接按 verdict 查询已执行/失败动作。
-- audit_log 只追加：回执写新行（action=action_receipt，target=audit:<原id>），
-- 不回改原裁决行。幂等：DROP IF EXISTS 后重建同名约束。
-- ==================================================================

ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_verdict_check;
ALTER TABLE audit_log
  ADD CONSTRAINT audit_log_verdict_check
  CHECK (verdict IN ('allow', 'deny', 'filtered', 'info',
                     'done', 'failed', 'skipped'));
