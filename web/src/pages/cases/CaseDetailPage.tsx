// 案例详情（spec §13.2 六段）：概要/内容/指标/状态流转/收益/合作达人
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { getCase, type CaseDetail } from '@/lib/api'
import { STAGE_LABEL } from '@/pages/cases/CasesPage'

const yuan = (v?: string | number | null) =>
  v == null || v === '' ? '—' : `¥${Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
const pct = (v?: string | null) =>
  v == null || v === '' ? '—' : `${(Number(v) * 100).toFixed(2)}%`
const wan = (n: number) => n >= 10000 ? `${(n / 10000).toFixed(1)}万` : `${n}`

/** 状态机流程条：主线 proposal→live→closed，分支 lost/terminated 挂在来源阶段下方 */
function StageFlow({ flow, reason }: { flow: CaseDetail['stage_flow']; reason?: string | null }) {
  const idx = flow.main.indexOf(flow.current)
  const branchFrom = flow.branch[flow.current]
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1">
        {flow.main.map((s, i) => (
          <div key={s} className="flex items-center gap-1">
            {i > 0 && <span className="text-muted-foreground">→</span>}
            <span className={`rounded-md px-2.5 py-1 text-xs ${
              flow.current === s ? 'bg-primary font-semibold text-primary-foreground'
              : idx >= 0 && i < idx ? 'bg-muted text-muted-foreground' : 'border text-muted-foreground'}`}>
              {STAGE_LABEL[s]}
            </span>
          </div>
        ))}
      </div>
      {branchFrom && (
        <div className="text-xs">
          <span className="text-muted-foreground">在「{STAGE_LABEL[branchFrom]}」阶段分流 → </span>
          <Badge variant="destructive">{STAGE_LABEL[flow.current]}</Badge>
        </div>
      )}
      {reason && (
        <div className="rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
          取消/终止原因：{reason}
        </div>
      )}
    </div>
  )
}

export function CaseDetailPage() {
  const { id } = useParams()
  const [d, setD] = useState<CaseDetail | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    setD(null); setError('')
    if (id) getCase(decodeURIComponent(id)).then(setD).catch((e) => setError(`${e}`))
  }, [id])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  if (!d) return <div className="p-6 text-sm text-muted-foreground">加载中…</div>
  const c = d.case
  const reason = c.lost_reason || c.terminate_reason || null
  // 预估毛利额（标注估）：bd_budget × gross_margin
  const marginEst = c.bd_budget && c.gross_margin
    ? `¥${(Number(c.bd_budget) * Number(c.gross_margin)).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
    : null

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/cases" className="text-xs text-primary hover:underline">← 案例</Link>
        <h2 className="text-base font-bold">{c.name}</h2>
        <Badge variant="outline">{STAGE_LABEL[c.stage] ?? c.stage}</Badge>
        {d.brand && (
          <Link to={`/brands/${encodeURIComponent(d.brand.id)}`} className="text-xs text-primary hover:underline">
            {d.brand.name}
          </Link>
        )}
        {c.settlement_status && (
          <Badge variant={c.settlement_status === 'paid' ? 'secondary' : 'destructive'}
                 className={c.settlement_status === 'paid' ? 'bg-emerald-100 text-emerald-700' : ''}>
            {c.settlement_status === 'paid' ? '已结算' : '未结算'}
          </Badge>
        )}
        <span className="ml-auto text-[11px] font-mono text-muted-foreground">{c.id}</span>
      </div>

      {/* 1 概要 + 3 指标 */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-1"><CardTitle className="text-sm">概要</CardTitle></CardHeader>
          <CardContent className="space-y-1.5 text-sm">
            <div>负责人：{d.owners.map((o) => o.name).join('、') || '—'}</div>
            {d.product && (
              <div>商品：
                {d.product.name}
                {d.product.target_age && <span className="text-muted-foreground">（人群 {d.product.target_age} 岁）</span>}
                {d.product.price && <span className="ml-1 font-mono">¥{d.product.price}</span>}
              </div>
            )}
            {c.bd_budget && <div>BD 预算：<b className="font-mono">{yuan(c.bd_budget)}</b></div>}
            {c.gross_margin && <div>毛利率：<b className="font-mono">{(Number(c.gross_margin) * 100).toFixed(0)}%</b></div>}
            <div className="text-xs text-muted-foreground">计划 {d.campaigns.length} 支 · 素材 {d.creatives.length} 条</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-1"><CardTitle className="text-sm">投放指标（汇总比）</CardTitle></CardHeader>
          <CardContent className="flex flex-wrap gap-x-7 gap-y-3">
            {([['消耗', d.stats?.cost != null ? yuan(d.stats.cost) : '—'],
               ['CTR', pct(d.stats?.ctr)], ['CVR', pct(d.stats?.cvr)],
               ['CPA', d.stats?.cpa != null ? `¥${Number(d.stats.cpa).toFixed(2)}` : '—'],
               ['天数', `${d.stats?.days ?? 0}`]] as const).map(([k, v]) => (
              <div key={k}>
                <div className="font-mono text-lg font-bold">{v}</div>
                <div className="text-xs text-muted-foreground">{k}</div>
              </div>
            ))}
            {d.stats?.platforms && (
              <div className="self-center text-xs text-muted-foreground">
                {d.stats.platforms.split(',').map((p) => p === 'douyin' ? '抖音' : '小红书').join(' + ')}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* 4 状态流转 */}
      <Card>
        <CardHeader className="pb-1"><CardTitle className="text-sm">状态流转</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <StageFlow flow={d.stage_flow} reason={reason} />
          <div className="border-t pt-2">
            <div className="mb-1 text-xs font-medium text-muted-foreground">流转记录（审计）</div>
            {d.timeline.length ? (
              <div className="space-y-1 text-xs">
                {d.timeline.map((t, i) => (
                  <div key={i} className="flex gap-3">
                    <span className="font-mono text-muted-foreground">{t.ts.slice(0, 19)}</span>
                    <span>{t.action}</span>
                    <Badge variant="outline">{t.verdict}</Badge>
                    <span className="text-muted-foreground">{t.reason}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">
                暂无流转记录（种子数据未产生审计；真实流转走 /actions/check 裁决后落审计）
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* 5 收益 + 素材明细 */}
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-sm">收益与素材明细</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {marginEst && (
            <div className="flex items-center gap-4 text-xs">
              <span>预估毛利额 <b className="font-mono text-foreground">{marginEst}</b></span>
              <span className="text-muted-foreground">= 预算 × 毛利率（估）</span>
            </div>
          )}
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 font-medium">素材</th><th className="py-2 font-medium">平台</th>
                <th className="py-2 font-medium">消耗</th><th className="py-2 font-medium">CTR</th>
                <th className="py-2 font-medium">CVR</th><th className="py-2 font-medium">CPA</th>
              </tr>
            </thead>
            <tbody>
              {d.creatives.map((cr) => (
                <tr key={cr.id} className="border-b last:border-0">
                  <td className="py-2">
                    <Link to={`/graph?focus=${encodeURIComponent(cr.id)}`} className="text-primary hover:underline">
                      {cr.name}
                    </Link>
                  </td>
                  <td className="py-2 text-xs text-muted-foreground">
                    {(cr.metrics?.platforms || '').split(',').filter(Boolean)
                      .map((p) => p === 'douyin' ? '抖音' : '小红书').join('+') || '—'}
                  </td>
                  <td className="py-2 font-mono">{yuan(cr.metrics?.cost)}</td>
                  <td className="py-2 font-mono">{pct(cr.metrics?.ctr)}</td>
                  <td className="py-2 font-mono">{pct(cr.metrics?.cvr)}</td>
                  <td className="py-2 font-mono">
                    {cr.metrics?.cpa != null ? `¥${Number(cr.metrics.cpa).toFixed(2)}` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* 6 合作达人 */}
      {d.creators.length > 0 && (
        <Card>
          <CardHeader className="pb-1"><CardTitle className="text-sm">合作达人</CardTitle></CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {d.creators.map((cr) => (
              <Link key={cr.id} to={`/creators/${encodeURIComponent(cr.id)}`}
                    className="rounded-lg border p-3 transition-colors hover:border-primary/50">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium">{cr.name}</span>
                  <span className="font-mono text-xs">¥{cr.quote_20s.toLocaleString('zh-CN')}</span>
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {cr.niches.slice(0, 3).join(' · ')} · 粉丝 {wan(cr.followers)}
                </div>
              </Link>
            ))}
          </CardContent>
        </Card>
      )}

      {/* 2 内容 */}
      {d.docs.length > 0 && (
        <Card>
          <CardHeader className="pb-1"><CardTitle className="text-sm">案例内容（入库文档）</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {d.docs.map((doc, i) => (
              <div key={i} className="rounded-md bg-muted/40 p-3 text-sm leading-relaxed whitespace-pre-wrap">
                {doc.text}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
