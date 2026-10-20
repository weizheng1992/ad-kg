// 路由表（react-router 库模式）：新增页面在这里注册，页面组件放 pages/<name>/
import { Navigate, createBrowserRouter } from 'react-router'
import { RequireAuth } from './RequireAuth'
import { LoginPage } from '@/pages/login/LoginPage'
import { HomePage } from '@/pages/home/HomePage'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: <RequireAuth><HomePage /></RequireAuth>,
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
