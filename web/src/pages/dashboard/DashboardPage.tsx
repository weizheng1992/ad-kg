// 数据看板（spec §5 + §13.3 互链）：echarts 大盘——趋势/平台/品牌/达人/阶段漏斗，
// 数据随角色收敛；品牌条/达人条点击跳转对应详情
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import * as echarts from 'echarts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { statsOverview, type StatsOverview } from '@/lib/api'
import { useSession } from '@/lib/session'

const PLATFORM_LABEL: Record<string, string> = { douyin: '抖音', xhs: '小红书' }
const STAGE_LABEL: Record<string, string> = {
  proposal: '提案中', live: '投放中', closed: '已结案', lost: '未成单', terminated: '已终止',
}
const num = (v: string | number | null | undefined) => Number(v ?? 0)
const wan = (n: number) => n >= 10000 ? `${(n / 10000).toFixed(1)}万` : `${Math.round(n)}`

/** 一图一钩子：容器尺寸自适应 + 卸载释放 */
function useChart(draw: (chart: echarts.ECharts) => void, dep: unknown) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  useEffect(() => {
    if (!ref.current) return
    chart.current = chart.current ?? echarts.init(ref.current)
    draw(chart.current)
    const onResize = () => chart.current?.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dep])
  return ref
}

export function DashboardPage() {
  const { session } = useSession()
  const navigate = useNavigate()
  const [d, setD] = useState<StatsOverview | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setD(null); setError('')
    statsOverview().then(setD).catch((e) => setError(`${e}`))
  }, [session?.role, session?.person])

  const trendRef = useChart((c) => {
    if (!d) return
    c.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['消耗', '转化'], top: 0, textStyle: { fontSize: 11 } },
      grid: { left: 52, right: 40, top: 30, bottom: 24 },
      xAxis: { type: 'category', data: d.trend.map((t) => t.date.slice(5)) },
      yAxis: [{ type: 'value', name: '消耗', axisLabel: { formatter: (v: number) => wan(v) } },
              { type: 'value', name: '转化' }],
      series: [
        { name: '消耗', type: 'bar', data: d.trend.map((t) => num(t.cost)), itemStyle: { opacity: 0.75 } },
        { name: '转化', type: 'line', yAxisIndex: 1, data: d.trend.map((t) => num(t.conversions)), smooth: true },
      ],
    }, true)
  }, d)

  const platformRef = useChart((c) => {
    if (!d) return
    c.setOption({
      tooltip: { trigger: 'item' },
      series: [{
        type: 'pie', radius: ['42%', '70%'], center: ['50%', '52%'],
        label: { formatter: '{b}\n{d}%' },
        data: d.platforms.map((p) => ({
          name: PLATFORM_LABEL[p.platform] ?? p.platform, value: num(p.cost),
        })),
      }],
    }, true)
  }, d)

  const brandRef = useChart((c) => {
    if (!d) return
    const rows = [...d.brands].slice(0, 8).reverse()
    c.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 90, right: 30, top: 8, bottom: 24 },
      xAxis: { type: 'value', axisLabel: { formatter: (v: number) => wan(v) } },
      yAxis: { type: 'category', data: rows.map((b) => b.brand_id.split(':')[1] ?? b.brand_id) },
      series: [{ type: 'bar', data: rows.map((b) => num(b.cost)),
                 label: { show: true, position: 'right', formatter: (p: { value: number }) => wan(p.value) } }],
    }, true)
    c.off('click')                                        // §13.3 互链：品牌条跳详情
    c.on('click', (p: { componentType?: string; dataIndex?: number }) => {
      const bid = rows[p.dataIndex ?? 0]?.brand_id
      if (p.componentType === 'series' && bid) navigate(`/brands/${encodeURIComponent(bid)}`)
    })
  }, d)

  const creatorRef = useChart((c) => {
    if (!d?.top_creators) return
    const rows = [...d.top_creators].reverse()
    c.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 100, right: 40, top: 8, bottom: 24 },
      xAxis: { type: 'value', axisLabel: { formatter: (v: number) => wan(v) } },
      yAxis: { type: 'category', data: rows.map((x) => x.name) },
      series: [{ type: 'bar', data: rows.map((x) => num(x.gmv_30d)),
                 itemStyle: { color: '#f59e0b' },
                 label: { show: true, position: 'right', formatter: (p: { value: number }) => wan(p.value) } }],
    }, true)
    c.off('click')                                        // §13.3 互链：达人条跳详情
    c.on('click', (p: { componentType?: string; dataIndex?: number }) => {
      const cid = rows[p.dataIndex ?? 0]?.id
      if (p.componentType === 'series' && cid) navigate(`/creators/${encodeURIComponent(cid)}`)
    })
  }, d)

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  if (!d) return <div className="p-6 text-sm text-muted-foreground">加载大盘数据…</div>

  const costTotal = d.trend.reduce((s, t) => s + num(t.cost), 0)
  const convTotal = d.trend.reduce((s, t) => s + num(t.conversions), 0)
  const caseTotal = d.stages.reduce((s, x) => s + x.count, 0)

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-baseline gap-3">
        <h2 className="text-base font-bold">数据看板</h2>
        <span className="text-xs text-muted-foreground">
          近 {d.days} 天 · 汇总比口径（README §六）——数据集合随你的角色锚点变化
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        {([['消耗', `¥${wan(costTotal)}`], ['转化', wan(convTotal)],
           ['可见案例', `${caseTotal}`],
           ['结算中', `${d.stages.find((s) => s.stage === 'live')?.count ?? 0} 投放中`]] as const)
          .map(([k, v]) => (
            <Card key={k}><CardContent className="py-4">
              <div className="font-mono text-xl font-bold">{v}</div>
              <div className="text-xs text-muted-foreground">{k}</div>
            </CardContent></Card>
          ))}
      </div>

      <Card>
        <CardHeader className="pb-1"><CardTitle className="text-sm">消耗 / 转化趋势</CardTitle></CardHeader>
        <CardContent><div ref={trendRef} className="h-64" /></CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-1"><CardTitle className="text-sm">平台分布（按消耗）</CardTitle></CardHeader>
          <CardContent><div ref={platformRef} className="h-60" /></CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1"><CardTitle className="text-sm">品牌消耗 Top</CardTitle></CardHeader>
          <CardContent><div ref={brandRef} className="h-60" /></CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {d.top_creators && (
          <Card>
            <CardHeader className="pb-1"><CardTitle className="text-sm">达人 30 天 GMV Top（有合作）</CardTitle></CardHeader>
            <CardContent><div ref={creatorRef} className="h-60" /></CardContent>
          </Card>
        )}
        <Card>
          <CardHeader className="pb-1"><CardTitle className="text-sm">案例阶段分布</CardTitle></CardHeader>
          <CardContent className="space-y-2 pt-2">
            {d.stages.map((s) => (
              <div key={s.stage} className="flex items-center gap-3 text-xs">
                <span className="w-14 text-muted-foreground">{STAGE_LABEL[s.stage] ?? s.stage}</span>
                <div className="h-4 flex-1 overflow-hidden rounded bg-muted">
                  <div className="h-full rounded bg-primary"
                       style={{ width: `${caseTotal ? (s.count / caseTotal) * 100 : 0}%` }} />
                </div>
                <span className="w-8 text-right font-mono">{s.count}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
