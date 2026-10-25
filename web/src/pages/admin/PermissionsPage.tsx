// 权限管理（spec §18 RBAC 角色工作台 + §19 table-tree）：左角色列表（系统+自定义+新建），
// 右选中角色——基本信息 / 权限树（真 Checkbox：页面勾写 app_menu.roles、按钮勾写
// app_role_action，一次保存两处落库）；页底折叠「数据面权限矩阵」只读投影。
// 界面权限（菜单/按钮/自定义角色）真源在 DB；数据面真源 permissions.yaml——两平面分离。
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { TableCell } from '@/components/ui/table'
import { ChevronDown } from 'lucide-react'
import { MenuTreeTable } from './components/MenuTreeTable'
import { createRole, deleteRole, getAdminMenus, getPermissionMatrix, listRoles,
         saveMenus, updateRole,
         type MenuDef, type PermissionMatrix, type RoleDef } from '@/lib/api'
import { ROLE_LABEL } from '@/lib/nav'
import { useCan } from '@/lib/session'

const roleLabel = (r: RoleDef) => ROLE_LABEL[r.name] ?? r.label

/** 数据面权限矩阵（spec §19 自 AdminPage 迁入）：permissions.yaml 的只读投影 */
function MatrixView({ m }: { m: PermissionMatrix | null }) {
  if (!m) return <div className="p-4 text-sm text-muted-foreground">加载中…</div>
  return (
    <div className="overflow-x-auto">
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
    </div>
  )
}

export function PermissionsPage() {
  const canWrite = useCan('menu_manage')   // 写门（spec §19 清偿③）：本页写操作 admin 专属，词表取 menu_manage
  const [roles, setRoles] = useState<RoleDef[] | null>(null)
  const [menus, setMenus] = useState<MenuDef[]>([])
  const [sel, setSel] = useState<string>('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState({ name: '', label: '', base_role: 'ae', description: '' })
  const [matrixOpen, setMatrixOpen] = useState(false)
  const [matrix, setMatrix] = useState<PermissionMatrix | null>(null)
  const [matrixError, setMatrixError] = useState('')

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
        {!canWrite && <span className="ml-auto text-xs text-muted-foreground">只读（无 menu_manage）</span>}
        <Button size="sm" className={canWrite ? 'ml-auto' : ''} disabled={busy || !role || !canWrite}
                onClick={save}>
          {busy ? '保存中…' : '保存当前角色'}
        </Button>
      </div>
      {msg && <div className="rounded-md bg-muted/60 p-2.5 text-xs">{msg}</div>}

      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <Card className="h-fit">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm">角色（{roles.length}）</CardTitle>
            {canWrite && (
              <Button size="sm" variant="outline" className="h-7"
                      onClick={() => setCreating(!creating)}>新建</Button>
            )}
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
                  {isCustom && canWrite && <Button size="sm" variant="destructive" onClick={doDelete}>删除角色</Button>}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-1">
                <CardTitle className="text-sm">
                  权限树（页面 → 按钮；页面勾写菜单可见，按钮勾写操作权限——保存一次落两库）
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <MenuTreeTable
                  menus={menus}
                  columns={['菜单 / 按钮', '路径 / 操作权限']}
                  renderPage={(m) => (
                    <>
                      <TableCell>
                        <label className="flex cursor-pointer items-center gap-2">
                          <Checkbox checked={m.roles.includes(sel)} onCheckedChange={() => toggleMenu(m.path)} />
                          <span className="text-sm font-medium">{m.label}</span>
                        </label>
                      </TableCell>
                      <TableCell className="font-mono text-[11px] text-muted-foreground">{m.path}</TableCell>
                    </>
                  )}
                  renderButton={(b) => (
                    <>
                      <TableCell>
                        <label className="flex cursor-pointer items-center gap-2">
                          <Checkbox checked={!!b.action_key && role.actions.includes(b.action_key)}
                                    disabled={!b.action_key}
                                    onCheckedChange={() => b.action_key && toggleAction(b.action_key)} />
                          <span className="text-xs">{b.label}</span>
                        </label>
                      </TableCell>
                      <TableCell className="font-mono text-[11px] text-muted-foreground">{b.action_key}</TableCell>
                    </>
                  )}
                  hint={<>页面勾 = 侧边栏显示该入口（写菜单可见集）；按钮勾 = 该操作对角色可用（写按钮权限，后端角色门同一套判定）</>}
                />
              </CardContent>
            </Card>
          </div>
        )}
      </div>

      <Collapsible open={matrixOpen}
                   onOpenChange={(o) => {
                     setMatrixOpen(o)
                     if (o && matrix === null) {
                       getPermissionMatrix().then(setMatrix)
                         .catch((e) => setMatrixError(`${e}`))
                     }
                   }}>
        <div className="flex items-center gap-2">
          <CollapsibleTrigger asChild>
            <Button variant="outline" size="sm">
              数据面权限矩阵
              <ChevronDown className={`size-3.5 transition-transform ${matrixOpen ? 'rotate-180' : ''}`} />
            </Button>
          </CollapsibleTrigger>
          <span className="text-xs text-muted-foreground">
            数据面真源 permissions.yaml，此处只读投影——界面权限在 DB、数据面在 yaml，两平面分离（spec §19）
          </span>
        </div>
        <CollapsibleContent>
          <Card className="mt-3">
            <CardContent className="p-0">
              {matrixError
                ? <div className="p-4 text-sm text-red-600">{matrixError}</div>
                : <MatrixView m={matrix} />}
            </CardContent>
          </Card>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}
