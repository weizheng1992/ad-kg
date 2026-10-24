// 达人库（spec §3 + §13.1 数据闭环）：筛选 + 列表 + 来源标识 + 录入表单 + CSV 导入
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Card, CardContent } from '@/components/ui/card'
import { createCreator, importCreators, listCreators,
         type CreatorItem, type CreatorListQuery } from '@/lib/api'

const wan = (n: number) => n >= 10000 ? `${(n / 10000).toFixed(1)}万` : `${n}`
const PLATFORM_OPT = { all: '全部平台', douyin: '抖音', xhs: '小红书' } as const
const SOURCE_OPT = { all: '全部来源', 种子: '种子', 平台抓取: '平台抓取',
                     表格导入: '表格导入', 手工录入: '手工录入' } as const

/** 录入表单（spec §13.1）：conversation/20 低权威——平台抓到更准数据可覆盖 */
function CreatorForm({ onDone }: { onDone: () => void }) {
  const [form, setForm] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const set = (k: string) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))

  const submit = async () => {
    setBusy(true); setMsg('')
    try {
      const r = await createCreator(form)
      setMsg(r.outcome === 'conflict'
        ? `⚠️ ${r.creator_id} 库内已有更高权威记录，未覆盖（冲突进人审队列）`
        : `✅ 已${r.outcome === 'created' ? '新建' : '更新'} ${r.creator_id}（来源：手工录入）`)
      setForm({})
      onDone()
    } catch (e) {
      setMsg(`❌ ${e}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardContent className="grid gap-3 py-4 sm:grid-cols-3">
        {([['name', '达人名 *'], ['platform', '平台 *（douyin/xhs）'], ['niches', '视频方向 *（| 分隔）'],
           ['followers', '粉丝'], ['quote_20s', '20s 报价（元）'], ['quote_image', '图文报价（元）'],
           ['gmv_30d', '30 天 GMV'], ['city', '城市'], ['rating', '评分（4-5）']] as const)
          .map(([k, label]) => (
            <div key={k} className="grid gap-1">
              <Label className="text-xs">{label}</Label>
              <Input value={form[k] ?? ''} onChange={set(k)} />
            </div>
          ))}
        <div className="flex items-end gap-2 sm:col-span-3">
          <Button size="sm" disabled={busy || !form.name || !form.platform || !form.niches}
                  onClick={submit}>{busy ? '提交中…' : '录入'}</Button>
          <span className="text-xs text-muted-foreground">
            手工录入为低权威来源（conversation/20）——平台抓取到更准数据可覆盖，高权威在场不覆盖
          </span>
          {msg && <span className="text-xs">{msg}</span>}
        </div>
      </CardContent>
    </Card>
  )
}

export function CreatorsPage() {
  const [q, setQ] = useState('')
  const [platform, setPlatform] = useState<string>('all')
  const [niche, setNiche] = useState('')
  const [source, setSource] = useState<string>('all')
  const [minFollowers, setMinFollowers] = useState('')
  const [maxQuote, setMaxQuote] = useState('')
  const [sort, setSort] = useState<string>('followers')
  const [items, setItems] = useState<CreatorItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [importMsg, setImportMsg] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const size = 12

  const load = useCallback(async (p: number) => {
    setBusy(true); setError('')
    try {
      const query: CreatorListQuery = { page: p, size, q: q.trim(), sort: sort as 'followers' }
      if (platform !== 'all') query.platform = platform
      if (niche.trim()) query.niche = niche.trim()
      if (source !== 'all') query.source = source
      if (minFollowers.trim()) query.min_followers = Number(minFollowers)
      if (maxQuote.trim()) query.max_quote = Number(maxQuote)
      const r = await listCreators(query)
      setItems(r.items); setTotal(r.total); setPage(p)
    } catch (e) {
      setError(`${e}`)
    } finally {
      setBusy(false)
    }
  }, [q, platform, niche, source, minFollowers, maxQuote, sort])

  useEffect(() => { void load(1) }, [load])

  /** 导出当前筛选（spec §14）：取 size=100 生成 CSV 下载 */
  const exportCsv = async () => {
    try {
      const query: CreatorListQuery = { page: 1, size: 100, q: q.trim(), sort: sort as 'followers' }
      if (platform !== 'all') query.platform = platform
      if (niche.trim()) query.niche = niche.trim()
      if (source !== 'all') query.source = source
      const r = await listCreators(query)
      const head = 'name,platform,niches,followers,quote_20s,quote_image,gmv_30d,city,rating,collab_cases,source'
      const body = r.items.map((c) => [
        c.name, c.platform, c.niches.join('|'), c.followers, c.quote_20s, c.quote_image,
        c.gmv_30d, c.city, c.rating, c.cases, c.source ?? '',
      ].join(',')).join('\n')
      const url = URL.createObjectURL(new Blob([`\ufeff${head}\n${body}`], { type: 'text/csv' }))
      const a = document.createElement('a')
      a.href = url; a.download = `creators-${Date.now()}.csv`; a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError(`导出失败：${e}`)
    }
  }

  const doImport = async (f: File) => {
    setImportMsg('导入中…')
    try {
      const r = await importCreators(f)
      setImportMsg(`新建 ${r.created} / 合并 ${r.merged} / 冲突 ${r.conflicts}`
        + (r.errors.length ? `；${r.errors.length} 行有误（如第 ${r.errors[0].line} 行：${r.errors[0].error}）` : ''))
      void load(1)
    } catch (e) {
      setImportMsg(`❌ ${e}`)
    }
  }

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
        <Input className="w-52" placeholder="达人名 / 视频方向" value={q}
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
        <Input className="w-32" placeholder="视频方向（如 露营）" value={niche}
               onChange={(e) => setNiche(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && load(1)} />
        <Select value={source} onValueChange={setSource}>
          <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
          <SelectContent>
            {Object.entries(SOURCE_OPT).map(([v, l]) => (
              <SelectItem key={v} value={v}>{l}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input className="w-28" placeholder="粉丝≥" value={minFollowers}
               onChange={(e) => setMinFollowers(e.target.value.replace(/\D/g, ''))}
               onKeyDown={(e) => e.key === 'Enter' && load(1)} />
        <Input className="w-28" placeholder="报价≤" value={maxQuote}
               onChange={(e) => setMaxQuote(e.target.value.replace(/\D/g, ''))}
               onKeyDown={(e) => e.key === 'Enter' && load(1)} />
        <Select value={sort} onValueChange={setSort}>
          <SelectTrigger className="w-28"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="followers">按粉丝</SelectItem>
            <SelectItem value="gmv">按 GMV</SelectItem>
            <SelectItem value="quote">按报价</SelectItem>
          </SelectContent>
        </Select>
        <Button size="sm" disabled={busy} onClick={() => load(1)}>筛选</Button>
        <div className="ml-auto flex items-center gap-2">
          <input ref={fileRef} type="file" accept=".csv" className="hidden"
                 onChange={(e) => { const f = e.target.files?.[0]; if (f) void doImport(f); e.target.value = '' }} />
          <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()}>导入 CSV</Button>
          <Button variant="outline" size="sm" onClick={() => void exportCsv()}>导出</Button>
          <Button size="sm" onClick={() => setShowForm(!showForm)}>{showForm ? '收起录入' : '录入达人'}</Button>
          <span className="text-xs text-muted-foreground">共 {total} 位</span>
        </div>
      </div>

      {showForm && <CreatorForm onDone={() => load(1)} />}
      {importMsg && <div className="rounded-md bg-muted/60 p-2.5 text-xs">{importMsg}
        <span className="ml-2 text-muted-foreground">
          （CSV 模板列：name,platform,niches,followers,quote_20s,quote_image,gmv_30d,city,rating）
        </span>
      </div>}

      {error && <div className="rounded-md bg-red-50 p-3 text-xs text-red-600">{error}</div>}

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              {['达人', '平台', '视频方向', '粉丝', '20s 报价', '30天 GMV', '城市', '评分', '合作单', '来源'].map((h) => (
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
                <td className="px-3 py-2.5">
                  <Badge variant="secondary" className="font-normal">{c.source ?? '—'}</Badge>
                </td>
              </tr>
            ))}
            {!items.length && !busy && (
              <tr><td colSpan={10} className="px-3 py-8 text-center text-muted-foreground">没有匹配的达人</td></tr>
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
