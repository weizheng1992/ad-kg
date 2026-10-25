// 权限管理（spec §18 RBAC 角色工作台）：左角色列表（系统+自定义+新建），
// 右选中角色——基本信息 / 可见菜单勾选（写 app_menu.roles）/ 按钮权限勾选
// （写 app_role_action）/ 占用账号。数据面（类/指标/行过滤）真源 permissions.yaml，
// 自定义角色数据面继承基角色（页内明示）。
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { createRole, deleteRole, getAdminMenus, listRoles, saveMenus, updateRole,
         type MenuDef, type RoleDef } from '@/lib/api'
import { ROLE_LABEL } from '@/lib/nav'

const roleLabel = (r: RoleDef) => ROLE_LABEL[r.name] ?? r.label

export function PermissionsPage() {
  const [roles, setRoles] = useState<RoleDef[] | null>(null)
  const [menus, setMenus] = useState<MenuDef[]>([])
  const [sel, setSel] = useState<string>('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState({ name: '', label: '', base_role: 'ae', description: '' })

  const load = useCallback(() => {
    listRoles().then((r) => {
      setRoles(r.items)
      setSel((s) => (r.items.some((x) => x.name === s) ? s : (r.items[0]?.name ?? '')))
    }).catch((e) => setMsg(`❌ ${e}`))
    getAdminMenus().then((r) => setMenus(r.items)).catch(() => setMenus([]))
  }, [])
  useEffect(() => { void load() }, [load])

  if (!roles) return <div className="p-6 text-sm text-muted-foreground">加载中…</div>
  const role = roles.find((r) => r.name === sel)
  const actionsAll = roles.find((r) => r.actions_all)?.actions_all ?? {}
  const isCustom = role?.source === 'custom'

  /** 角色菜单勾选：写 app_menu.roles（菜单管理同源数据，转置视图） */
  const toggleMenu = (path: string) => {
    setMenus((prev) => prev.map((m) => (m.path === path ? {
      ...m,
      roles: m.roles.includes(sel) ? m.roles.filter((r) => r !== sel)
        : [...m.roles, sel],
    } : m)))
  }
  const toggleAction = (a: string) => {
    setRoles((prev) => (prev ?? []).map((r) => (r.name === sel ? {
      ...r, actions: r.actions.includes(a) ? r.actions.filter((x) => x !== a)
        : [...r.actions, a],
    } : r)))
  }
  const save = async () => {
    if (!role) return
    setBusy(true); setMsg('')
    try {
      await updateRole(role.name, { label: roleLabel(role), description: role.description,
                                    actions: role.actions })
      await saveMenus(menus)
      setMsg('✅ 已保存（菜单 + 按钮权限；变更落审计）')
      load()
    } catch (e) {
      setMsg(`❌ ${e}`)
    } finally {
      setBusy(false)
    }
  }
  const doCreate = async () => {
    setBusy(true); setMsg('')
    try {
      await createRole(draft)
      setMsg(`✅ 角色 ${draft.name} 已创建（数据面继承 ${draft.base_role}）`)
      setCreating(false); setDraft({ ...draft, name: '', label: '', description: '' })
      load()
    } catch (e) {
      setMsg(`❌ ${e}`)
    } finally {
      setBusy(false)
    }
  }
  const doDelete = async () => {
    if (!role || !isCustom) return
    if (!window.confirm(`删除角色 ${role.name}？`)) return
    try {
      await deleteRole(role.name)
      setMsg('✅ 已删除'); setSel(''); load()
    } catch (e) { setMsg(`❌ ${e}`) }
  }

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-bold">权限管理</h2>
        <span className="text-xs text-muted-foreground">
          角色 → 分配菜单与按钮权限；数据面（类/指标/行过滤）真源 permissions.yaml，
          自定义角色数据面继承基角色；账号分配角色去
          <Link to="/people" className="mx-1 text-primary hover:underline">人员管理</Link>
        </span>
        <Button size="sm" className="ml-auto" disabled={busy || !role} onClick={save}>
          {busy ? '保存中…' : '保存当前角色'}
        </Button>
      </div>
      {msg && <div className="rounded-md bg-muted/60 p-2.5 text-xs">{msg}</div>}

      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <Card className="h-fit">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm">角色（{roles.length}）</CardTitle>
            <Button size="sm" variant="outline" className="h-7"
                    onClick={() => setCreating(!creating)}>新建</Button>
          </CardHeader>
          <CardContent className="space-y-1">
            {creating && (
              <div className="mb-2 space-y-1.5 rounded-md border p-2.5">
                <Input className="h-8 text-xs" placeholder="角色名（如 auditor）"
                       value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                <Input className="h-8 text-xs" placeholder="显示名"
                       value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />
                <select className="h-8 w-full rounded-md border bg-background px-2 text-xs"
                        value={draft.base_role}
                        onChange={(e) => setDraft({ ...draft, base_role: e.target.value })}>
                  {roles.filter((r) => r.source === 'system').map((r) => (
                    <option key={r.name} value={r.name}>基于 {roleLabel(r)}（{r.name}）</option>
                  ))}
                </select>
                <Button size="sm" className="h-7 w-full" disabled={busy || !draft.name}
                        onClick={doCreate}>创建</Button>
              </div>
            )}
            {roles.map((r) => (
              <button key={r.name} onClick={() => setSel(r.name)}
                      className={`flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm ${
                        sel === r.name ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'}`}>
                <span className="flex-1 truncate">{roleLabel(r)}</span>
                <span className={`rounded px-1 text-[10px] ${sel === r.name ? '' : 'text-muted-foreground'}`}>
                  {r.source === 'system' ? '系统' : '自定义'}
                </span>
                {r.used > 0 && <Badge variant="secondary" className="px-1 text-[10px]">{r.used}人</Badge>}
              </button>
            ))}
          </CardContent>
        </Card>

        {role && (
          <div className="space-y-4">
            <Card>
              <CardHeader className="pb-1"><CardTitle className="text-sm">基本信息</CardTitle></CardHeader>
              <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
                <div>角色名：<b className="font-mono">{role.name}</b></div>
                <div>数据面基角色：<Badge variant="outline">{role.base_role}</Badge>
                  {isCustom && <span className="ml-1 text-xs text-muted-foreground">（继承）</span>}</div>
                <div>占用账号：{role.used} 个</div>
                <div className="flex flex-wrap items-center gap-2 sm:col-span-3">
                  <span className="text-xs text-muted-foreground">显示名</span>
                  <Input className="h-8 w-40 text-sm" value={roleLabel(role)}
                         onChange={(e) => setRoles((p) => (p ?? []).map((r) =>
                           r.name === sel ? { ...r, label: e.target.value } : r))} />
                  <span className="text-xs text-muted-foreground">说明</span>
                  <Input className="h-8 min-w-40 flex-1 text-sm" value={role.description}
                         onChange={(e) => setRoles((p) => (p ?? []).map((r) =>
                           r.name === sel ? { ...r, description: e.target.value } : r))} />
                  {isCustom && <Button size="sm" variant="destructive" onClick={doDelete}>删除角色</Button>}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-sm">按钮 / 操作权限（{role.actions.length}/{Object.keys(actionsAll).length}）</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-1.5">
                {Object.entries(actionsAll).map(([a, label]) => (
                  <button key={a} onClick={() => toggleAction(a)}
                          className={`rounded-md px-2.5 py-1 text-xs ${role.actions.includes(a)
                            ? 'bg-primary text-primary-foreground' : 'border text-muted-foreground'}`}>
                    {label}
                  </button>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-sm">可见菜单（勾选后该角色侧边栏可见）</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                {menus.map((m) => (
                  <button key={m.path} onClick={() => toggleMenu(m.path)}
                          className={`flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs ${
                            m.roles.includes(sel) ? 'bg-primary/10 text-primary' : 'text-muted-foreground'}`}>
                    <span className={`size-2 rounded-full ${m.roles.includes(sel) ? 'bg-primary' : 'bg-muted-foreground/30'}`} />
                    {m.label}
                    <span className="ml-auto font-mono text-[10px] opacity-60">{m.path}</span>
                  </button>
                ))}
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  )
}
