// 路由表（react-router 库模式）：AppLayout 为认证后骨架，页面挂 children
import { Navigate, createBrowserRouter } from 'react-router'
import { RequireAuth } from './RequireAuth'
import { LoginPage } from '@/pages/login/LoginPage'
import { DashboardPage } from '@/pages/dashboard/DashboardPage'
import { AppLayout } from '@/components/layout/AppLayout'
import { GraphPage } from '@/features/graph/GraphPage'
import { CreatorsPage } from '@/pages/creators/CreatorsPage'
import { CreatorDetailPage } from '@/pages/creators/CreatorDetailPage'
import { CasesPage } from '@/pages/cases/CasesPage'
import { CaseDetailPage } from '@/pages/cases/CaseDetailPage'
import { BrandsPage } from '@/pages/brands/BrandsPage'
import { BrandDetailPage } from '@/pages/brands/BrandDetailPage'
import { SettlementsPage } from '@/pages/settlements/SettlementsPage'
import { AdminPage } from '@/pages/admin/AdminPage'
import { PeoplePage } from '@/pages/admin/PeoplePage'

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    path: '/',
    element: <RequireAuth><AppLayout /></RequireAuth>,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: 'creators', element: <CreatorsPage /> },
      { path: 'creators/:id', element: <CreatorDetailPage /> },
      { path: 'cases', element: <CasesPage /> },
      { path: 'cases/:id', element: <CaseDetailPage /> },
      { path: 'brands', element: <BrandsPage /> },
      { path: 'brands/:id', element: <BrandDetailPage /> },
      { path: 'settlements', element: <SettlementsPage /> },
      { path: 'graph', element: <GraphPage /> },
      { path: 'admin', element: <AdminPage /> },
      { path: 'people', element: <PeoplePage /> },
    ],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
