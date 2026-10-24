// 达人详情（spec §3/§13/§15）：档案 + 来源卡 + 报价历史折线 + 合作案例（含指标与拒因）+ 带货商品
import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router'
import * as echarts from 'echarts'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { getCreator, type CreatorDetail } from '@/lib/api'

const STAGE_LABEL: Record<string, string> = {
  proposal: '提案中', live: '投放中', closed: '已结案',
  lost: '未成单', terminated: '已终止',
}
const wan = (n: number) => n >= 10000 ? `${(n / 10000).toFixed(1)}万` : `${n}`

export function CreatorDetailPage() {
  const { id } = useParams()
  const [d, setD] = useState<CreatorDetail | null>(null)
  const [error, setError] = useState('')
  const histRef = useRef<HTMLDivElement>(null)
  const histChart = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    setD(null); setError('')
    if (id) getCreator(decodeURIComponent(id)).then(setD).catch((e) => setError(`${e}`))
  }, [id])

  // 报价历史折线（spec §15）
  useEffect(() => {
    if (!d?.quote_history?.length || !histRef.current) return
    histChart.current = histChart.current ?? echarts.init(histRef.current)
    const h = d.quote_history
    histChart.current.setOption({
      grid: { left: 56, right: 16, top: 10, bottom: 22 },
      xAxis: { type: 'category', data: h.map((x) => x.date.slice(5)),
               axisLabel: { fontSize: 10, interval: 6 } },
      yAxis: { type: 'value', axisLabel: { fontSize: 10,
               formatter: (v: number) => `¥${(v / 1000).toFixed(0)}k` } },
      tooltip: { trigger: 'axis',
                 valueFormatter: (v: number) => `¥${Number(v).toLocaleString()}` },
      series: [{ type: 'line', smooth: true, data: h.map((x) => x.quote_20s),
                 areaStyle: { opacity: 0.12 }, lineStyle: { width: 2 } }],
    }, true)
    const onResize = () => histChart.current?.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [d])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  if (!d) return <div className="p-6 text-sm text-muted-foreground">加载中…</div>
  const c = d.creator

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex items-center gap-3">
        <Link to="/creators" className="text-xs text-primary hover:underline">← 达人库</Link>
        {d.provenance && (
          <span className="ml-auto text-[11px] text-muted-foreground">
            来源：<Badge variant="secondary" className="font-normal">{d.provenance.source}</Badge>
            {d.provenance.authority != null && `（权威 ${d.provenance.authority}）`}
            {d.provenance.fetched_at && ` · ${d.provenance.fetched_at.slice(0, 10)} 入库`}
            <span className="ml-1 font-mono">{d.provenance.source_id}</span>
          </span>
        )}
      </div>

      <Card>
        <CardContent className="flex flex-wrap items-center gap-x-8 gap-y-4 py-5">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold">{c.name}</h2>
              <Badge variant="secondary">
                {c.platform === 'douyin' ? '抖音' : c.platform === 'xhs' ? '小红书' : c.platform}
              </Badge>
            </div>
            <div className="mt-1.5">
              {c.niches.map((n) => <Badge key={n} variant="outline" className="mr-1 font-normal">{n}</Badge>)}
              <span className="ml-1 text-xs text-muted-foreground">{c.city} · 评分 {c.rating}</span>
            </div>
          </div>
          <div className="ml-auto flex flex-wrap gap-x-8">
            {([['粉丝', wan(c.followers)], ['20s 报价', `¥${c.quote_20s.toLocaleString('zh-CN')}`],
               ['图文报价', `¥${c.quote_image.toLocaleString('zh-CN')}`],
               ['30天 GMV', `¥${c.gmv_30d.toLocaleString('zh-CN')}`]] as const).map(([k, v]) => (
              <div key={k}>
                <div className="font-mono text-lg font-bold">{v}</div>
                <div className="text-xs text-muted-foreground">{k}</div>
              </div>
            ))}
          </div>
        </CardContent>
        {d.stats && (
          <CardContent className="flex flex-wrap items-center gap-3 border-t py-3 text-xs">
            <span className="font-semibold">合作案例投放（汇总比）</span>
            {d.stats.cost != null && (
              <span className="rounded-md bg-muted/60 px-2 py-1">消耗
                <b className="ml-1 font-mono">¥{Number(d.stats.cost).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</b></span>
            )}
            {d.stats.ctr != null && (
              <span className="rounded-md bg-muted/60 px-2 py-1">CTR
                <b className="ml-1 font-mono">{(Number(d.stats.ctr) * 100).toFixed(2)}%</b></span>
            )}
            {d.stats.cvr != null && (
              <span className="rounded-md bg-muted/60 px-2 py-1">CVR
                <b className="ml-1 font-mono">{(Number(d.stats.cvr) * 100).toFixed(2)}%</b></span>
            )}
            {d.stats.cpa != null && (
              <span className="rounded-md bg-muted/60 px-2 py-1">CPA
                <b className="ml-1 font-mono">¥{d.stats.cpa}</b></span>
            )}
            {d.stats.days != null && (
              <span className="rounded-md bg-muted/60 px-2 py-1">{d.stats.days} 天</span>
            )}
          </CardContent>
        )}
      </Card>

      {!!d.quote_history?.length && (
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-sm">
              报价历史（近 {d.quote_history.length} 个记录点；录入/导入/平台抓取自动留痕）
            </CardTitle>
          </CardHeader>
          <CardContent><div ref={histRef} className="h-44" /></CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            合作案例
            {d.collabs_filtered > 0 && (
              <Badge variant="destructive" className="font-normal">
                {d.collabs_filtered} 单被行权限过滤
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {d.collabs.length ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 font-medium">案例</th><th className="py-2 font-medium">阶段</th>
                  <th className="py-2 font-medium">消耗</th><th className="py-2 font-medium">CPA</th>
                  <th className="py-2 font-medium">未成单原因</th>
                </tr>
              </thead>
              <tbody>
                {d.collabs.map((x) => (
                  <tr key={x.id} className="border-b last:border-0">
                    <td className="py-2">
                      <Link to={`/cases/${encodeURIComponent(x.id)}`} className="text-primary hover:underline">
                        {x.name}
                      </Link>
                    </td>
                    <td className="py-2"><Badge variant="outline">{STAGE_LABEL[x.stage] ?? x.stage}</Badge></td>
                    <td className="py-2 font-mono">
                      {x.cost != null ? `¥${Number(x.cost).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}` : '—'}
                    </td>
                    <td className="py-2 font-mono">
                      {x.cpa != null ? `¥${Number(x.cpa).toFixed(2)}` : '—'}
                    </td>
                    <td className="py-2 text-muted-foreground">{x.lost_reason || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="py-2 text-sm text-muted-foreground">
              暂无可见合作（{d.collabs_filtered ? '你锚点子图外的合作单不可见' : '该达人还没有合作单'}）
            </p>
          )}
        </CardContent>
      </Card>

      {d.products.length > 0 && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">带货商品</CardTitle></CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {d.products.map((p) => (
              <div key={p.id} className="rounded-lg border p-3">
                <div className="text-sm font-medium">{p.name}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {p.spec && <span className="mr-2">{p.spec}</span>}
                  {p.target_age && <span>人群 {p.target_age} 岁</span>}
                </div>
                {p.price && <div className="mt-1.5 font-mono text-sm">¥{p.price}</div>}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
