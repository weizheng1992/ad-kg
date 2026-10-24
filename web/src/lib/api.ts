// AdKG API 客户端（README §9.7：由 OpenAPI 约定的薄封装；身份走同源会话 cookie，spec §2）
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

export async function ask(question: string): Promise<AskResponse> {
  const r = await fetch('/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

export async function graphEntity(id: string): Promise<GraphResponse> {
  const p = new URLSearchParams({ id })
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

export async function caseCommit(draft: CaseDraft): Promise<CommitResult> {
  const r = await fetch('/ingest/case-commit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft }),
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
  /** 来源四梯度（spec §13.1）：种子/平台抓取/表格导入/手工录入 */
  source?: string
  fetched_at?: string | null
}

export interface CreatorDetail {
  creator: CreatorItem
  collabs: { id: string; name: string; stage: string; lost_reason?: string | null
             cost?: string | null; cpa?: string | null }[]
  collabs_filtered: number
  products: { id: string; name: string; price?: string | null; spec?: string | null
              target_age?: string | null }[]
  /** 合作案例维度汇总投放统计（spec §3；口径同 /graph stats，无可见案例为 null） */
  stats?: { cost?: string | null; ctr?: string | null; cvr?: string | null
            cpa?: string | null; days?: number; platforms?: string | null } | null
  provenance?: { source?: string; source_type?: string; source_id?: string
                 fetched_at?: string | null; authority?: number | null }
  /** 报价历史（spec §15）：种子轨迹 + 入库口快照，旧→新 */
  quote_history?: { date: string; quote_20s: number; source_type: string }[]
}

export interface CreatorListQuery {
  q?: string; platform?: string; niche?: string; source?: string
  min_followers?: number; max_quote?: number
  sort?: 'followers' | 'gmv' | 'quote'
  page?: number; size?: number
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

/** 达人录入（spec §13.1：conversation/20 低权威，平台抓取可覆盖） */
export async function createCreator(payload: Record<string, unknown>): Promise<
  { outcome: 'created' | 'merged' | 'conflict'; creator_id: string }> {
  const r = await fetch('/creators', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

/** CSV 批量导入（spec §13.1：official_doc/60；列同 creators.csv 模板） */
export async function importCreators(file: File): Promise<
  { created: number; merged: number; conflicts: number
    errors: { line: number; error: string }[]; total: number }> {
  const r = await fetch('/creators/import', { method: 'POST', body: (() => {
    const fd = new FormData(); fd.append('file', file); return fd
  })() })
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

// ---------- 案例全生命周期（spec §13.2） ----------

export interface CaseStatsLite {
  cost?: string | null; ctr?: string | null; cvr?: string | null
  cpa?: string | null; days?: number; platforms?: string | null
}

export interface CaseListItem {
  id: string
  name: string
  stage: string
  brand_id: string
  brand_name: string
  owners: string[]
  settlement_status?: string
  bd_budget?: string
  gross_margin?: string
  lost_reason?: string | null
  terminate_reason?: string | null
  stats: CaseStatsLite | null
}

export interface CaseDetail {
  case: { id: string; name: string; stage: string; bd_budget?: string
          gross_margin?: string; settlement_status?: string
          lost_reason?: string | null; terminate_reason?: string | null }
  brand: { id: string; name: string } | null
  product: { id: string; name: string; spec?: string | null; price?: string | null
             target_age?: string | null } | null
  owners: { id: string; name: string }[]
  campaigns: { id: string; name: string; status: string }[]
  creatives: { id: string; name: string
               metrics: ({ creative_id: string; platforms?: string | null } & CaseStatsLite) | null }[]
  creators: { id: string; name: string; niches: string[]; followers: number
              quote_20s: number }[]
  stats: CaseStatsLite | null
  docs: { doc_id: string; chunk_index: number; text: string }[]
  timeline: { ts: string; role: string; action: string; verdict: string | null
              reason: string | null }[]
  stage_flow: { main: string[]; branch: Record<string, string>; current: string }
  /** 状态变更权限（spec §15）：按 permissions.yaml update_stage 动态下发 */
  can_update_stage?: boolean
}

export async function listCases(params: { q?: string; stage?: string; brand?: string
                                           page?: number; size?: number } = {}): Promise<
  { items: CaseListItem[]; total: number; page: number; size: number }> {
  const p = new URLSearchParams(
    Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
      .map(([k, v]) => [k, String(v)])))
  const r = await fetch(`/cases?${p}`)
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

export async function getCase(id: string): Promise<CaseDetail> {
  const r = await fetch(`/cases/${encodeURIComponent(id)}`)
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

/** 状态变更（spec §15）：走 ActionChecker 状态机裁决，拒绝 409 */
export async function updateCaseStage(id: string, toStage: string, reason: string): Promise<
  { ok: boolean; case_id: string; stage: string }> {
  const r = await fetch(`/cases/${encodeURIComponent(id)}/stage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ to_stage: toStage, reason }),
  })
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
  /** 近 30 天消耗（spec §5 健康度窗口） */
  cost_30d?: string | null
}

export interface BrandDetail {
  brand: { id: string; name: string; category: string }
  products: { id: string; name: string; category?: string; spec?: string | null
              detail?: string | null; price?: string | null; target_age?: string | null
              platform?: string | null }[]
  cases: { id: string; name: string; stage: string; lost_reason?: string | null
           settlement_status?: string | null }[]
  stats: BrandListItem['stats']
  owners?: { id: string; name: string }[]
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
export const getAuditLog = (page = 1, size = 30, filters: {
  action?: string; verdict?: string; by_role?: string; q?: string } = {}) => {
  const p = new URLSearchParams({ page: String(page), size: String(size) })
  Object.entries(filters).forEach(([k, v]) => { if (v) p.set(k, v) })
  return _get<{ items: AuditRow[]; total: number; page: number; size: number }>(`/admin/audit?${p}`)
}
export interface ReviewQueueItem {
  id: string; kind: string; status: string; created_at: string
  payload: { entity?: string; incoming_source?: string; incoming_authority?: number
             existing_authority?: number; [k: string]: unknown }
}
export const getReviewQueue = (status = 'open', kind = '') => {
  const p = new URLSearchParams({ status })
  if (kind) p.set('kind', kind)
  return _get<{ items: ReviewQueueItem[]; total: number
                kinds: Record<string, number> }>(`/admin/review-queue?${p}`)
}

/** 人审处置（spec §15）：approve 对 conflict 落图进源数据，reject 维持现状 */
export async function resolveReviewQueue(id: string, decision: 'approved' | 'rejected',
                                         note = ''): Promise<
  { ok: boolean; decision: string; applied: boolean }> {
  const r = await fetch(`/admin/review-queue/${id}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, note }),
  })
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}

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
  messages: { role: string; content: string }[],
  onEvent: (ev: AgentEvent) => void,
): Promise<void> {
  const r = await fetch('/agent/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
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
  messages: { role: string; content: string }[],
): Promise<AgentChatResult> {
  const r = await fetch('/agent/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  })
  if (!r.ok) throw new Error(`${r.status} ${await errorDetail(r)}`)
  return r.json()
}
