// 共享文案标签单一来源（2026-10-26 夜检：STAGE_LABEL 曾 5 页各抄、roleLabel
// 权限/人员两页近重复——一处定义，各页导入）
import { ROLE_LABEL } from './nav'
import type { RoleDef } from './api'

/** 案例/品牌阶段 → 中文（与后端 STAGE_FLOW 同域词表） */
export const STAGE_LABEL: Record<string, string> = {
  proposal: '提案中', live: '投放中', closed: '已结案',
  lost: '未成单', terminated: '已终止',
}

/** 角色 → 显示名（系统角色用 nav 词表，自定义角色用库内 label） */
export const roleLabel = (r: Pick<RoleDef, 'name' | 'label'>) => ROLE_LABEL[r.name] ?? r.label
