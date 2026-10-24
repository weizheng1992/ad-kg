// 管理后台（spec §7，只读三件套）：权限矩阵 / 账号一览 / 审计流水——management/admin 专属
import { useCallback, useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ROLE_LABEL } from '@/lib/nav'
import { getAdminAccounts, getAuditLog, getPermissionMatrix,
         type AdminAccount, type AuditRow, type PermissionMatrix } from '@/lib/api'

const VERDICT_COLOR: Record<string, string> = {
  allow: 'bg-emerald-100 text-emerald-700', deny: 'bg-red-100 text-red-700',
  filtered: 'bg-amber-100 text-amber-700', info: 'bg-muted text-muted-foreground',
}

function MatrixTab({ m }: { m: PermissionMatrix | null }) {
  if (!m) return <div className="p-4 text-sm text-muted-foreground">加载中…</div>
  return (
    <Card>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/40 text-left">
              {['角色', '类白名单', '属性 deny / allow', '指标 deny / allow', '动作', '行过滤'].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(m.roles).map(([name, r]) => (
              <tr key={name} className="border-b align-top last:border-0">
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <b>{ROLE_LABEL[name] ?? name}</b>
                  {r.external && <Badge variant="destructive" className="ml-1">外部</Badge>}
                </td>
                <td className="px-3 py-2.5">
                  {r.classes.map((c) => <Badge key={c} variant="outline" className="m-0.5 font-normal">{c}</Badge>)}
                </td>
                <td className="px-3 py-2.5 font-mono">
                  {r.deny_properties.length > 0 && <div className="text-red-600">deny: {r.deny_properties.join(', ')}</div>}
                  {r.allow_properties.length > 0 && <div className="text-emerald-700">allow: {r.allow_properties.join(', ')}</div>}
                  {!r.deny_properties.length && !r.allow_properties.length && <span className="text-muted-foreground">—</span>}
                </td>
                <td className="px-3 py-2.5 font-mono">
                  {r.metrics_deny.length > 0 && <div className="text-red-600">deny: {r.metrics_deny.join(', ')}</div>}
                  {r.metrics_allow.length > 0 && <div className="text-emerald-700">allow: {r.metrics_allow.join(', ')}</div>}
                  {!r.metrics_deny.length && !r.metrics_allow.length && <span className="text-muted-foreground">全部</span>}
                </td>
                <td className="px-3 py-2.5 font-mono">{r.actions.join(', ')}</td>
                <td className="px-3 py-2.5 font-mono text-muted-foreground">{r.row_filter || '无（全量）'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

function AccountsTab({ items }: { items: AdminAccount[] | null }) {
  if (!items) return <div className="p-4 text-sm text-muted-foreground">加载中…</div>
  return (
    <Card>
      <CardContent className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              {['账号', '姓名', '角色', 'Person 绑定', '状态', '创建时间'].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id} className="border-b last:border-0">
                <td className="px-3 py-2.5 font-mono">{a.username}</td>
                <td className="px-3 py-2.5">{a.display_name}</td>
                <td className="px-3 py-2.5"><Badge variant="outline">{ROLE_LABEL[a.role] ?? a.role}</Badge></td>
                <td className="px-3 py-2.5 font-mono text-xs text-muted-foreground">{a.person ?? '—'}</td>
                <td className="px-3 py-2.5">{a.disabled ? <Badge variant="destructive">停用</Badge> : <Badge variant="secondary">正常</Badge>}</td>
                <td className="px-3 py-2.5 text-xs text-muted-foreground">{a.created_at.slice(0, 19)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="px-3 py-2 text-[11px] text-muted-foreground">
          最小账号面：开户/改密走 scripts/init_users.py，不做用户管理 UI（README §9.7）
        </p>
      </CardContent>
    </Card>
  )
}

function AuditTab({ rows, total, page, size, onPage }: {
  rows: AuditRow[]; total: number; page: number; size: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size))
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="flex items-center gap-3 text-sm">
          审计流水
          <span className="text-xs font-normal text-muted-foreground">
            共 {total} 条（只追加，§八）——第 {page} / {pages} 页
          </span>
          <div className="ml-auto flex gap-1.5">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>上一页</Button>
            <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页</Button>
          </div>
        </CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/40 text-left">
              {['时间', '身份', '动作', '对象', '结果'].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b last:border-0">
                <td className="px-3 py-2 whitespace-nowrap font-mono">{r.ts.slice(0, 19)}</td>
                <td className="px-3 py-2 whitespace-nowrap">
                  {r.user_id ?? '—'}
                  <Badge variant="outline" className="ml-1 font-normal">{r.role}</Badge>
                </td>
                <td className="px-3 py-2 font-mono">{r.action}</td>
                <td className="max-w-[22rem] truncate px-3 py-2" title={r.target ?? ''}>{r.target ?? '—'}</td>
                <td className="px-3 py-2">
                  <Badge className={VERDICT_COLOR[r.verdict ?? ''] ?? ''}>{r.verdict ?? '—'}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

export function AdminPage() {
  const [m, setM] = useState<PermissionMatrix | null>(null)
  const [accounts, setAccounts] = useState<AdminAccount[] | null>(null)
  const [audit, setAudit] = useState<{ rows: AuditRow[]; total: number; page: number } | null>(null)
  const [error, setError] = useState('')

  const loadAudit = useCallback(async (p: number) => {
    try {
      const r = await getAuditLog(p)
      setAudit({ rows: r.items, total: r.total, page: r.page })
    } catch (e) {
      setError(`${e}`)
    }
  }, [])

  useEffect(() => {
    getPermissionMatrix().then(setM).catch((e) => setError(`${e}`))
    getAdminAccounts().then((r) => setAccounts(r.items)).catch((e) => setError(`${e}`))
    void loadAudit(1)
  }, [loadAudit])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  return (
    <div className="space-y-4 p-6">
      <div className="flex items-baseline gap-3">
        <h2 className="text-base font-bold">管理后台</h2>
        <span className="text-xs text-muted-foreground">
          只读三件套——权限矩阵即 permissions.yaml 的可视化，审计只追加
        </span>
      </div>
      <Tabs defaultValue="matrix">
        <TabsList>
          <TabsTrigger value="matrix">权限矩阵</TabsTrigger>
          <TabsTrigger value="accounts">账号一览</TabsTrigger>
          <TabsTrigger value="audit">审计流水</TabsTrigger>
        </TabsList>
        <TabsContent value="matrix"><MatrixTab m={m} /></TabsContent>
        <TabsContent value="accounts"><AccountsTab items={accounts} /></TabsContent>
        <TabsContent value="audit">
          {audit && (
            <AuditTab rows={audit.rows} total={audit.total} page={audit.page}
                      size={30} onPage={loadAudit} />
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
