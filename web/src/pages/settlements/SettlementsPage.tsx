// 财务结算中心（spec §5）：Case 结算视图 + 达人合作成本（估）——仅 management/finance
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Card, CardContent } from '@/components/ui/card'
import { listSettlements, type SettlementItem } from '@/lib/api'

const STATUS_OPT = { all: '全部状态', paid: '已结算', unbilled: '未结算' } as const
const STAGE_LABEL: Record<string, string> = {
  proposal: '提案中', live: '投放中', closed: '已结案',
  lost: '未成单', terminated: '已终止',
}
const yuan = (n: number | string | null | undefined) =>
  n == null || n === '' ? '—' : `¥${Number(n).toLocaleString('zh-CN')}`

export function SettlementsPage() {
  const [status, setStatus] = useState('all')
  const [brand, setBrand] = useState('')
  const [items, setItems] = useState<SettlementItem[]>([])
  const [summary, setSummary] = useState<{ budget_total: number; creator_cost_total: number
                                           paid: number; unbilled: number } | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setBusy(true); setError('')
    try {
      const r = await listSettlements({
        status: status === 'all' ? undefined : status,
        brand: brand.trim() || undefined,
      })
      setItems(r.items); setSummary(r.summary)
    } catch (e) {
      setError(`${e}`)
    } finally {
      setBusy(false)
    }
  }, [status, brand])

  useEffect(() => { void load() }, [load])

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-bold">财务结算</h2>
        <span className="text-xs text-muted-foreground">
          案例预算 / 毛利 / 结算状态与达人合作成本（报价上界估计）——仅管理层与财务可见
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
          <SelectContent>
            {Object.entries(STATUS_OPT).map(([v, l]) => (
              <SelectItem key={v} value={v}>{l}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input className="w-44" placeholder="品牌（名或 ID）" value={brand}
               onChange={(e) => setBrand(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && load()} />
        <Button size="sm" disabled={busy} onClick={() => load()}>筛选</Button>
        {summary && (
          <div className="ml-auto flex gap-5 text-xs text-muted-foreground">
            <span>案例预算合计 <b className="font-mono text-foreground">{yuan(summary.budget_total)}</b></span>
            <span>达人成本（估） <b className="font-mono text-foreground">{yuan(summary.creator_cost_total)}</b></span>
            <span>已结算 <b className="text-foreground">{summary.paid}</b> / 未结算 <b className="text-foreground">{summary.unbilled}</b></span>
          </div>
        )}
      </div>

      {error && <div className="rounded-md bg-red-50 p-3 text-xs text-red-600">{error}</div>}

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                {['案例', '品牌', '阶段', 'BD 预算', '毛利率', '结算状态', '合作达人', '达人成本（估）'].map((h) => (
                  <th key={h} className="px-3 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.case_id} className="border-b last:border-0 hover:bg-muted/30">
                  <td className="px-3 py-2.5">
                    <Link to={`/graph?focus=${encodeURIComponent(s.case_id)}`} className="text-primary hover:underline">
                      {s.case_name}
                    </Link>
                  </td>
                  <td className="px-3 py-2.5">{s.brand_name}</td>
                  <td className="px-3 py-2.5">
                    <Badge variant="outline">{STAGE_LABEL[s.stage] ?? s.stage}</Badge>
                  </td>
                  <td className="px-3 py-2.5 font-mono">{yuan(s.bd_budget)}</td>
                  <td className="px-3 py-2.5 font-mono">
                    {s.gross_margin ? `${(Number(s.gross_margin) * 100).toFixed(0)}%` : '—'}
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge variant={s.settlement_status === 'paid' ? 'secondary' : 'destructive'}
                           className={s.settlement_status === 'paid' ? 'bg-emerald-100 text-emerald-700' : ''}>
                      {s.settlement_status === 'paid' ? '已结算' : '未结算'}
                    </Badge>
                  </td>
                  <td className="px-3 py-2.5 font-mono">{s.creator_count}</td>
                  <td className="px-3 py-2.5 font-mono">{yuan(s.creator_cost)}</td>
                </tr>
              ))}
              {!items.length && !busy && (
                <tr><td colSpan={8} className="px-3 py-8 text-center text-muted-foreground">没有匹配的结算记录</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}
