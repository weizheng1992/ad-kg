// 应用骨架（spec §4）：侧边栏导航（按角色显隐）+ 顶栏身份 + 内容区 Outlet
import { NavLink, Outlet, useNavigate } from 'react-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { AgentDock } from '@/features/agent/AgentDock'
import { NAV, ROLE_LABEL } from '@/lib/nav'
import { useSession } from '@/lib/session'

export function AppLayout() {
  const { session, logout } = useSession()
  const navigate = useNavigate()
  if (!session) return null
  const items = NAV.filter((n) => n.roles.includes(session.role))

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="flex w-52 shrink-0 flex-col border-r bg-card">
        <div className="border-b px-5 py-4">
          <div className="text-lg font-extrabold tracking-wide">AdKG</div>
          <div className="text-[11px] text-muted-foreground">本体驱动的广告营销知识中台</div>
        </div>
        <nav className="flex-1 space-y-0.5 p-2.5">
          {items.map((n) => n.ready === false ? (
            <span key={n.to}
                  className="flex cursor-not-allowed items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted-foreground/60">
              <n.icon className="size-4" />{n.label}
              <Badge variant="outline" className="ml-auto px-1.5 py-0 text-[10px]">建设中</Badge>
            </span>
          ) : (
            <NavLink key={n.to} to={n.to} end={n.to === '/'} onClick={(e) => { if (n.external) { e.preventDefault(); window.open(n.external, '_blank') } }}
                     className={({ isActive }) => `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm ${isActive ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}>
              <n.icon className="size-4" />{n.label}
            </NavLink>
          ))}
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
