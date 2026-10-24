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

// ---------- 认证（spec §2：服务端会话 cookie；登录壳不再是前端账号表） ----------

export interface Me { username: string; display_name: string; role: string; person: string | null }

export async function login(username: string, password: string): Promise<Me> {
  const r = await fetch('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

export async function fetchMe(): Promise<Me | null> {
  const r = await fetch('/auth/me')
  return r.ok ? r.json() : null
}

export async function logout(): Promise<void> {
  await fetch('/auth/logout', { method: 'POST' })
}

/** 错误响应 detail：500 未捕获异常时 body 是纯文本（非 JSON），先 text 再安全 parse */
async function errorDetail(r: Response): Promise<string> {
  const t = await r.text()
  try {
    return (JSON.parse(t) as { detail?: string }).detail ?? t.slice(0, 200)
  } catch {
    return t.slice(0, 200)
  }
}

export async function ask(question: string, role: string, user: string): Promise<AskResponse> {
  const r = await fetch('/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, role, user }),
  })
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

export async function graphEntity(id: string, role: string, user: string): Promise<GraphResponse> {
  const p = new URLSearchParams({ id, role, user })
  const r = await fetch(`/graph/entity?${p}`)
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

// ---------- 案例草稿（agent 产出物 → /ingest/case-commit 确认入图，README §9.4） ----------

export interface DraftNode {
  id: string
  name: string
  props: Record<string, unknown>
  existing: boolean
  same_doc?: boolean
}

export interface CaseDraft {
  doc_id: string
  case: DraftNode | null
  brand: DraftNode | null
  products: DraftNode[]
  persons: { id: string; name: string; aligned: boolean }[]
  relations: { source: string; predicate: string; target: string }[]
  warnings: string[]
}

export interface CommitResult {
  status: string
  case_id: string
  entities: number
  relations: number
  written: { id: string; name?: string }[]
  warnings: string[]
}

export async function caseCommit(draft: CaseDraft, persona: Persona): Promise<CommitResult> {
  const r = await fetch('/ingest/case-commit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft, role: persona.role, user: persona.user }),
  })
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

// ---------- 素材草稿（agent 产出物形态，README §9.4） ----------

export interface CreativeDraftItem {
  title: string
  format: string
  platform: string
  hook_3s: string
  script: string | string[]          // LLM 可能返回逐行数组
  copy: string | string[]
  based_on?: string[]
}

// ---------- 达人库（spec §3：Creator 平台级主数据；合作历史随行权限过滤） ----------

export interface CreatorItem {
  id: string
  name: string
  platform: string
  niches: string[]
  followers: number
  quote_20s: number
  quote_image: number
  gmv_30d: number
  city: string
  rating: number
  cases: number
}

export interface CreatorDetail {
  creator: CreatorItem
  collabs: { id: string; name: string; stage: string; lost_reason?: string | null }[]
  collabs_filtered: number
  products: { id: string; name: string; price?: string | null; spec?: string | null
              target_age?: string | null }[]
}

export interface CreatorListQuery {
  q?: string; platform?: string; niche?: string
  min_followers?: number; max_quote?: number; page?: number; size?: number
}

export async function listCreators(params: CreatorListQuery): Promise<
  { items: CreatorItem[]; total: number; page: number; size: number }> {
  const p = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
      .map(([k, v]) => [k, String(v)])))
  const r = await fetch(`/creators?${p}`)
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

export async function getCreator(id: string): Promise<CreatorDetail> {
  const r = await fetch(`/creators/${encodeURIComponent(id)}`)
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

// ---------- 客户页（spec §5）：品牌列表 + 子图详情；client 锚点豁免类闸只见自己 ----------

export interface BrandListItem {
  id: string
  name: string
  category: string
  cases_total: number
  cases_live: number
  cases_lost: number
  stats: { cost?: string | null; ctr?: string | null; cvr?: string | null; days?: number } | null
}

export interface BrandDetail {
  brand: { id: string; name: string; category: string }
  products: { id: string; name: string; category?: string; spec?: string | null
              detail?: string | null; price?: string | null; target_age?: string | null
              platform?: string | null }[]
  cases: { id: string; name: string; stage: string; lost_reason?: string | null
           settlement_status?: string | null }[]
  stats: BrandListItem['stats']
}

export async function listBrands(q = ''): Promise<{ items: BrandListItem[]; total: number }> {
  const p = new URLSearchParams()
  if (q.trim()) p.set('q', q.trim())
  const r = await fetch(`/brands?${p}`)
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

export async function getBrand(id: string): Promise<BrandDetail> {
  const r = await fetch(`/brands/${encodeURIComponent(id)}`)
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

// ---------- 财务结算（spec §5：角色门 management/finance） ----------

export interface SettlementItem {
  case_id: string
  case_name: string
  stage: string
  settlement_status: string
  bd_budget: string
  gross_margin?: string | null
  brand_id: string
  brand_name: string
  creator_count: number
  creator_cost: number
}

export async function listSettlements(params: { status?: string; brand?: string; stage?: string } = {}): Promise<
  { items: SettlementItem[]; total: number
    summary: { budget_total: number; creator_cost_total: number; paid: number; unbilled: number } }> {
  const p = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => !!v) as [string, string][]))
  const r = await fetch(`/settlements?${p}`)
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

// ---------- 数据看板（spec §5：汇总比口径 + 行谓词同一道闸） ----------

export interface StatsOverview {
  trend: { date: string; cost: string | null; conversions: string | null }[]
  platforms: { platform: string; cost: string | null; conversions: string | null }[]
  brands: { brand_id: string; cost: string | null; conversions: string | null; cases: number }[]
  stages: { stage: string; count: number }[]
  top_creators: { id: string; name: string; gmv_30d: number; cases: number }[] | null
  role: string
  days: number
}

export async function statsOverview(days = 90): Promise<StatsOverview> {
  const r = await fetch(`/stats/overview?days=${days}`)
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

// ---------- 管理后台（spec §7：只读三件套，management/admin） ----------

export interface PermissionMatrix {
  roles: Record<string, {
    classes: string[]; deny_properties: string[]; allow_properties: string[]
    metrics_deny: string[]; metrics_allow: string[]; actions: string[]
    external: boolean; row_filter: string
  }>
  global_classes: string[]
}

export interface AdminAccount {
  id: string; username: string; display_name: string; role: string
  person: string | null; disabled: boolean; created_at: string
}

export interface AuditRow {
  id: string; ts: string; user_id: string | null; role: string
  agent_id: string | null; action: string; target: string | null
  verdict: string | null; reason: string | null
}

async function _get<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

export const getPermissionMatrix = () => _get<PermissionMatrix>('/admin/permission-matrix')
export const getAdminAccounts = () => _get<{ items: AdminAccount[] }>('/admin/accounts')
export const getAuditLog = (page = 1, size = 30) =>
  _get<{ items: AuditRow[]; total: number; page: number; size: number }>(`/admin/audit?page=${page}&size=${size}`)

// ---------- Agent 对话（/agent/chat，README §9.7） ----------

export interface AgentTraceStep { tool: string; args: Record<string, unknown>; result: string }

export interface AgentChatResult {
  reply: string
  case_draft: CaseDraft | null
  creative_drafts: CreativeDraftItem[] | null
  trace: AgentTraceStep[]
  /** 案例确认入图的角色门（服务端下发，前端不硬抄角色表） */
  can_commit_case?: boolean
}

// SSE 事件（spec §6 契约：thought / tool_start / tool_step / tool_result / reply / draft / done / error）
export type AgentEvent =
  | { type: 'thought'; text: string }
  | { type: 'tool_start'; tool: string; args: Record<string, unknown> }
  | { type: 'tool_step'; tool: string; step: number; desc: string; screenshot?: string | null }
  | { type: 'tool_result'; tool: string; result: string }
  | { type: 'reply'; text: string }
  | { type: 'draft'; case_draft: CaseDraft | null; creative_drafts: CreativeDraftItem[] | null }
  | { type: 'done'; turns: number; can_commit_case: boolean; has_result: boolean }
  | { type: 'error'; detail: string }

/** POST + ReadableStream 解析 SSE（EventSource 不支持 POST，spec §6） */
export async function agentChatStream(
  messages: { role: string; content: string }[], persona: Persona,
  onEvent: (ev: AgentEvent) => void,
): Promise<void> {
  const r = await fetch('/agent/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, role: persona.role, user: persona.user }),
  })
  if (!r.ok || !r.body) throw new Error(`${r.status} ${await errorDetail(r)}`)
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    for (const part of parts) {
      const line = part.split('\n').find((l) => l.startsWith('data: '))
      if (line) onEvent(JSON.parse(line.slice(6)) as AgentEvent)
    }
  }
}

export async function agentChat(
  messages: { role: string; content: string }[], persona: Persona,
): Promise<AgentChatResult> {
  const r = await fetch('/agent/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, role: persona.role, user: persona.user }),
  })
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}
