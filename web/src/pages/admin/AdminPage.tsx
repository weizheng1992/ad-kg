// 管理后台（spec §7 + §14 + §19）：审计流水（筛选）/ 人审队列——只读；
// 权限矩阵已迁「权限管理」页折叠区（spec §19 两平面分离）
import { useCallback, useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ROLE_LABEL } from '@/lib/nav'
import { useCan } from '@/lib/session'
import { getAuditLog, getReviewQueue, resolveReviewQueue,
         type AuditRow, type ReviewQueueItem } from '@/lib/api'

const VERDICT_COLOR: Record<string, string> = {
  allow: 'bg-emerald-100 text-emerald-700', deny: 'bg-red-100 text-red-700',
  filtered: 'bg-amber-100 text-amber-700', info: 'bg-muted text-muted-foreground',
}

function AuditTab({ rows, total, page, size, onPage, filters, setFilters, reload }: {
  rows: AuditRow[]; total: number; page: number; size: number
  onPage: (p: number) => void
  filters: { action: string; verdict: string; by_role: string; q: string }
  setFilters: (f: { action: string; verdict: string; by_role: string; q: string }) => void
  reload: () => void
}) {
  const pages = Math.max(1, Math.ceil(total / size))
  const set = (k: keyof typeof filters) => (v: string) => { setFilters({ ...filters, [k]: v }) }
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
          审计流水
          <span className="text-xs font-normal text-muted-foreground">
            共 {total} 条（只追加，§八）——第 {page} / {pages} 页
          </span>
          <div className="ml-auto flex flex-wrap gap-1.5">
            <Input className="h-7 w-32 text-xs" placeholder="动作（login…）" value={filters.action}
                   onChange={(e) => set('action')(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && reload()} />
            <Input className="h-7 w-28 text-xs" placeholder="对象包含" value={filters.q}
                   onChange={(e) => set('q')(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && reload()} />
            <select className="h-7 rounded-md border bg-background px-2 text-xs"
                    value={filters.verdict} onChange={(e) => set('verdict')(e.target.value)}>
              <option value="">全部结果</option>
              {['allow', 'deny', 'filtered', 'info'].map((v) => <option key={v}>{v}</option>)}
            </select>
            <select className="h-7 rounded-md border bg-background px-2 text-xs"
                    value={filters.by_role} onChange={(e) => set('by_role')(e.target.value)}>
              <option value="">全部角色</option>
              {Object.entries(ROLE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <Button variant="outline" size="sm" onClick={reload}>筛选</Button>
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>上一页</Button>
            <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页</Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/40 text-left">
              {['时间', '身份', '动作', '对象', '结果'].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b last:border-0">
                <td className="px-3 py-2 whitespace-nowrap font-mono">{r.ts.slice(0, 19)}</td>
                <td className="px-3 py-2 whitespace-nowrap">
                  {r.user_id ?? '—'}
                  <Badge variant="outline" className="ml-1 font-normal">{r.role}</Badge>
                </td>
                <td className="px-3 py-2 font-mono">{r.action}</td>
                <td className="max-w-[22rem] truncate px-3 py-2" title={r.target ?? ''}>{r.target ?? '—'}</td>
                <td className="px-3 py-2">
                  <Badge className={VERDICT_COLOR[r.verdict ?? ''] ?? ''}>{r.verdict ?? '—'}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}


/** 人审队列（spec §14/§15）：kind 计数筛选 + 处置（approve 落图进源 / reject 维持） */
function ReviewTab({ data, kind, setKind, reload }: {
  data: { items: ReviewQueueItem[]; kinds: Record<string, number> } | null
  kind: string; setKind: (k: string) => void; reload: () => void
}) {
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const canResolve = useCan('review_resolve')   // 按钮显隐与后端 review_resolve 门同源（§18.5）
  const KIND_LABEL: Record<string, string> = {
    conflict: '权威冲突', low_confidence: '低置信', unmatched: '对齐失败', reconcile: '对账差异',
  }
  if (!data) return <div className="p-4 text-sm text-muted-foreground">加载中…</div>
  const resolve = async (id: string, decision: 'approved' | 'rejected') => {
    const note = decision === 'approved' ? window.prompt('处置备注（可空）') ?? '' : ''
    setBusy(id); setMsg('')
    try {
      const r = await resolveReviewQueue(id, decision, note)
      setMsg(`✅ ${decision === 'approved' ? '通过' : '驳回'}${r.applied ? '（进源数据已落图）' : ''}`)
      reload()
    } catch (e) {
      setMsg(`❌ ${e}`)
    } finally {
      setBusy('')
    }
  }
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <button onClick={() => setKind('')}
                  className={`rounded-md px-2.5 py-1 ${!kind ? 'bg-primary text-primary-foreground' : 'border'}`}>
            全部
          </button>
          {Object.entries(data.kinds).map(([k, n]) => (
            <button key={k} onClick={() => setKind(kind === k ? '' : k)}
                    className={`rounded-md px-2.5 py-1 ${kind === k ? 'bg-primary text-primary-foreground' : 'border'}`}>
              {KIND_LABEL[k] ?? k} {n}
            </button>
          ))}
          <span className="ml-2 text-muted-foreground">通过=采纳（冲突类落进源数据）· 驳回=维持现状</span>
          {msg && <span>{msg}</span>}
        </div>
        {data.items.length ? (
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b bg-muted/40 text-left">
                {['时间', '类型', '实体', '内容', '状态', '处置'].map((h) => (
                  <th key={h} className="px-3 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.id} className="border-b align-top last:border-0">
                  <td className="px-3 py-2 whitespace-nowrap font-mono">{r.created_at.slice(0, 19)}</td>
                  <td className="px-3 py-2"><Badge variant="outline">{KIND_LABEL[r.kind] ?? r.kind}</Badge></td>
                  <td className="px-3 py-2 font-mono">{r.payload?.entity ?? '—'}</td>
                  <td className="max-w-[28rem] px-3 py-2 text-muted-foreground">
                    {r.payload?.incoming_source && (
                      <div>进源 {String(r.payload.incoming_source)}（权威 {r.payload.incoming_authority ?? '—'}）
                        vs 库内权威 {r.payload.existing_authority ?? '——高者保留，待人审合并'}</div>
                    )}
                    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all font-mono">
                      {JSON.stringify(r.payload, null, 0).slice(0, 260)}
                    </pre>
                  </td>
                  <td className="px-3 py-2"><Badge variant="secondary">{r.status}</Badge></td>
                  <td className="px-3 py-2">
                    {canResolve ? (
                      <div className="flex gap-1">
                        <Button variant="outline" size="sm" className="h-6 px-2 text-[11px]"
                                disabled={busy === r.id}
                                onClick={() => void resolve(r.id, 'approved')}>通过</Button>
                        <Button variant="outline" size="sm" className="h-6 px-2 text-[11px]"
                                disabled={busy === r.id}
                                onClick={() => void resolve(r.id, 'rejected')}>驳回</Button>
                      </div>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">无处置权</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="py-6 text-center text-sm text-muted-foreground">该筛选下队列为空</div>
        )}
      </CardContent>
    </Card>
  )
}

export function AdminPage() {
  const [audit, setAudit] = useState<{ rows: AuditRow[]; total: number; page: number } | null>(null)
  const [auditFilters, setAuditFilters] = useState({ action: '', verdict: '', by_role: '', q: '' })
  const [review, setReview] = useState<{ items: ReviewQueueItem[]
                                         kinds: Record<string, number> } | null>(null)
  const [reviewKind, setReviewKind] = useState('')
  const [error, setError] = useState('')

  const loadAudit = useCallback(async (p: number, filters = auditFilters) => {
    try {
      const f = Object.fromEntries(Object.entries(filters).filter(([, v]) => !!v))
      const r = await getAuditLog(p, 30, f)
      setAudit({ rows: r.items, total: r.total, page: r.page })
    } catch (e) {
      setError(`${e}`)
    }
  }, [auditFilters])

  const loadReview = useCallback(async (k: string) => {
    getReviewQueue('open', k).then(setReview).catch((e) => setError(`${e}`))
  }, [])

  useEffect(() => {
    void loadAudit(1)
    void loadReview('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  return (
    <div className="space-y-4 p-6">
      <div className="flex items-baseline gap-3">
        <h2 className="text-base font-bold">管理后台</h2>
        <span className="text-xs text-muted-foreground">
          审计流水（可筛）+ 人审队列（只读）；权限矩阵在
          <a href="/permissions" className="mx-1 text-primary hover:underline">权限管理</a>
          页折叠区（spec §19 迁出）
        </span>
      </div>
      <Tabs defaultValue="audit">
        <TabsList>
          <TabsTrigger value="audit">审计流水</TabsTrigger>
          <TabsTrigger value="review">人审队列</TabsTrigger>
        </TabsList>
        <TabsContent value="audit">
          {audit && (
            <AuditTab rows={audit.rows} total={audit.total} page={audit.page}
                      size={30} onPage={(p) => loadAudit(p)}
                      filters={auditFilters} setFilters={setAuditFilters}
                      reload={() => loadAudit(1, auditFilters)} />
          )}
        </TabsContent>
        <TabsContent value="review">
          <ReviewTab data={review} kind={reviewKind}
                     setKind={(k) => { setReviewKind(k); void loadReview(k) }}
                     reload={() => void loadReview(reviewKind)} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
