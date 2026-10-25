// 导航（spec §17 菜单管理）：菜单真源在服务端（GET /menus，DB 数据驱动），
// 本文件保留静态默认（/menus 不可用时的回落）与图标名映射、角色标签
import {
  BarChart3, Bot, Briefcase, Building2, KeyRound, LayoutDashboard, Menu, Network,
  ShieldCheck, UserCog, Users, Wallet, type LucideIcon,
} from 'lucide-react'

export const ROLE_LABEL: Record<string, string> = {
  management: '管理层', ae: 'AE/销售', optimizer: '优化师', creative: '创意',
  client: '客户方(外部)', finance: '财务', admin: '运维',
}

/** 图标名（后端白名单同源）→ 组件 */
export const ICONS: Record<string, LucideIcon> = {
  LayoutDashboard, Users, Briefcase, BarChart3, Building2, Wallet, Network,
  ShieldCheck, UserCog, KeyRound, Menu, Bot,
}

export const ICON_NAMES = Object.keys(ICONS)

/** 星图·模拟（compose 起 mock-douyin 服务，spec §3）；同主机名 8100 端口 */
export const platformUrl = () => `http://${window.location.hostname}:8100`

export interface NavItem {
  to: string
  label: string
  icon: string                  // ICONS 键名（数据驱动）
  roles: string[]
  ready?: boolean
  external?: string
}

/** 静态回落默认 = 后端 DEFAULT_MENUS（§4 矩阵 + §16/§17 管理入口） */
export const DEFAULT_NAV: NavItem[] = [
  { to: '/', label: '数据看板', icon: 'LayoutDashboard',
    roles: ['management', 'ae', 'optimizer', 'finance', 'client'] },
  { to: '/creators', label: '达人库', icon: 'Users',
    roles: ['management', 'ae', 'optimizer', 'finance'] },
  { to: '/cases', label: '案例', icon: 'Briefcase',
    roles: ['management', 'ae', 'optimizer', 'client'] },
  { to: '/platform', label: '数据平台(模拟)', icon: 'BarChart3',
    roles: ['management', 'ae', 'optimizer'], external: platformUrl() },
  { to: '/brands', label: '客户', icon: 'Building2',
    roles: ['management', 'ae', 'client'] },
  { to: '/settlements', label: '财务结算', icon: 'Wallet',
    roles: ['management', 'finance'] },
  { to: '/graph', label: '图谱', icon: 'Network',
    roles: ['management', 'ae', 'optimizer', 'creative'] },
  { to: '/admin', label: '管理后台', icon: 'ShieldCheck',
    roles: ['management', 'admin'] },
  { to: '/people', label: '人员管理', icon: 'UserCog',
    roles: ['management', 'admin'] },
  { to: '/permissions', label: '权限管理', icon: 'KeyRound',
    roles: ['management', 'admin'] },
  { to: '/menus', label: '菜单管理', icon: 'Menu', roles: ['admin'] },
]
