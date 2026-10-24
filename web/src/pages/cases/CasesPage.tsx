// 案例列表（spec §13.2）：阶段/品牌筛选 + 批量指标（汇总比）——行点击进详情；
// 支持 ?stage= 进场筛选（看板阶段分布互链，spec §14）
import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { listCases, type CaseListItem } from '@/lib/api'

export const STAGE_LABEL: Record<string, string> = {
  proposal: '提案中', live: '投放中', closed: '已结案',
  lost: '未成单', terminated: '已终止',
}
const yuan = (v?: string | number | null) =>
  v == null || v === '' ? '—' : `¥${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
const pct = (v?: string | null) =>
  v == null || v === '' ? '—' : `${(Number(v) * 100).toFixed(2)}%`

export function CasesPage() {
  const [params] = useSearchParams()
  const [q, setQ] = useState('')
  const [stage, setStage] = useState<string>(params.get('stage') ?? 'all')
  const [brand, setBrand] = useState('')
  const [items, setItems] = useState<CaseListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const size = 15

  const load = useCallback(async (p: number) => {
    setBusy(true); setError('')
    try {
      const r = await listCases({
        page: p, size, q: q.trim() || undefined,
        stage: stage === 'all' ? undefined : stage,
        brand: brand.trim() || undefined,
      })
      setItems(r.items); setTotal(r.total); setPage(p)
    } catch (e) {
      setError(`${e}`)
    } finally {
      setBusy(false)
    }
  }, [q, stage, brand])

  useEffect(() => { void load(1) }, [load])

  const pages = Math.max(1, Math.ceil(total / size))
  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-bold">案例</h2>
        <span className="text-xs text-muted-foreground">
          全生命周期视图入口——指标为汇总比口径，点击行进详情（内容 / 流转 / 收益）
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-52" placeholder="案例名" value={q}
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && load(1)} />
        <Select value={stage} onValueChange={setStage}>
          <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部阶段</SelectItem>
            {Object.entries(STAGE_LABEL).map(([v, l]) => (
              <SelectItem key={v} value={v}>{l}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input className="w-40" placeholder="品牌（名或 ID）" value={brand}
               onChange={(e) => setBrand(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && load(1)} />
        <Button size="sm" disabled={busy} onClick={() => load(1)}>筛选</Button>
        <span className="ml-auto text-xs text-muted-foreground">共 {total} 个案例</span>
      </div>

      {error && <div className="rounded-md bg-red-50 p-3 text-xs text-red-600">{error}</div>}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              {['案例', '品牌', '阶段', '负责人', '消耗', 'CTR', 'CVR', 'CPA', '结算'].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id} className="border-b last:border-0 hover:bg-muted/30">
                <td className="max-w-64 truncate px-3 py-2.5">
                  <Link to={`/cases/${encodeURIComponent(c.id)}`} className="font-medium text-primary hover:underline">
                    {c.name}
                  </Link>
                  {c.stage === 'lost' && c.lost_reason && (
                    <span className="ml-2 text-[11px] text-muted-foreground" title={c.lost_reason}>
                      （{c.lost_reason}）
                    </span>
                  )}
                </td>
                <td className="px-3 py-2.5">{c.brand_name}</td>
                <td className="px-3 py-2.5"><Badge variant="outline">{STAGE_LABEL[c.stage] ?? c.stage}</Badge></td>
                <td className="px-3 py-2.5 text-muted-foreground">{c.owners.join('、') || '—'}</td>
                <td className="px-3 py-2.5 font-mono">{yuan(c.stats?.cost)}</td>
                <td className="px-3 py-2.5 font-mono">{pct(c.stats?.ctr)}</td>
                <td className="px-3 py-2.5 font-mono">{pct(c.stats?.cvr)}</td>
                <td className="px-3 py-2.5 font-mono">
                  {c.stats?.cpa != null ? `¥${Number(c.stats.cpa).toFixed(2)}` : '—'}
                </td>
                <td className="px-3 py-2.5">
                  {c.settlement_status
                    ? <Badge variant={c.settlement_status === 'paid' ? 'secondary' : 'destructive'}
                             className={c.settlement_status === 'paid' ? 'bg-emerald-100 text-emerald-700' : ''}>
                        {c.settlement_status === 'paid' ? '已结算' : '未结算'}
                      </Badge>
                    : '—'}
                </td>
              </tr>
            ))}
            {!items.length && !busy && (
              <tr><td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">没有可见案例</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-end gap-2 text-xs text-muted-foreground">
        <Button variant="outline" size="sm" disabled={page <= 1 || busy} onClick={() => load(page - 1)}>上一页</Button>
        第 {page} / {pages} 页
        <Button variant="outline" size="sm" disabled={page >= pages || busy} onClick={() => load(page + 1)}>下一页</Button>
      </div>
    </div>
  )
}
