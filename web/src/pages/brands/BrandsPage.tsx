// 客户页列表（spec §5）：品牌卡 + 案例阶段分布 + 消耗——ae 只见对接品牌、client 只见自己
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { listBrands, type BrandListItem } from '@/lib/api'

const yuan = (v?: string | null) =>
  v == null ? '—' : `¥${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`

export function BrandsPage() {
  const [q, setQ] = useState('')
  const [items, setItems] = useState<BrandListItem[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (query: string) => {
    setBusy(true); setError('')
    try {
      setItems((await listBrands(query)).items)
    } catch (e) {
      setError(`${e}`)
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => { void load('') }, [load])

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-bold">客户</h2>
        <span className="text-xs text-muted-foreground">
          品牌子图 + 健康度——你看到的品牌集合随角色锚点变化
        </span>
        <div className="ml-auto flex gap-2">
          <Input className="w-48" placeholder="品牌名" value={q}
                 onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => e.key === 'Enter' && load(q)} />
          <Button size="sm" disabled={busy} onClick={() => load(q)}>筛选</Button>
        </div>
      </div>

      {error && <div className="rounded-md bg-red-50 p-3 text-xs text-red-600">{error}</div>}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {items.map((b) => (
          <Link key={b.id} to={`/brands/${encodeURIComponent(b.id)}`}
                className="block rounded-lg border p-4 transition-colors hover:border-primary/50 hover:bg-muted/30">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold">{b.name}</span>
              <Badge variant="outline">{b.category}</Badge>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
              <Badge variant="secondary">案例 {b.cases_total}</Badge>
              {b.cases_live > 0 && <Badge className="bg-emerald-100 text-emerald-700">投放中 {b.cases_live}</Badge>}
              {b.cases_lost > 0 && <Badge variant="destructive">未成单 {b.cases_lost}</Badge>}
            </div>
            <div className="mt-3 flex items-baseline gap-5 text-xs text-muted-foreground">
              <span>消耗 <b className="font-mono text-foreground">{yuan(b.stats?.cost)}</b></span>
              <span>CTR <b className="font-mono text-foreground">
                {b.stats?.ctr != null ? `${(Number(b.stats.ctr) * 100).toFixed(2)}%` : '—'}</b></span>
              <span>{b.stats?.days ?? 0} 天</span>
            </div>
          </Link>
        ))}
        {!items.length && !busy && (
          <div className="col-span-full rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
            没有可见品牌（角色锚点内无品牌）
          </div>
        )}
      </div>
    </div>
  )
}
