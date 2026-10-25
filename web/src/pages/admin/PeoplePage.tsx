// 人员管理独立页（spec §16/§19）：搜索 + 角色筛选 + shadcn Table；
// 开户 / 改密走 Dialog（废 window.prompt）；行内角色改绑与停启用保留；
// 写门 canWrite = useCan('account_manage')——与后端 role_allows 同一 action 词表
import { useCallback, useEffect, useMemo, useState } from 'react'
import { KeyRound, UserPlus } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader,
         DialogTitle } from '@/components/ui/dialog'
import { createAccount, getAdminAccounts, listRoles, resetAccountPassword,
         setAccountRole, toggleAccount,
         type AdminAccount, type RoleDef } from '@/lib/api'
import { ROLE_LABEL } from '@/lib/nav'
import { useCan } from '@/lib/session'

const roleText = (r: RoleDef) =>
  `${ROLE_LABEL[r.name] ?? r.label}${r.source === 'custom' ? '（自定义）' : ''}`

export function PeoplePage() {
  const canWrite = useCan('account_manage')
  const [items, setItems] = useState<AdminAccount[] | null>(null)
  const [roles, setRoles] = useState<RoleDef[]>([])
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  // 筛选（spec §19）：账号/姓名模糊 + 角色等值
  const [q, setQ] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  // 开户 / 改密 Dialog
  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState({ username: '', password: '', display_name: '',
                                     role: 'ae', person: '' })
  const [resetTarget, setResetTarget] = useState<AdminAccount | null>(null)
  const [newPw, setNewPw] = useState('')
  // 弹窗内错误（审查修复）：出错时 Dialog 不关，错误文案须在遮罩内可见——
  // 页顶 msg 会被模态盖住
  const [dlgErr, setDlgErr] = useState('')

  const load = useCallback(() => {
    getAdminAccounts().then((r) => setItems(r.items)).catch((e) => setError(`${e}`))
  }, [])

  useEffect(() => {
    load()
    listRoles().then((r) => setRoles(r.items)).catch((e) => setError(`${e}`))
  }, [load])

  const kw = q.trim().toLowerCase()
  const shown = useMemo(() => (items ?? []).filter((a) =>
    (roleFilter === 'all' || a.role === roleFilter)
    && (!kw || a.username.toLowerCase().includes(kw)
        || a.display_name.toLowerCase().includes(kw))
  ), [items, kw, roleFilter])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>

  const submitCreate = async () => {
    setBusy(true); setMsg(''); setDlgErr('')
    try {
      await createAccount(form)
      setMsg(`✅ 已开户 ${form.username}（角色 ${ROLE_LABEL[form.role] ?? form.role}）`)
      setCreateOpen(false)
      setForm({ username: '', password: '', display_name: '', role: form.role, person: '' })
      load()
    } catch (e) {
      setDlgErr(`${e}`); setMsg(`❌ ${e}`)
    } finally {
      setBusy(false)
    }
  }
  const submitReset = async () => {
    if (!resetTarget || !newPw) return
    setBusy(true); setMsg(''); setDlgErr('')
    try {
      await resetAccountPassword(resetTarget.id, newPw)
      setMsg(`✅ ${resetTarget.username} 已改密（既有会话已吊销）`)
      setResetTarget(null); setNewPw('')
    } catch (e) {
      setDlgErr(`${e}`); setMsg(`❌ ${e}`)
    } finally {
      setBusy(false)
    }
  }
  const setRole = async (a: AdminAccount, role: string) => {
    try {
      await setAccountRole(a.id, role)
      setMsg(`✅ ${a.username} 已改绑 ${role}（会话已吊销，重新登录生效）`)
      load()
    } catch (e) { setMsg(`❌ ${e}`) }
  }
  const toggle = async (a: AdminAccount) => {
    try {
      await toggleAccount(a.id, !a.disabled)
      setMsg(`✅ ${a.username} 已${a.disabled ? '启用' : '停用（会话吊销）'}`)
      load()
    } catch (e) { setMsg(`❌ ${e}`) }
  }

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-bold">人员管理</h2>
        <span className="text-xs text-muted-foreground">
          账号 · 角色 · Person 绑定——开户/改密/停启用为 admin 专属（改密与停用即吊销会话），management 只读
        </span>
        {canWrite && (
          <Button size="sm" className="ml-auto" onClick={() => { setDlgErr(''); setCreateOpen(true) }}>
            <UserPlus className="size-3.5" />开户
          </Button>
        )}
      </div>
      {msg && <div className="rounded-md bg-muted/60 p-2.5 text-xs">{msg}</div>}

      <div className="flex flex-wrap items-center gap-2">
        <Input className="h-8 w-52 text-sm" placeholder="搜索账号 / 姓名"
               value={q} onChange={(e) => setQ(e.target.value)} />
        <Select value={roleFilter} onValueChange={setRoleFilter}>
          <SelectTrigger size="sm" className="w-44"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部角色</SelectItem>
            {roles.map((r) => <SelectItem key={r.name} value={r.name}>{roleText(r)}</SelectItem>)}
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">
          共 {shown.length} / {items?.length ?? 0} 个账号；密码 scrypt 哈希入库，一切操作落审计
        </span>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                {['账号', '姓名', '角色', 'Person 绑定', '状态', '创建时间',
                  ...(canWrite ? ['操作'] : [])].map((h) => (
                  <TableHead key={h}>{h}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map((a) => (
                <TableRow key={a.id}>
                  <TableCell className="font-mono">{a.username}</TableCell>
                  <TableCell>{a.display_name}</TableCell>
                  <TableCell>
                    {canWrite ? (
                      <Select value={a.role} onValueChange={(v) => void setRole(a, v)}>
                        <SelectTrigger size="sm" className="h-7 w-40 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {roles.map((r) => (
                            <SelectItem key={r.name} value={r.name}>{roleText(r)}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Badge variant="outline">{ROLE_LABEL[a.role] ?? a.role}</Badge>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{a.person ?? '—'}</TableCell>
                  <TableCell>{a.disabled ? <Badge variant="destructive">停用</Badge> : <Badge variant="secondary">正常</Badge>}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{a.created_at.slice(0, 19)}</TableCell>
                  {canWrite && (
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="outline" size="sm" className="h-7 px-2 text-[11px]"
                                onClick={() => { setResetTarget(a); setNewPw(''); setDlgErr('') }}>改密</Button>
                        <Button variant="outline" size="sm" className="h-7 px-2 text-[11px]"
                                onClick={() => void toggle(a)}>{a.disabled ? '启用' : '停用'}</Button>
                      </div>
                    </TableCell>
                  )}
                </TableRow>
              ))}
              {shown.length === 0 && (
                <TableRow>
                  <TableCell colSpan={canWrite ? 7 : 6}
                             className="py-6 text-center text-sm text-muted-foreground">
                    无匹配账号
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* 开户 Dialog（spec §19：表单卡改弹窗） */}
      <Dialog open={createOpen} onOpenChange={(o) => { setCreateOpen(o); if (o) setDlgErr('') }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>开户</DialogTitle>
            <DialogDescription>
              密码 scrypt 哈希入库；角色须为 RBAC 全集（系统 + 自定义）
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="pu">账号 *</Label>
              <Input id="pu" value={form.username}
                     onChange={(e) => setForm({ ...form, username: e.target.value })} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="pp">初始密码 *</Label>
              <Input id="pp" type="password" value={form.password}
                     onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="pn">姓名</Label>
              <Input id="pn" value={form.display_name}
                     onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
            </div>
            <div className="grid gap-1.5">
              <Label>角色 *</Label>
              <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v })}>
                <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {roles.map((r) => <SelectItem key={r.name} value={r.name}>{roleText(r)}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="pe">Person 绑定（可空）</Label>
              <Input id="pe" value={form.person}
                     onChange={(e) => setForm({ ...form, person: e.target.value })} />
            </div>
          </div>
          {dlgErr && <div className="rounded-md bg-destructive/10 p-2 text-xs text-red-600">{dlgErr}</div>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
            <Button disabled={busy || !form.username || !form.password}
                    onClick={() => void submitCreate()}>{busy ? '提交中…' : '开户'}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 改密 Dialog（spec §19：废 window.prompt） */}
      <Dialog open={!!resetTarget} onOpenChange={(o) => {
        if (o) setDlgErr(''); else { setResetTarget(null); setNewPw('') }
      }}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <KeyRound className="size-4" />改密
            </DialogTitle>
            <DialogDescription>
              {resetTarget && <>给 {resetTarget.display_name}（{resetTarget.username}）设置新密码；保存后既有会话全部吊销</>}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="np">新密码 *</Label>
            <Input id="np" type="password" value={newPw}
                   onChange={(e) => setNewPw(e.target.value)} />
          </div>
          {dlgErr && <div className="rounded-md bg-destructive/10 p-2 text-xs text-red-600">{dlgErr}</div>}
          <DialogFooter>
            <Button variant="outline" onClick={() => { setResetTarget(null); setNewPw('') }}>取消</Button>
            <Button disabled={busy || !newPw} onClick={() => void submitReset()}>
              {busy ? '提交中…' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
