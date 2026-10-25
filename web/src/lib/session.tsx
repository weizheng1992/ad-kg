// 会话上下文（spec §2）：/auth/me 驱动的服务端会话——登录/登出全应用唯一入口
// ready 区分「还没问到」与「确实未登录」，守卫据此防首屏闪跳登录页
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { fetchMe, fetchMyActions, login as apiLogin, logout as apiLogout,
         type Me } from './api'

interface SessionCtx {
  session: Me | null
  ready: boolean
  /** 按钮权限集合（spec §18.5）：登录后取 /my-actions，按钮显隐用 */
  actions: Set<string>
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const Ctx = createContext<SessionCtx>({
  session: null, ready: false, actions: new Set(),
  login: async () => {}, logout: async () => {},
})

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Me | null>(null)
  const [ready, setReady] = useState(false)
  const [actions, setActions] = useState<Set<string>>(new Set())

  useEffect(() => {
    fetchMe().then(setSession).finally(() => setReady(true))
  }, [])

  useEffect(() => {
    if (!session) { setActions(new Set()); return }
    fetchMyActions().then((a) => setActions(new Set(a.actions))).catch(() => {})
  }, [session?.username, session?.role])

  const value: SessionCtx = {
    session,
    ready,
    actions,
    login: async (username, password) => setSession(await apiLogin(username, password)),
    logout: async () => { await apiLogout(); setSession(null) },
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSession(): SessionCtx {
  return useContext(Ctx)
}

/** 按钮显隐统一入口（spec §19 缺陷清偿③）：action 词表与后端 role_allows 同源；
 * 全应用按钮一律 useCan(action) 判定，不再散抄 session.role === 'admin' */
export function useCan(action: string): boolean {
  const { actions } = useSession()
  return actions.has(action)
}
