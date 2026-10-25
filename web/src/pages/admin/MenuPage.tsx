// 菜单管理（spec §17，admin 专属）：侧边栏菜单项的可见角色 / 排序 / 改名 / 启停
// path 与 icon 白名单锁定（对应真实路由），不开放增删；/menus 自身防自锁（后端校验）
import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp } from 'lucide-react'
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

  const load = () => getAdminMenus().then((r) => setItems(r.items)).catch((e) => setError(`${e}`))
  useEffect(() => { void load() }, [])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  if (!items) return <div className="p-6 text-sm text-muted-foreground">加载中…</div>

  const patch = (path: string, fn: (m: MenuDef) => MenuDef) =>
    setItems((prev) => prev!.map((m) => (m.path === path ? fn(m) : m)))
  const move = (idx: number, delta: number) => {
    setItems((prev) => {
      const arr = [...prev!]
      const j = idx + delta
      if (j < 0 || j >= arr.length) return prev
      ;[arr[idx], arr[j]] = [arr[j], arr[idx]]
      const step = Math.min(...arr.map((x) => x.sort)) >= 0 ? 10 : 0
      return arr.map((m, i) => ({ ...m, sort: step + i * 10 }))
    })
  }

  const save = async () => {
    setBusy(true); setMsg('')
    try {
      await saveMenus(items)
      setMsg('✅ 已保存（侧边栏即时生效；变更落审计）')
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
          菜单项排序 / 名称 / 启停——给角色分配菜单在「权限管理」，菜单可见性是导航层不是权限闸
        </span>
        <Button size="sm" className="ml-auto" disabled={busy} onClick={save}>
          {busy ? '保存中…' : '保存'}
        </Button>
      </div>
      {msg && <div className="rounded-md bg-muted/60 p-2.5 text-xs">{msg}</div>}

      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
                <th className="px-3 py-2 font-medium">排序</th>
                <th className="px-3 py-2 font-medium">菜单项</th>
                <th className="px-3 py-2 font-medium">名称</th>
                <th className="px-3 py-2 font-medium">可见角色</th>
                <th className="px-3 py-2 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {items.map((m, idx) => {
                const Icon = ICONS[m.icon] ?? ICONS.Menu
                return (
                  <tr key={m.path} className="border-b align-top last:border-0">
                    <td className="px-3 py-2.5">
                      <div className="flex gap-1">
                        <Button variant="ghost" size="sm" className="h-6 w-6 p-0"
                                onClick={() => move(idx, -1)}><ArrowUp className="size-3.5" /></Button>
                        <Button variant="ghost" size="sm" className="h-6 w-6 p-0"
                                onClick={() => move(idx, 1)}><ArrowDown className="size-3.5" /></Button>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5">
                      <Icon className="mr-1.5 inline size-4 text-muted-foreground" />
                      <span className="font-mono text-xs">{m.path}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <Input className="h-8 w-36 text-sm" value={m.label}
                             onChange={(e) => patch(m.path, (x) => ({ ...x, label: e.target.value }))} />
                    </td>
                    <td className="px-3 py-2.5">
                      <button onClick={() => patch(m.path, (x) => ({ ...x, enabled: !x.enabled }))}>
                        <Badge variant={m.enabled ? 'secondary' : 'destructive'}
                               className="cursor-pointer">
                          {m.enabled ? '启用' : '停用'}
                        </Badge>
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <p className="text-[11px] text-muted-foreground">
        path 与图标白名单锁定（新增菜单项 = 新增路由与后端权限，走开发流程）；
        「菜单管理」自身不可对运维停用（防自锁，后端强校验）
      </p>
    </div>
  )
}
