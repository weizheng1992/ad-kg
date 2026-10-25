// 菜单管理（spec §18.5/§19 table-tree）：页面行（改名/图标白名单内更换/排序/启停）+
// 按钮子行（改名/启停）；给角色分配菜单与按钮在「权限管理」（同源数据转置）
import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { TableCell } from '@/components/ui/table'
import { MenuTreeTable } from './components/MenuTreeTable'
import { getAdminMenus, saveMenus, type MenuDef } from '@/lib/api'
import { ICONS } from '@/lib/nav'

/** 图标可选集 = nav.tsx ICONS 键（与后端 _ICONS 白名单同源，spec §19：白名单内可换） */
const ICON_OPTIONS = Object.keys(ICONS)

const EnabledBadge = ({ on, onToggle }: { on: boolean; onToggle: () => void }) => (
  <button onClick={onToggle}>
    <Badge variant={on ? 'secondary' : 'destructive'} className="cursor-pointer">
      {on ? '启用' : '停用'}
    </Badge>
  </button>
)

export function MenuPage() {
  const [items, setItems] = useState<MenuDef[] | null>(null)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const load = () => getAdminMenus().then((r) => setItems(r.items)).catch((e) => setError(`${e}`))
  useEffect(() => { void load() }, [])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  if (!items) return <div className="p-6 text-sm text-muted-foreground">加载中…</div>

  const patch = (path: string, fn: (m: MenuDef) => MenuDef) =>
    setItems((prev) => (prev ?? []).map((m) => (m.path === path ? fn(m) : m)))

  /** 页面节点上移/下移：交换相邻页面条 sort，按钮条随 parent 走（保存时同步写回） */
  const move = (path: string, delta: number) => {
    setItems((prev) => {
      const arr = [...(prev ?? [])]
      const order = arr.filter((m) => m.type !== 'button')
      const oi = order.findIndex((m) => m.path === path)
      const oj = oi + delta
      if (oj < 0 || oj >= order.length) return prev
      const a = order[oi], b = order[oj]
      const sa = arr.find((m) => m.path === a.path)!.sort
      arr.find((m) => m.path === a.path)!.sort = arr.find((m) => m.path === b.path)!.sort
      arr.find((m) => m.path === b.path)!.sort = sa
      return arr
    })
  }

  const save = async () => {
    setBusy(true); setMsg('')
    try {
      await saveMenus(items)
      setMsg('✅ 已保存（侧边栏与按钮显隐即时生效；变更落审计）')
      load()
    } catch (e) {
      setMsg(`❌ ${e}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-bold">菜单管理</h2>
        <span className="text-xs text-muted-foreground">
          页面 → 按钮两级树表：页面排序 / 改名 / 图标 / 启停，按钮（页面内操作）改名 / 启停；
          给角色分配菜单与按钮在
          <a href="/permissions" className="mx-1 text-primary hover:underline">权限管理</a>
        </span>
        <Button size="sm" className="ml-auto" disabled={busy} onClick={save}>
          {busy ? '保存中…' : '保存'}
        </Button>
      </div>
      {msg && <div className="rounded-md bg-muted/60 p-2.5 text-xs">{msg}</div>}

      <Card>
        <CardContent className="p-0">
          <MenuTreeTable
            menus={items}
            columns={['菜单名', '类型', '图标', '排序', '路径 / action_key', '启停']}
            renderPage={(m) => (
              <>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <Input className="h-8 w-40 text-sm" value={m.label}
                           onChange={(e) => patch(m.path, (x) => ({ ...x, label: e.target.value }))} />
                  </div>
                </TableCell>
                <TableCell><Badge variant="outline" className="font-normal">页面</Badge></TableCell>
                <TableCell>
                  <Select value={m.icon}
                          onValueChange={(v) => patch(m.path, (x) => ({ ...x, icon: v }))}>
                    <SelectTrigger size="sm" className="w-44">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ICON_OPTIONS.map((name) => {
                        const Icon = ICONS[name] ?? ICONS.Menu
                        return (
                          <SelectItem key={name} value={name}>
                            <Icon className="size-3.5" />{name}
                          </SelectItem>
                        )
                      })}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button variant="ghost" size="icon-xs" aria-label="上移"
                            onClick={() => move(m.path, -1)}><ArrowUp className="size-3.5" /></Button>
                    <Button variant="ghost" size="icon-xs" aria-label="下移"
                            onClick={() => move(m.path, 1)}><ArrowDown className="size-3.5" /></Button>
                  </div>
                </TableCell>
                <TableCell className="font-mono text-[11px] text-muted-foreground">{m.path}</TableCell>
                <TableCell>
                  <EnabledBadge on={m.enabled}
                                onToggle={() => patch(m.path, (x) => ({ ...x, enabled: !x.enabled }))} />
                </TableCell>
              </>
            )}
            renderButton={(b) => (
              <>
                <TableCell>
                  <Input className="h-7 w-40 text-xs" value={b.label}
                         onChange={(e) => patch(b.path, (x) => ({ ...x, label: e.target.value }))} />
                </TableCell>
                <TableCell><Badge variant="secondary" className="font-normal">按钮</Badge></TableCell>
                <TableCell><span className="text-xs text-muted-foreground">—</span></TableCell>
                <TableCell><span className="text-xs text-muted-foreground">—</span></TableCell>
                <TableCell className="font-mono text-[11px] text-muted-foreground">{b.action_key}</TableCell>
                <TableCell>
                  <EnabledBadge on={b.enabled}
                                onToggle={() => patch(b.path, (x) => ({ ...x, enabled: !x.enabled }))} />
                </TableCell>
              </>
            )}
            hint={<>按钮可见性 = 角色是否持有对应操作权限（在「权限管理」按角色勾选）；图标白名单内可换，其余列后端强校验</>}
          />
        </CardContent>
      </Card>
      <p className="text-[11px] text-muted-foreground">
        path 与图标白名单锁定（新增菜单项 = 新增路由与后端权限，走开发流程）；
        「菜单管理」自身不可对运维停用（防自锁，后端强校验）
      </p>
    </div>
  )
}
