// 登录守卫：未登录一律重定向 /login；ready 前（首次 /auth/me 未返回）不判定，防闪跳
import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import { useSession } from '@/lib/session'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session, ready } = useSession()

  if (!ready) return null
  if (!session) return <Navigate to="/login" replace />
  return children
}
