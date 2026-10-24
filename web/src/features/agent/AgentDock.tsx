// Agent 悬浮窗（spec §6）：全局常驻——右下角悬浮球唤起，跨页面保留会话
// 问答 + 生成合一；案例草稿仍需确认入图（/ingest/case-commit 服务端重校验，铁律不因 agent 而绕过）
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { Bot, Minus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { agentChat, caseCommit } from '@/lib/api'
import { NodeCard, DraftCard } from '@/features/shared/cards'
import { usePersona } from '@/lib/session'
import type { CaseDraft, CreativeDraftItem } from '@/lib/api'

interface Msg {
  role: 'user' | 'assistant'
  content: string
  caseDraft?: CaseDraft | null
  creatives?: CreativeDraftItem[] | null
  trace?: { tool: string; result: string }[]
  committed?: boolean
}

export function AgentDock() {
  const navigate = useNavigate()
  const persona = usePersona()
  const [open, setOpen] = useState(false)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const bottom = useRef<HTMLDivElement>(null)
  // can_commit_case 由 /agent/chat 响应下发（§9.7）——前端不再本地硬抄角色表
  const [canCommit, setCanCommit] = useState(false)

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, busy, open])

  const send = async () => {
    const text = input.trim()
    if (!text || busy) return
    const history = [...msgs, { role: 'user' as const, content: text }]
    setMsgs(history)
    setInput('')
    setBusy(true); setError('')
    try {
      const r = await agentChat(
        history.filter((m) => !m.committed).map((m) => ({ role: m.role, content: m.content })),
        persona)
      setCanCommit(r.can_commit_case !== false)
      setMsgs((prev) => [...prev, {
        role: 'assistant', content: r.reply, caseDraft: r.case_draft,
        creatives: r.creative_drafts, trace: r.trace,
      }])
    } catch (e) {
      setError(`agent 失败：${e}`)
    } finally {
      setBusy(false)
    }
  }

  const commit = async (idx: number, draft: CaseDraft) => {
    setMsgs((prev) => prev.map((m, i) => i === idx ? { ...m, committed: true } : m))
    try {
      await caseCommit(draft, persona)
      alert(`已入图：${draft.case?.id ?? ''}`)
      if (draft.case?.id) navigate('/graph', { state: { focus: draft.case.id } })
    } catch (e) {
      setError(`入图失败：${e}`)
      setMsgs((prev) => prev.map((m, i) => i === idx ? { ...m, committed: false } : m))
    }
  }

  return (
    <>
      {/* 关闭时缩为悬浮球；面板常挂 hidden 切换——消息与会话跨页面、跨开合不丢 */}
      {!open && (
        <button aria-label="打开 Agent 助手" title="Agent 助手"
                onClick={() => setOpen(true)}
                className="fixed bottom-5 right-5 z-50 flex size-12 items-center justify-center
                           rounded-full bg-primary text-primary-foreground shadow-lg
                           transition-transform hover:scale-105">
          <Bot className="size-5.5" />
        </button>
      )}
      <div className={open
        ? 'fixed bottom-4 right-4 z-50 flex h-[min(78vh,44rem)] w-[26.5rem] flex-col'
              + ' overflow-hidden rounded-xl border bg-card shadow-2xl'
        : 'hidden'}>
        <header className="flex items-center gap-2 border-b px-4 py-2.5">
          <Bot className="size-4 text-primary" />
          <span className="text-sm font-bold">Agent 助手</span>
          <span className="text-[11px] text-muted-foreground">问答 + 生成合一</span>
          <Button variant="ghost" size="sm" className="ml-auto h-7 px-2"
                  aria-label="收起" onClick={() => setOpen(false)}>
            <Minus className="size-4" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3.5">
          {msgs.length === 0 && !busy && (
            <div className="rounded-md border border-dashed p-5 text-center text-xs text-muted-foreground">
              试试：「看看库里有哪些已同步的文档」「途野露营最好的素材 CPA 多少」「根据极光潮品的商品出一个案例草稿」
            </div>
          )}
          {msgs.map((m, i) => (
            m.role === 'user' ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">{m.content}</div>
              </div>
            ) : (
              <div key={i} className="space-y-2">
                {!!m.trace?.length && (
                  <div className="font-mono text-[11px] text-muted-foreground">
                    🔧 {m.trace.map((t) => t.tool).join(' → ')}
                  </div>
                )}
                {m.content && (
                  <Card><CardContent className="whitespace-pre-wrap py-2.5 text-sm">{m.content}</CardContent></Card>
                )}
                {m.caseDraft && (
                  <Card>
                    <CardContent className="space-y-2 py-2.5">
                      <div className="flex items-center gap-2 text-xs">
                        <Badge>案例草稿</Badge>
                        {m.committed && <Badge variant="secondary">已入图</Badge>}
                      </div>
                      <div className="grid gap-2">
                        <NodeCard title="Case" node={m.caseDraft.case} />
                        <NodeCard title="Brand" node={m.caseDraft.brand} />
                        {m.caseDraft.products.map((p) => <NodeCard key={p.id} title="Product" node={p} />)}
                      </div>
                      {!m.committed && (
                        <Button size="sm" disabled={!canCommit}
                                onClick={() => commit(i, m.caseDraft as CaseDraft)}>确认入图</Button>
                      )}
                    </CardContent>
                  </Card>
                )}
                {!!m.creatives?.length && (
                  <div className="grid gap-2">
                    {m.creatives.map((d, j) => <DraftCard key={j} d={d} />)}
                  </div>
                )}
              </div>
            )
          ))}
          {busy && (
            <div className="rounded-lg bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
              agent 思考中…（自选工具检索 + 生成，可能需要 1–3 分钟）
            </div>
          )}
          {error && <div className="rounded-md bg-red-50 p-2.5 text-xs text-red-600">{error}</div>}
          <div ref={bottom} />
        </div>

        <div className="flex gap-2 border-t p-3">
          <Input value={input} placeholder="问数 / 建案例 / 出素材…"
                 onChange={(e) => setInput(e.target.value)}
                 onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && send()}
                 disabled={busy} />
          <Button size="sm" className="px-4" onClick={send} disabled={busy || !input.trim()}>发送</Button>
        </div>
      </div>
    </>
  )
}
