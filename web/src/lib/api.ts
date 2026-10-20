// AdKG API 客户端（README §9.7：由 OpenAPI 约定的薄封装；dev 模式带 role/user）
export interface Persona { role: string; user: string }
export interface Evidence {
  type: string
  ref: string
  /** ref 的可读版（中文名 + 中文关系词）；ref 原串作溯源锚仍保留 */
  readable_ref?: string
  quote?: string
  rows?: Record<string, unknown>[]
  score?: number
  confidence?: number
  provenance?: { source_type?: string; source_id?: string; authority?: number }
}
export interface AskResponse {
  answer?: string
  intent?: string
  evidence?: Evidence[]
  routes_used?: { route: string; score: number }[]
  permission_applied?: boolean
  degraded?: string[]
  action?: string
  endpoint?: string
  reason?: string
}
export interface Neighbor {
  id: string
  class: string
  name?: string
  via: string
  confidence?: number
  provenance?: { source_type?: string; authority?: number }
}
/** Case/Product 实体的统计卡（汇总比口径，README §六；行权限过滤后越权对象为 null）。
 *  Product 额外带交易侧：orders/gmv 全量、purchase_rate 与投放 clicks 按天对齐（可 null） */
export interface CaseStats {
  cost: string
  ctr: string
  cvr: string
  cpa: string
  /** 覆盖平台（一案例常跨双平台投放，DISTINCT 聚合，如 "douyin,xhs"） */
  platforms?: string | null
  days: number
  first_day?: string
  last_day?: string
  orders?: string | null
  gmv?: string | null
  purchase_rate?: string | null
}
export interface GraphResponse {
  entity: { id: string; class: string; name?: string; stage?: string; authority?: number }
  neighbors: Neighbor[]
  filtered: number
  stats?: CaseStats | null
}

export const ROLES: { role: string; user: string; label: string }[] = [
  { role: 'management', user: 'Person:chen', label: '管理层·陈朔' },
  { role: 'optimizer', user: 'Person:li', label: '优化师·李昂' },
  { role: 'creative', user: 'Person:wang', label: '创意·王雪' },
  { role: 'client', user: 'Person:client_a', label: '客户方·顾佳(外部)' },
  { role: 'ae', user: 'Person:li', label: 'AE·李昂' },
  { role: 'finance', user: 'Person:zhou', label: '财务·周荃' },
]

export async function ask(question: string, role: string, user: string): Promise<AskResponse> {
  const r = await fetch('/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Adkg-Role': role },
    body: JSON.stringify({ question, role, user }),
  })
  if (!r.ok) throw new Error(`${r.status} ${(await r.json()).detail ?? ''}`)
  return r.json()
}

export async function graphEntity(id: string, role: string, user: string): Promise<GraphResponse> {
  const p = new URLSearchParams({ id, role, user })
  const r = await fetch(`/graph/entity?${p}`, { headers: { 'X-Adkg-Role': role } })
  if (!r.ok) throw new Error(`${r.status}`)
  return r.json()
}
