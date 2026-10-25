// 应用骨架（spec §4/§17）：侧边栏菜单数据驱动（GET /menus，失败回落静态默认）
// + 顶栏身份 + 内容区 Outlet + Agent 悬浮窗
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { AgentDock } from '@/features/agent/AgentDock'
import { getMenus, type MenuDef } from '@/lib/api'
import { DEFAULT_NAV, ICONS, ROLE_LABEL, platformUrl } from '@/lib/nav'
import { useSession } from '@/lib/session'

export function AppLayout() {
  const { session, logout } = useSession()
  const navigate = useNavigate()
  const [menus, setMenus] = useState<MenuDef[] | null>(null)

  useEffect(() => {
    if (!session) return
    getMenus().then((r) => setMenus(r.items)).catch(() => setMenus(null))
  }, [session?.role, session])      // 角色变化即重取（菜单随角色/管理端调整实时变）

  if (!session) return null
  // 服务端菜单（含 external 标记：/platform 外链）——失败回落静态默认
  const server = menus?.map((m) => ({
    to: m.path, label: m.label, icon: m.icon,
    external: m.path === '/platform' ? platformUrl() : undefined,
  }))
  const items = (server && server.length ? server
    : DEFAULT_NAV.filter((n) => n.roles.includes(session.role)))

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="flex w-52 shrink-0 flex-col border-r bg-card">
        <div className="border-b px-5 py-4">
          <div className="text-lg font-extrabold tracking-wide">AdKG</div>
          <div className="text-[11px] text-muted-foreground">本体驱动的广告营销知识中台</div>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2.5">
          {items.map((n) => {
            const Icon = ICONS[n.icon] ?? ICONS.Menu
            return (
              <NavLink key={n.to} to={n.to} end={n.to === '/'}
                       onClick={(e) => { if (n.external) { e.preventDefault(); window.open(n.external, '_blank') } }}
                       className={({ isActive }) => `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm ${isActive ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}>
                <Icon className="size-4" />{n.label}
              </NavLink>
            )
          })}
        </nav>
        <div className="border-t p-4 text-[11px] leading-relaxed text-muted-foreground">
          同一问题不同角色得到不同的行与字段——这不是功能，是本体权限的副作用
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b bg-card px-6 py-3">
          <span className="text-sm font-semibold">{session.display_name}</span>
          <Badge variant="secondary">{ROLE_LABEL[session.role] ?? session.role}</Badge>
          {session.person && (
            <span className="font-mono text-[11px] text-muted-foreground">{session.person}</span>
          )}
          <Button variant="ghost" size="sm" className="ml-auto"
                  onClick={async () => { await logout(); navigate('/login', { replace: true }) }}>
            退出
          </Button>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto"><Outlet /></main>
      </div>
      <AgentDock />
    </div>
  )
}
