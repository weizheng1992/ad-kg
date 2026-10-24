// 客户详情（spec §5 + §13.3 互链）：商品卡 + 案例合作史（含拒因与指标，链接案例详情）+ 汇总统计
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { getBrand, listCases, type BrandDetail, type CaseListItem } from '@/lib/api'

const STAGE_LABEL: Record<string, string> = {
  proposal: '提案中', live: '投放中', closed: '已结案',
  lost: '未成单', terminated: '已终止',
}
const yuan = (v?: string | null) =>
  v == null ? '—' : `¥${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`

export function BrandDetailPage() {
  const { id } = useParams()
  const [d, setD] = useState<BrandDetail | null>(null)
  const [caseStats, setCaseStats] = useState<Record<string, CaseListItem>>({})
  const [error, setError] = useState('')

  useEffect(() => {
    setD(null); setError(''); setCaseStats({})
    if (!id) return
    getBrand(decodeURIComponent(id)).then(setD).catch((e) => setError(`${e}`))
    // 案例行指标（spec §13.3）：从案例列表端点取同品牌案例的批量统计
    listCases({ brand: decodeURIComponent(id), size: 100 })
      .then((r) => setCaseStats(Object.fromEntries(r.items.map((c) => [c.id, c]))))
      .catch(() => setCaseStats({}))
  }, [id])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  if (!d) return <div className="p-6 text-sm text-muted-foreground">加载中…</div>

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex items-center gap-3">
        <Link to="/brands" className="text-xs text-primary hover:underline">← 客户</Link>
        <h2 className="text-base font-bold">{d.brand.name}</h2>
        <Badge variant="outline">{d.brand.category}</Badge>
        {d.stats && (
          <span className="ml-auto flex gap-4 text-xs text-muted-foreground">
            <span>消耗 <b className="font-mono text-foreground">{yuan(d.stats.cost)}</b></span>
            <span>CTR <b className="font-mono text-foreground">
              {d.stats.ctr != null ? `${(Number(d.stats.ctr) * 100).toFixed(2)}%` : '—'}</b></span>
            <span>{d.stats.days ?? 0} 天</span>
          </span>
        )}
      </div>

      {d.products.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">商品（详情 · 使用人群 · 客单价）</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {d.products.map((p) => (
              <div key={p.id} className="rounded-lg border p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{p.name}</span>
                  {p.price && <span className="font-mono text-sm">¥{p.price}</span>}
                </div>
                <div className="mt-1.5 space-y-0.5 text-xs text-muted-foreground">
                  {p.spec && <div>{p.spec}</div>}
                  {p.detail && <div>{p.detail}</div>}
                  <div className="flex gap-3">
                    {p.target_age && <span>使用人群 {p.target_age} 岁</span>}
                    {p.platform && <span>{p.platform === '电商' ? '电商 SKU' : p.platform}</span>}
                  </div>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">
            案例合作史{d.cases.some((c) => c.lost_reason) && '（未成单带拒因）'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 font-medium">案例</th>
                <th className="py-2 font-medium">阶段</th>
                <th className="py-2 font-medium">消耗</th>
                <th className="py-2 font-medium">CTR</th>
                <th className="py-2 font-medium">CVR</th>
                <th className="py-2 font-medium">未成单 / 终止原因</th>
              </tr>
            </thead>
            <tbody>
              {d.cases.map((c) => {
                const st = caseStats[c.id]?.stats
                return (
                  <tr key={c.id} className="border-b last:border-0">
                    <td className="py-2">
                      <Link to={`/cases/${encodeURIComponent(c.id)}`} className="text-primary hover:underline">
                        {c.name}
                      </Link>
                    </td>
                    <td className="py-2"><Badge variant="outline">{STAGE_LABEL[c.stage] ?? c.stage}</Badge></td>
                    <td className="py-2 font-mono">
                      {st?.cost != null ? `¥${Number(st.cost).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}` : '—'}
                    </td>
                    <td className="py-2 font-mono">
                      {st?.ctr != null ? `${(Number(st.ctr) * 100).toFixed(2)}%` : '—'}
                    </td>
                    <td className="py-2 font-mono">
                      {st?.cvr != null ? `${(Number(st.cvr) * 100).toFixed(2)}%` : '—'}
                    </td>
                    <td className="py-2 text-muted-foreground">{c.lost_reason || '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}
