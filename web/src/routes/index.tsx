// 路由表（react-router 库模式）：AppLayout 为认证后骨架，页面挂 children
import { Navigate, createBrowserRouter } from 'react-router'
import { RequireAuth } from './RequireAuth'
import { LoginPage } from '@/pages/login/LoginPage'
import { DashboardPage } from '@/pages/dashboard/DashboardPage'
import { AppLayout } from '@/components/layout/AppLayout'
import { GraphPage } from '@/features/graph/GraphPage'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: <RequireAuth><AppLayout /></RequireAuth>,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'graph', element: <GraphPage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
