// 登录守卫：未登录一律重定向 /login（受保护路由统一包这一层）
import type { ReactNode } from 'react'
import { Navigate } from 'react-router'
import { useSession } from '@/lib/session'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { session } = useSession()

  if (!session) return <Navigate to="/login" replace />
  return children
}
