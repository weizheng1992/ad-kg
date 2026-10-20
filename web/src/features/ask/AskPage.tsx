// 问答页：提问 → 回答卡（intent/路由/权限/缺席）→ 证据列表
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ask, type AskResponse, type Persona } from '@/lib/api'
import { EvidenceCard } from './EvidenceCard'

const EXAMPLES = [
  '李昂负责哪些 Case？',
  '上月 CPA 最差的素材有哪些？',
  '信息流视频的时长规范是什么？',
  '效果差的素材和创意规范有没有关系？',
  '删掉 live 案例的素材 creative_992',
]

export function AskPage({ persona }: { persona: Persona }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState<AskResponse | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const run = async (question: string) => {
    setBusy(true); setErr(''); setRes(null)
    try {
      setRes(await ask(question, persona.role, persona.user))
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-5 py-7">
      <div className="flex gap-2.5">
        <Input className="h-12 text-[15px]" value={q}
               placeholder="问点什么……（跨系统问题也能答，每条证据带来源）"
               onChange={(e) => setQ(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && q.trim() && run(q.trim())} />
        <Button className="h-12 px-6 text-[15px]" disabled={!q.trim() || busy}
                onClick={() => run(q.trim())}>
          {busy ? '检索中…' : '提问'}
        </Button>
      </div>

      <div className="my-3.5 flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <Button key={ex} variant="outline" size="sm" className="rounded-full border-dashed text-xs text-muted-foreground"
                  onClick={() => { setQ(ex); run(ex) }}>
            {ex}
          </Button>
        ))}
      </div>

      {err && <div className="p-3 text-red-600">{err}</div>}

      {res && (res.action === 'guidance' ? (
        <Alert className="mt-4 border-amber-200 bg-amber-50">
          <AlertTitle>操作类请求不进检索——请调用 <code>{res.endpoint}</code> 做裁决。</AlertTitle>
          <AlertDescription className="text-muted-foreground">{res.reason}</AlertDescription>
        </Alert>
      ) : (
        <div className="mt-4.5 flex flex-col gap-2.5">
          <Card>
            <CardContent className="px-4.5 py-4 text-[15px] leading-relaxed">
              <div className="md-answer">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{res.answer}</ReactMarkdown>
              </div>
            </CardContent>
          </Card>

          <div className="flex flex-wrap items-center gap-2">
            {res.intent && <Badge className="bg-violet-100 text-violet-700 hover:bg-violet-100">{res.intent}</Badge>}
            {res.routes_used?.map((r) => (
              <span key={r.route} className="rounded-md bg-blue-50 px-2 py-0.5 text-[11px] text-blue-700">
                {r.route} {r.score}
              </span>
            ))}
            {res.permission_applied && (
              <Badge variant="destructive">权限已过滤</Badge>
            )}
            {res.degraded?.map((d) => (
              <Badge key={d} className="bg-amber-100 text-amber-700 hover:bg-amber-100">缺席：{d}</Badge>
            ))}
          </div>

          <div className="flex flex-col gap-2.5">
            {res.evidence?.map((ev, i) => <EvidenceCard key={`${i}-${ev.ref}`} ev={ev} idx={i} />)}
            {res.evidence?.length === 0 && (
              <div className="p-4 text-center text-muted-foreground">无可支撑证据（或被权限过滤）</div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}
