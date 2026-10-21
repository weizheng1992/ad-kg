// 草稿展示卡片（案例生成 / 素材灵感 / Agent 三个场景共用）
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { CreativeDraftItem, DraftNode } from '@/lib/api'

export function NodeCard({ title, node }: { title: string; node: DraftNode | null }) {
  if (!node) return null
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-sm">
          {title}
          <Badge variant={node.existing ? 'secondary' : 'default'}>
            {node.existing ? (node.same_doc ? '本文档已生成·将刷新' : '复用既有实体') : '新建'}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1 text-[13px]">
        <div className="font-semibold text-foreground">{node.name}</div>
        <div className="font-mono text-[11px] text-muted-foreground">{node.id}</div>
        {Object.entries(node.props)
          .filter(([k]) => k !== 'name')
          .map(([k, v]) => (
            <div key={k} className="text-muted-foreground">
              {k}：<span className="font-mono text-foreground">{String(v)}</span>
            </div>
          ))}
      </CardContent>
    </Card>
  )
}

export function DraftCard({ d }: { d: CreativeDraftItem }) {
  // LLM 输出 script/copy 可能是字符串或逐行数组——统一归一成带换行的文本
  const text = (v: unknown) => (Array.isArray(v) ? v.map((x) => String(x)).join('\n') : String(v ?? ''))
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center justify-between gap-2 text-sm">
          <span className="truncate">{d.title}</span>
          <Badge variant="secondary" className="shrink-0">{d.format}</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-[13px]">
        <div className="rounded-md bg-amber-50 px-2.5 py-1.5">
          <span className="text-xs font-semibold text-amber-700">前 3 秒钩子</span>
          <div className="text-foreground">{text(d.hook_3s)}</div>
        </div>
        <div>
          <span className="text-xs font-semibold text-muted-foreground">分镜脚本</span>
          <pre className="whitespace-pre-wrap font-sans text-foreground">{text(d.script)}</pre>
        </div>
        <div>
          <span className="text-xs font-semibold text-muted-foreground">投放文案</span>
          <div className="whitespace-pre-wrap text-foreground">{text(d.copy)}</div>
        </div>
        {d.based_on && d.based_on.length > 0 && (
          <div className="font-mono text-[11px] text-muted-foreground">依据：{d.based_on.join(' ')}</div>
        )}
      </CardContent>
    </Card>
  )
}
