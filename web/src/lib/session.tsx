// 会话上下文（spec §2）：/auth/me 驱动的服务端会话——登录/登出全应用唯一入口
// ready 区分「还没问到」与「确实未登录」，守卫据此防首屏闪跳登录页
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { fetchMe, login as apiLogin, logout as apiLogout, type Me } from './api'

interface SessionCtx {
  session: Me | null
  ready: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const Ctx = createContext<SessionCtx>({
  session: null, ready: false,
  login: async () => {}, logout: async () => {},
})

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Me | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    fetchMe().then(setSession).finally(() => setReady(true))
  }, [])

  const value: SessionCtx = {
    session,
    ready,
    login: async (username, password) => setSession(await apiLogin(username, password)),
    logout: async () => { await apiLogout(); setSession(null) },
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSession(): SessionCtx {
  return useContext(Ctx)
}
