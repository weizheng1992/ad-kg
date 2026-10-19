import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts'
import { graphEntity, type Neighbor, type Persona } from './api'

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
    <div className="graph">
      <div className="g-bar">
        <input
          value={focus}
          onChange={(e) => setFocus(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && expand(focus.trim())}
          placeholder="实体 ID（如 Case:C-2025-005）回车展开"
        />
        <button onClick={() => expand(focus.trim())}>展开</button>
        <span className="g-status">{status}</span>
        {filtered > 0 && <span className="chip perm">{filtered} 条边被权限过滤</span>}
      </div>
      <div ref={ref} className="g-canvas" />
      <div className="g-legend">
        {Object.entries(CLASS_COLOR).map(([c, col]) => (
          <span key={c}><i style={{ background: col }} />{c}</span>
        ))}
      </div>
      <div className="g-hint">点击节点继续展开 · 滚轮缩放 · 拖拽平移</div>
    </div>
  )
}
