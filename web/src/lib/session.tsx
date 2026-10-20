// 会话上下文：登录/退出全应用唯一入口（routes 守卫与页面都从这里读）
import { createContext, useContext, useState, type ReactNode } from 'react'
import type { Persona } from '@/lib/api'
import { clearSession, loadSession, saveSession, type Session } from '@/lib/accounts'

interface SessionCtx {
  session: Session | null
  login: (s: Session) => void
  logout: () => void
  /** 切换演示身份（管理员/管理层）：写回 session，刷新不丢（README §9.7） */
  switchPersona: (p: Persona) => void
}

const Ctx = createContext<SessionCtx>({
  session: null,
  login: () => {},
  logout: () => {},
  switchPersona: () => {},
})

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadSession)

  const value: SessionCtx = {
    session,
    login: (s) => { saveSession(s); setSession(s) },
    logout: () => { clearSession(); setSession(null) },
    switchPersona: (p) => {
      setSession((s) => {
        if (!s) return s
        const next = { ...s, persona: p }
        saveSession(next)
        return next
      })
    },
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSession(): SessionCtx {
  return useContext(Ctx)
}
