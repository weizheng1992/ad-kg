// 菜单管理（spec §18.5）：页面→按钮两级树——页面节点排序/改名/启停，
// 按钮节点（挂其页面下）改名/启停；给角色分配在「权限管理」（同源数据转置）
import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, MousePointerClick } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { getAdminMenus, saveMenus, type MenuDef } from '@/lib/api'
import { ICONS } from '@/lib/nav'

export function MenuPage() {
  const [items, setItems] = useState<MenuDef[] | null>(null)
  const [error, setError] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const load = () => getAdminMenus().then((r) => setItems(r.items)).catch((e) => setError(`${e}`))
  useEffect(() => { void load() }, [])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  if (!items) return <div className="p-6 text-sm text-muted-foreground">加载中…</div>

  const pages = items.filter((m) => m.type !== 'button')
  const buttonsOf = (path: string) =>
    items.filter((m) => m.type === 'button' && m.parent === path)
         .sort((a, b) => a.sort - b.sort)

  const patch = (path: string, fn: (m: MenuDef) => MenuDef) =>
    setItems((prev) => (prev ?? []).map((m) => (m.path === path ? fn(m) : m)))
  const toggleCollapse = (path: string) =>
    setCollapsed((s) => { const n = new Set(s); n.has(path) ? n.delete(path) : n.add(path); return n })

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
          页面 → 按钮两级树：页面排序 / 改名 / 启停，按钮（页面内操作）改名 / 启停；
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
          <div className="divide-y">
            {pages.sort((a, b) => a.sort - b.sort).map((m) => {
              const Icon = ICONS[m.icon] ?? ICONS.Menu
              const btns = buttonsOf(m.path)
              const open = !collapsed.has(m.path)
              return (
                <div key={m.path}>
                  <div className="flex flex-wrap items-center gap-2 px-3 py-2.5">
                    <button className="text-muted-foreground" aria-label="展开/收起"
                            onClick={() => toggleCollapse(m.path)}>
                      {btns.length ? (open ? <ChevronDown className="size-4" />
                        : <ChevronRight className="size-4" />) : <span className="inline-block size-4" />}
                    </button>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="sm" className="h-6 w-6 p-0"
                              onClick={() => move(m.path, -1)}><ArrowUp className="size-3.5" /></Button>
                      <Button variant="ghost" size="sm" className="h-6 w-6 p-0"
                              onClick={() => move(m.path, 1)}><ArrowDown className="size-3.5" /></Button>
                    </div>
                    <Icon className="size-4 text-muted-foreground" />
                    <Input className="h-8 w-32 text-sm" value={m.label}
                           onChange={(e) => patch(m.path, (x) => ({ ...x, label: e.target.value }))} />
                    <span className="font-mono text-[11px] text-muted-foreground">{m.path}</span>
                    <button className="ml-auto" onClick={() => patch(m.path, (x) => ({ ...x, enabled: !x.enabled }))}>
                      <Badge variant={m.enabled ? 'secondary' : 'destructive'} className="cursor-pointer">
                        {m.enabled ? '启用' : '停用'}
                      </Badge>
                    </button>
                  </div>
                  {open && btns.length > 0 && (
                    <div className="ml-14 space-y-1.5 border-l pb-3 pl-4">
                      {btns.map((b) => (
                        <div key={b.path} className="flex items-center gap-2">
                          <MousePointerClick className="size-3.5 text-muted-foreground/70" />
                          <Input className="h-7 w-28 text-xs" value={b.label}
                                 onChange={(e) => patch(b.path, (x) => ({ ...x, label: e.target.value }))} />
                          <span className="font-mono text-[10px] text-muted-foreground">
                            {b.action_key}
                          </span>
                          <button className="ml-auto" onClick={() => patch(b.path, (x) => ({ ...x, enabled: !x.enabled }))}>
                            <Badge variant={b.enabled ? 'secondary' : 'destructive'} className="cursor-pointer text-[10px]">
                              {b.enabled ? '启用' : '停用'}
                            </Badge>
                          </button>
                        </div>
                      ))}
                      <p className="text-[10px] text-muted-foreground">
                        按钮可见性 = 角色是否持有对应操作权限（在「权限管理」按角色勾选）
                      </p>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </CardContent>
      </Card>
      <p className="text-[11px] text-muted-foreground">
        path 与图标白名单锁定（新增菜单项 = 新增路由与后端权限，走开发流程）；
        「菜单管理」自身不可对运维停用（防自锁，后端强校验）
      </p>
    </div>
  )
}
