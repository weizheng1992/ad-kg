// 达人库（spec §3）：筛选 + 列表 + 分页——平台级主数据，角色过类白名单即可见
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { listCreators, type CreatorItem, type CreatorListQuery } from '@/lib/api'

const wan = (n: number) => n >= 10000 ? `${(n / 10000).toFixed(1)}万` : `${n}`
const PLATFORM_OPT = { all: '全部平台', douyin: '抖音', xhs: '小红书' } as const

export function CreatorsPage() {
  const [q, setQ] = useState('')
  const [platform, setPlatform] = useState<string>('all')
  const [niche, setNiche] = useState('')
  const [items, setItems] = useState<CreatorItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const size = 12

  const load = useCallback(async (p: number) => {
    setBusy(true); setError('')
    try {
      const query: CreatorListQuery = { page: p, size, q: q.trim() }
      if (platform !== 'all') query.platform = platform
      if (niche.trim()) query.niche = niche.trim()
      const r = await listCreators(query)
      setItems(r.items); setTotal(r.total); setPage(p)
    } catch (e) {
      setError(`${e}`)
    } finally {
      setBusy(false)
    }
  }, [q, platform, niche])

  useEffect(() => { void load(1) }, [load])

  const pages = Math.max(1, Math.ceil(total / size))
  return (
    <div className="space-y-4 p-6">
      <div className="flex items-baseline gap-3">
        <h2 className="text-base font-bold">达人库</h2>
        <span className="text-xs text-muted-foreground">
          平台级主数据——达人档案、视频方向、报价与带货（字段设计参照界面原型 01–04）
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-56" placeholder="达人名 / 视频方向" value={q}
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && load(1)} />
        <Select value={platform} onValueChange={setPlatform}>
          <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
          <SelectContent>
            {Object.entries(PLATFORM_OPT).map(([v, l]) => (
              <SelectItem key={v} value={v}>{l}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input className="w-36" placeholder="视频方向（如 露营）" value={niche}
               onChange={(e) => setNiche(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && load(1)} />
        <Button size="sm" disabled={busy} onClick={() => load(1)}>筛选</Button>
        <span className="ml-auto text-xs text-muted-foreground">共 {total} 位达人</span>
      </div>

      {error && <div className="rounded-md bg-red-50 p-3 text-xs text-red-600">{error}</div>}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              {['达人', '平台', '视频方向', '粉丝', '20s 报价', '30天 GMV', '城市', '评分', '合作单'].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.id} className="border-b last:border-0 hover:bg-muted/30">
                <td className="px-3 py-2.5">
                  <Link to={`/creators/${encodeURIComponent(c.id)}`} className="font-medium text-primary hover:underline">
                    {c.name}
                  </Link>
                </td>
                <td className="px-3 py-2.5">{c.platform === 'douyin' ? '抖音' : '小红书'}</td>
                <td className="px-3 py-2.5">
                  {c.niches.map((n) => <Badge key={n} variant="outline" className="mr-1 font-normal">{n}</Badge>)}
                </td>
                <td className="px-3 py-2.5 font-mono">{wan(c.followers)}</td>
                <td className="px-3 py-2.5 font-mono">¥{c.quote_20s.toLocaleString('zh-CN')}</td>
                <td className="px-3 py-2.5 font-mono">¥{c.gmv_30d.toLocaleString('zh-CN')}</td>
                <td className="px-3 py-2.5">{c.city}</td>
                <td className="px-3 py-2.5 font-mono">{c.rating}</td>
                <td className="px-3 py-2.5 font-mono">{c.cases}</td>
              </tr>
            ))}
            {!items.length && !busy && (
              <tr><td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">没有匹配的达人</td></tr>
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
