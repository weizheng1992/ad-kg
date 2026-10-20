// 会话上下文：登录/退出全应用唯一入口（routes 守卫与页面都从这里读）
import { createContext, useContext, useState, type ReactNode } from 'react'
import { clearSession, loadSession, saveSession, type Session } from '@/lib/accounts'

interface SessionCtx {
  session: Session | null
  login: (s: Session) => void
  logout: () => void
}

const Ctx = createContext<SessionCtx>({
  session: null,
  login: () => {},
  logout: () => {},
})

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadSession)

  const value: SessionCtx = {
    session,
    login: (s) => { saveSession(s); setSession(s) },
    logout: () => { clearSession(); setSession(null) },
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSession(): SessionCtx {
  return useContext(Ctx)
}
