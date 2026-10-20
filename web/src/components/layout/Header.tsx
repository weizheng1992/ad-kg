// 顶栏：品牌 + 页签 + 角色身份（业务账号锁定 / admin 可切换）+ 退出
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ROLES } from '@/lib/api'
import type { Session } from '@/lib/accounts'

export type Tab = 'ask' | 'graph'

export function Header({ tab, onTab, session, persona, onPersona, onLogout }: {
  tab: Tab
  onTab: (t: Tab) => void
  session: Session
  persona: { role: string; user: string }
  onPersona: (role: string, user: string) => void
  onLogout: () => void
}) {
  const roleByUser = (user: string) => ROLES.find((r) => r.user === user) ?? ROLES[0]

  return (
    <header className="sticky top-0 z-5 flex items-center gap-6 border-b bg-card px-7 py-3.5">
      <div className="flex items-baseline gap-2.5">
        <span className="text-xl font-extrabold tracking-wide">AdKG</span>
        <span className="text-xs text-muted-foreground">本体驱动的广告营销知识中台 · 演示</span>
      </div>

      <nav className="ml-3 flex gap-1.5">
        <Button variant={tab === 'ask' ? 'default' : 'outline'} size="sm" onClick={() => onTab('ask')}>问答</Button>
        <Button variant={tab === 'graph' ? 'default' : 'outline'} size="sm" onClick={() => onTab('graph')}>图谱</Button>
      </nav>

      <div className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
        {session.admin ? (
          <label className="flex items-center gap-2">
            当前角色
            <Select value={persona.user} onValueChange={(user) => { const r = roleByUser(user); onPersona(r.role, r.user) }}>
              <SelectTrigger size="sm" className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => (
                  <SelectItem key={r.user} value={r.user}>{r.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </label>
        ) : (
          <span>身份：<b className="text-foreground">{session.label}</b>（角色随账号绑定）</span>
        )}
        <span className="text-border">|</span>
        <span>{session.account}</span>
        <Button variant="ghost" size="sm" onClick={onLogout}>退出</Button>
      </div>
    </header>
  )
}
