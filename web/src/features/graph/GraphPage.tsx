// 图谱页：实体展开 + 力导向图（echarts）+ 案例统计卡 + 权限过滤计数
import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { graphEntity, type CaseStats, type Neighbor, type Persona } from '@/lib/api'

const CLASS_COLOR: Record<string, string> = {
  Brand: '#0ea5e9', Product: '#6366f1', Case: '#10b981', Campaign: '#f59e0b',
  Creative: '#ef4444', Guideline: '#8b5cf6', Person: '#ec4899', Metric: '#14b8a6',
  Channel: '#84cc16', DocVersion: '#94a3b8', LandingPage: '#a8a29e', Audience: '#f97316',
}

interface GNode { id: string; name: string; category: string; value?: string }
interface GEdge { source: string; target: string; label?: string }

const SEEDS = ['Person:li', 'Brand:B04', 'Guideline:G-01', 'Metric:cpa']

export function GraphPage({ persona }: { persona: Persona }) {
  const ref = useRef<HTMLDivElement>(null)
  const chart = useRef<echarts.ECharts | null>(null)
  const nodes = useRef<Map<string, GNode>>(new Map())
  const edges = useRef<Map<string, GEdge>>(new Map())
  const [focus, setFocus] = useState('Person:li')
  const [status, setStatus] = useState('')
  const [filtered, setFiltered] = useState(0)
  const [stats, setStats] = useState<CaseStats | null>(null)

  const render = () => {
    const cats = [...new Set([...nodes.current.values()].map((n) => n.category))]
    chart.current?.setOption({
      series: [{
        type: 'graph', layout: 'force', roam: true, draggable: true,
        force: { repulsion: 320, edgeLength: 90 },
        categories: cats.map((c) => ({ name: c, itemStyle: { color: CLASS_COLOR[c] ?? '#64748b' } })),
        label: { show: true, formatter: (p: { data: { name: string } }) => p.data.name, fontSize: 11 },
        edgeLabel: { show: true, fontSize: 9, color: '#64748b',
                     formatter: (p: { data: { label?: string } }) => p.data.label ?? '' },
        data: [...nodes.current.values()].map((n) => ({
          id: n.id, name: n.name, category: cats.indexOf(n.category),
          symbolSize: n.id === focus ? 46 : 30,
        })),
        edges: [...edges.current.values()],
      }],
    }, true)
  }

  const expand = async (id: string) => {
    setStatus(`展开 ${id} …`)
    try {
      const g = await graphEntity(id, persona.role, persona.user)
      const label = (s: string) => s.split(':').slice(1).join(':') || s
      nodes.current.set(g.entity.id, {
        id: g.entity.id, category: g.entity.class,
        name: label(g.entity.name ?? g.entity.id) + (g.entity.stage ? `·${g.entity.stage}` : ''),
      })
      g.neighbors.forEach((n: Neighbor) => {
        nodes.current.set(n.id, {
          id: n.id, category: n.class, name: label(n.name ?? n.id),
        })
        edges.current.set(`${n.id}->${g.entity.id}`, {
          source: n.id, target: g.entity.id, label: n.via,
        })
      })
      setFiltered((f) => f + g.filtered)
      setStats(g.entity.class === 'Case' ? (g.stats ?? null) : null)
      setFocus(id)
      setStatus(`${g.entity.id}：${g.neighbors.length} 个邻居${g.filtered ? `（${g.filtered} 被权限过滤）` : ''}`)
      render()
    } catch (e) {
      setStatus(`展开失败：${e}`)
    }
  }

  useEffect(() => {
    if (!ref.current) return
    chart.current = echarts.init(ref.current)
    chart.current.on('click', (p: unknown) => {
      const e = p as { dataType?: string; data?: { id?: string } }
      if (e.dataType === 'node' && e.data?.id) expand(e.data.id)
    })
    nodes.current.clear(); edges.current.clear(); setFiltered(0)
    SEEDS.forEach((s) => expand(s))
    const onResize = () => chart.current?.resize()
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); chart.current?.dispose() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 切角色重查：权限口径随 persona 变化（画面 4：不同角色不同子图）
  useEffect(() => {
    if (!chart.current) return
    nodes.current.clear(); edges.current.clear(); setFiltered(0)
    SEEDS.forEach((s) => expand(s))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persona.role, persona.user])

  return (
    <div className="flex h-[calc(100vh-8.5rem)] flex-col">
      <div className="flex items-center gap-2.5 px-5 py-3">
        <Input className="w-96 font-mono text-[13px]" value={focus}
               placeholder="实体 ID（如 Case:C-2025-005）回车展开"
               onChange={(e) => setFocus(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && expand(focus.trim())} />
        <Button size="sm" className="px-4" onClick={() => expand(focus.trim())}>展开</Button>
        <span className="text-xs text-muted-foreground">{status}</span>
        {filtered > 0 && <Badge variant="destructive">{filtered} 条边被权限过滤</Badge>}
      </div>
      {stats && (
        <div className="flex flex-wrap items-center gap-4 px-5 py-2 text-xs">
          <span className="font-semibold text-foreground">案例统计</span>
          {([
            ['消耗', `¥${Number(stats.cost).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`],
            ['CTR', `${(Number(stats.ctr) * 100).toFixed(2)}%`],
            ['CVR', `${(Number(stats.cvr) * 100).toFixed(2)}%`],
            ['CPA', `¥${stats.cpa}`],
            ['天数', `${stats.days}`],
          ] as const).map(([k, v]) => (
            <span key={k} className="rounded-md bg-muted/60 px-2 py-1">
              <span className="text-muted-foreground">{k}</span>{' '}
              <b className="font-mono text-foreground">{v}</b>
            </span>
          ))}
          {stats.first_day && (
            <span className="text-muted-foreground">
              {stats.first_day} ~ {stats.last_day}
            </span>
          )}
          <span className="text-[10px] text-muted-foreground">比率型 = 汇总比（README §六）</span>
        </div>
      )}
      <div ref={ref} className="min-h-0 flex-1" />
      <div className="flex flex-wrap gap-3.5 px-5 py-2 text-[11px] text-muted-foreground">
        {Object.entries(CLASS_COLOR).map(([c, col]) => (
          <span key={c} className="flex items-center gap-1">
            <i className="inline-block size-2 rounded-full" style={{ background: col }} />{c}
          </span>
        ))}
      </div>
      <div className="px-5 pb-2.5 text-[11px] text-slate-300">点击节点继续展开 · 滚轮缩放 · 拖拽平移</div>
    </div>
  )
}
