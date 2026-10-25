// 人员管理独立页（spec §16）：侧边栏直达——账号一览 + admin 专属开户/改密/启停
import { useCallback, useEffect, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { createAccount, getAdminAccounts, getPermissionMatrix,
         resetAccountPassword, toggleAccount,
         type AdminAccount, type PermissionMatrix } from '@/lib/api'
import { ROLE_LABEL } from '@/lib/nav'
import { useSession } from '@/lib/session'

/** 人员管理（spec §16）：账号一览 + admin 专属写操作（开户/改密/启停） */
export function AccountsTab({ items, roles, canWrite, onChanged }: {
  items: AdminAccount[] | null; roles: string[]; canWrite: boolean; onChanged: () => void
}) {
  const [form, setForm] = useState({ username: '', password: '', display_name: '',
                                     role: 'ae', person: '' })
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  if (!items) return <div className="p-4 text-sm text-muted-foreground">加载中…</div>

  const submit = async () => {
    setBusy(true); setMsg('')
    try {
      await createAccount(form)
      setMsg(`✅ 已开户 ${form.username}（角色 ${ROLE_LABEL[form.role] ?? form.role}）`)
      setForm({ ...form, username: '', password: '', display_name: '', person: '' })
      onChanged()
    } catch (e) {
      setMsg(`❌ ${e}`)
    } finally {
      setBusy(false)
    }
  }
  const resetPw = async (a: AdminAccount) => {
    const pw = window.prompt(`给 ${a.display_name}（${a.username}）设置新密码：`)
    if (!pw) return
    try {
      await resetAccountPassword(a.id, pw)
      setMsg(`✅ ${a.username} 已改密（既有会话已吊销）`)
    } catch (e) { setMsg(`❌ ${e}`) }
  }
  const toggle = async (a: AdminAccount) => {
    try {
      await toggleAccount(a.id, !a.disabled)
      setMsg(`✅ ${a.username} 已${a.disabled ? '启用' : '停用（会话吊销）'}`)
      onChanged()
    } catch (e) { setMsg(`❌ ${e}`) }
  }

  return (
    <div className="space-y-3">
      {canWrite && (
        <Card>
          <CardContent className="grid gap-3 py-4 sm:grid-cols-5">
            {([['username', '账号 *'], ['password', '初始密码 *'], ['display_name', '姓名'],
               ['person', 'Person 绑定（可空）']] as const).map(([k, label]) => (
              <div key={k} className="grid gap-1">
                <span className="text-xs text-muted-foreground">{label}</span>
                <Input value={(form as Record<string, string>)[k]}
                       onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
              </div>
            ))}
            <div className="grid gap-1">
              <span className="text-xs text-muted-foreground">角色 *</span>
              <select className="h-9 rounded-md border bg-background px-2 text-sm"
                      value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r] ?? r}</option>)}
              </select>
            </div>
            <div className="flex items-end gap-2 sm:col-span-5">
              <Button size="sm" disabled={busy || !form.username || !form.password}
                      onClick={submit}>{busy ? '提交中…' : '开户'}</Button>
              <span className="text-xs text-muted-foreground">
                密码 scrypt 哈希入库；停用即吊销会话；一切操作落审计
              </span>
              {msg && <span className="text-xs">{msg}</span>}
            </div>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                {['账号', '姓名', '角色', 'Person 绑定', '状态', '创建时间', ...(canWrite ? ['操作'] : [])].map((h) => (
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
                  {canWrite && (
                    <td className="px-3 py-2.5">
                      <div className="flex gap-1">
                        <Button variant="outline" size="sm" className="h-7 px-2 text-[11px]"
                                onClick={() => void resetPw(a)}>改密</Button>
                        <Button variant="outline" size="sm" className="h-7 px-2 text-[11px]"
                                onClick={() => void toggle(a)}>{a.disabled ? '启用' : '停用'}</Button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  )
}




export function PeoplePage() {
  const { session } = useSession()
  const [items, setItems] = useState<AdminAccount[] | null>(null)
  const [m, setM] = useState<PermissionMatrix | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    getAdminAccounts().then((r) => setItems(r.items)).catch((e) => setError(`${e}`))
  }, [])

  useEffect(() => {
    load()
    getPermissionMatrix().then(setM).catch((e) => setError(`${e}`))
  }, [load])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-bold">人员管理</h2>
        <span className="text-xs text-muted-foreground">
          账号 · 角色 · Person 绑定——开户/改密/停启用为 admin 专属（改密与停用即吊销会话），management 只读
        </span>
      </div>
      <AccountsTab items={items} roles={m ? Object.keys(m.roles) : []}
                   canWrite={session?.role === 'admin'} onChanged={load} />
    </div>
  )
}
