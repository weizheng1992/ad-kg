import { useState } from 'react'
import { ask, type AskResponse, type Evidence, type Persona } from './api'

const EXAMPLES = [
  '李昂负责哪些 Case？',
  '上月 CPA 最差的素材有哪些？',
  '信息流视频的时长规范是什么？',
  '效果差的素材和创意规范有没有关系？',
  '删掉 live 案例的素材 creative_992',
]

const TYPE_LABEL: Record<string, string> = {
  relation: '关系', fact: '事实', doc: '文档',
}

function authorityColor(a?: number): string {
  if ((a ?? 0) >= 80) return '#059669'
  if ((a ?? 0) >= 60) return '#2563eb'
  if ((a ?? 0) >= 40) return '#d97706'
  return '#6b7280'
}

function EvidenceCard({ ev, idx }: { ev: Evidence; idx: number }) {
  return (
    <div className="ev">
      <div className="ev-head">
        <span className={`chip t-${ev.type}`}>{TYPE_LABEL[ev.type] ?? ev.type}</span>
        <span className="auth" style={{ color: authorityColor(ev.provenance?.authority) }}>
          authority {ev.provenance?.authority ?? '—'}
        </span>
        {ev.confidence != null && <span className="conf">conf {ev.confidence}</span>}
        {ev.score != null && <span className="conf">score {ev.score}</span>}
        <span className="idx">#{idx + 1}</span>
      </div>
      <div className="ev-ref">{ev.ref}</div>
      {ev.quote && <div className="ev-quote">“{ev.quote}”</div>}
      {ev.rows && ev.rows.length > 0 && (
        <table className="ev-rows">
          <thead><tr>{Object.keys(ev.rows[0]).map((k) => <th key={k}>{k}</th>)}</tr></thead>
          <tbody>
            {ev.rows.slice(0, 5).map((row, i) => (
              <tr key={i}>{Object.values(row).map((v, j) => <td key={j}>{String(v)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="ev-prov">
        {ev.provenance?.source_type} · {ev.provenance?.source_id}
      </div>
    </div>
  )
}

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
    <div className="ask">
      <div className="ask-bar">
        <input
          value={q}
          placeholder="问点什么……（跨系统问题也能答，每条证据带来源）"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && q.trim() && run(q.trim())}
        />
        <button disabled={!q.trim() || busy} onClick={() => run(q.trim())}>
          {busy ? '检索中…' : '提问'}
        </button>
      </div>
      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} className="ex" onClick={() => { setQ(ex); run(ex) }}>{ex}</button>
        ))}
      </div>

      {err && <div className="error">{err}</div>}
      {res && (
        <div className="result">
          {res.action === 'guidance' ? (
            <div className="guidance">
              操作类请求不进检索——请调用 <code>{res.endpoint}</code> 做裁决。
              <div className="g-reason">{res.reason}</div>
            </div>
          ) : (
            <>
              <div className="answer">{res.answer}</div>
              <div className="meta">
                {res.intent && <span className="chip intent">{res.intent}</span>}
                {res.routes_used?.map((r) => (
                  <span key={r.route} className="route">{r.route} {r.score}</span>
                ))}
                {res.permission_applied && <span className="chip perm">权限已过滤</span>}
                {res.degraded?.map((d) => <span key={d} className="chip degr">缺席：{d}</span>)}
              </div>
              <div className="evidence">
                {res.evidence?.map((ev, i) => <EvidenceCard key={`${i}-${ev.ref}`} ev={ev} idx={i} />)}
                {res.evidence?.length === 0 && <div className="empty">无可支撑证据（或被权限过滤）</div>}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
