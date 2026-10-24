// Agent 悬浮窗（spec §6）：全局常驻——右下角悬浮球唤起，跨页面保留会话。
// ZCode 式透明时间线：思考 / 工具调用 / 浏览子步（截图）/ 结果逐事件上屏（SSE 流式）；
// 案例草稿仍需确认入图（/ingest/case-commit 服务端重校验，铁律不因 agent 而绕过）
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Bot, ChevronRight, Minus, Wrench } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { agentChatStream, caseCommit, type AgentEvent } from '@/lib/api'
import { NodeCard, DraftCard } from '@/features/shared/cards'
import type { CaseDraft, CreativeDraftItem } from '@/lib/api'

interface Msg {
  role: 'user' | 'assistant'
  content: string
  caseDraft?: CaseDraft | null
  creatives?: CreativeDraftItem[] | null
  /** SSE 时间线（spec §6）：thought / tool_start / tool_step / tool_result */
  steps?: AgentEvent[]
  committed?: boolean
}

const TOOL_LABEL: Record<string, string> = {
  ask_knowledge: '知识问答', list_brands: '品牌清单',
  search_product_knowledge: '商品知识检索', search_best_creatives: '最好素材检索',
  get_guidelines: '创意规范', list_synced_docs: '已同步文档',
  fetch_creator_from_platform: '数据平台抓取',
}

function StepLine({ ev }: { ev: AgentEvent }) {
  const [open, setOpen] = useState(false)
  if (ev.type === 'thought') {
    return (
      <div className="flex items-start gap-1.5 text-[11px] italic text-muted-foreground">
        <span className="not-italic">💭</span>{ev.text}
      </div>
    )
  }
  if (ev.type === 'tool_start') {
    return (
      <div className="flex items-center gap-1.5 rounded-md bg-muted/70 px-2 py-1 text-[11px]">
        <Wrench className="size-3 shrink-0" />
        <b>{TOOL_LABEL[ev.tool] ?? ev.tool}</b>
        {Object.keys(ev.args ?? {}).length > 0 && (
          <span className="truncate font-mono text-muted-foreground">
            {JSON.stringify(ev.args)}
          </span>
        )}
      </div>
    )
  }
  if (ev.type === 'tool_step') {
    return (
      <div className="ml-3 space-y-1 border-l pl-2.5 text-[11px]">
        <div className="text-muted-foreground">▸ {ev.desc}</div>
        {ev.screenshot && (
          <>
            <img src={ev.screenshot} alt={`步骤${ev.step}截图`}
                 onClick={() => setOpen(!open)}
                 className={`cursor-zoom-in rounded border ${open ? 'max-h-none w-full' : 'max-h-20'}`} />
          </>
        )}
      </div>
    )
  }
  if (ev.type === 'tool_result') {
    return (
      <details className="ml-3 text-[11px] text-muted-foreground">
        <summary className="cursor-pointer select-none">工具结果（点击展开）</summary>
        <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all font-mono">
          {ev.result}
        </pre>
      </details>
    )
  }
  return null
}

export function AgentDock() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const bottom = useRef<HTMLDivElement>(null)
  // can_commit_case 由 /agent/chat/stream done 事件下发（§9.7）——前端不硬抄角色表
  const [canCommit, setCanCommit] = useState(false)

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs, busy, open])

  const send = async () => {
    const text = input.trim()
    if (!text || busy) return
    const history = [...msgs, { role: 'user' as const, content: text }]
    setMsgs([...history, { role: 'assistant', content: '', steps: [] }])
    setInput('')
    setBusy(true); setError('')
    const patch = (fn: (m: Msg) => Msg) =>
      setMsgs((prev) => prev.map((m, i) => i === prev.length - 1 ? fn(m) : m))
    try {
      await agentChatStream(
        history.filter((m) => !m.committed).map((m) => ({ role: m.role, content: m.content })),
        (ev) => patch((m) => {
          if (ev.type === 'reply') return { ...m, content: ev.text }
          if (ev.type === 'draft') {
            return { ...m, caseDraft: ev.case_draft, creatives: ev.creative_drafts }
          }
          if (ev.type === 'done') {
            setCanCommit(ev.can_commit_case)
            return m
          }
          if (ev.type === 'error') return { ...m, content: `⚠️ ${ev.detail}` }
          return { ...m, steps: [...(m.steps ?? []), ev] }
        }))
    } catch (e) {
      setError(`agent 失败：${e}`)
    } finally {
      setBusy(false)
    }
  }

  const commit = async (idx: number, draft: CaseDraft) => {
    setMsgs((prev) => prev.map((m, i) => i === idx ? { ...m, committed: true } : m))
    try {
      await caseCommit(draft)
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
          <span className="text-[11px] text-muted-foreground">问答 · 生成 · 平台抓取</span>
          <Button variant="ghost" size="sm" className="ml-auto h-7 px-2"
                  aria-label="收起" onClick={() => setOpen(false)}>
            <Minus className="size-4" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3.5">
          {msgs.length === 0 && !busy && (
            <div className="rounded-md border border-dashed p-5 text-center text-xs text-muted-foreground">
              试试：「从数据平台抓一下铲屎官阿喵的最新报价」「途野露营最好的素材 CPA 多少」
              「根据极光潮品的商品出一个案例草稿」
            </div>
          )}
          {msgs.map((m, i) => (
            m.role === 'user' ? (
              <div key={i} className="flex justify-end">
                <div className="max-w-[80%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">{m.content}</div>
              </div>
            ) : (
              <div key={i} className="space-y-1.5">
                {!!m.steps?.length && (
                  <div className="space-y-1 rounded-lg bg-muted/40 p-2">
                    {m.steps.map((ev, j) => <StepLine key={j} ev={ev} />)}
                  </div>
                )}
                {m.content && (
                  <Card>
                    <CardContent className="py-2.5 text-sm leading-relaxed
                                            [&_p:first-child]:mt-0 [&_p:last-child]:mb-0
                                            [&_table]:my-2 w-full [&_table]:text-[11px]
                                            [&_th]:border [&_th]:px-1.5 [&_th]:py-1 [&_th]:bg-muted/50
                                            [&_td]:border [&_td]:px-1.5 [&_td]:py-1
                                            [&_code]:rounded [&_code]:bg-muted [&_code]:px-1
                                            [&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-4">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                    </CardContent>
                  </Card>
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
            <div className="flex items-center gap-1.5 rounded-lg bg-muted/60 px-3 py-2 text-xs text-muted-foreground">
              <ChevronRight className="size-3.5 animate-pulse" />agent 工作中…（下方时间线实时更新）
            </div>
          )}
          {error && <div className="rounded-md bg-red-50 p-2.5 text-xs text-red-600">{error}</div>}
          <div ref={bottom} />
        </div>

        <div className="flex gap-2 border-t p-3">
          <Input value={input} placeholder="问数 / 建案例 / 抓达人…"
                 onChange={(e) => setInput(e.target.value)}
                 onKeyDown={(e) => e.key === 'Enter' && !e.nativeEvent.isComposing && send()}
                 disabled={busy} />
          <Button size="sm" className="px-4" onClick={send} disabled={busy || !input.trim()}>发送</Button>
        </div>
      </div>
    </>
  )
}
