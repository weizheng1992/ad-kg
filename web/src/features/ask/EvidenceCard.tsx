// 单条证据卡：类型徽章 + authority 色 + 引文/行表 + provenance
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import type { Evidence } from '@/lib/api'

const TYPE_LABEL: Record<string, string> = {
  relation: '关系', fact: '事实', doc: '文档',
}

function authorityColor(a?: number): string {
  if ((a ?? 0) >= 80) return '#059669'
  if ((a ?? 0) >= 60) return '#2563eb'
  if ((a ?? 0) >= 40) return '#d97706'
  return '#6b7280'
}

export function EvidenceCard({ ev, idx }: { ev: Evidence; idx: number }) {
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center gap-2.5 px-3.5 py-3 text-[11px]">
        <Badge variant="secondary">{TYPE_LABEL[ev.type] ?? ev.type}</Badge>
        <span className="font-semibold" style={{ color: authorityColor(ev.provenance?.authority) }}>
          authority {ev.provenance?.authority ?? '—'}
        </span>
        {ev.confidence != null && <span className="text-muted-foreground">conf {ev.confidence}</span>}
        {ev.score != null && <span className="text-muted-foreground">score {ev.score}</span>}
        <span className="ml-auto text-slate-300">#{idx + 1}</span>
      </CardHeader>
      <CardContent className="px-3.5 pb-3.5 pt-0">
        <div className="mb-1 break-all font-mono text-xs">{ev.ref}</div>
        {ev.quote && (
          <div className="rounded-md border-l-3 border-border bg-muted/50 px-2.5 py-1.5 text-[13px] text-slate-700">
            “{ev.quote}”
          </div>
        )}
        {ev.rows && ev.rows.length > 0 && (
          <Table className="mt-2 text-xs">
            <TableHeader>
              <TableRow>
                {Object.keys(ev.rows[0]).map((k) => <TableHead key={k}>{k}</TableHead>)}
              </TableRow>
            </TableHeader>
            <TableBody>
              {ev.rows.slice(0, 5).map((row, i) => (
                <TableRow key={i}>
                  {Object.values(row).map((v, j) => <TableCell key={j}>{String(v)}</TableCell>)}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <div className="mt-2 text-[11px] text-muted-foreground">
          {ev.provenance?.source_type} · {ev.provenance?.source_id}
        </div>
      </CardContent>
    </Card>
  )
}
