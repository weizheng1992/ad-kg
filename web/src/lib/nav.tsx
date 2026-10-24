// 侧边导航矩阵（spec §4）：菜单项随登录角色显隐——「权限不同看到的不同」的导航面
// ready=false 的入口置灰占位，展示系统全貌与施工进度
import {
  BarChart3, Building2, LayoutDashboard, Network, ShieldCheck, Users, Wallet,
  type LucideIcon,
} from 'lucide-react'

export const ROLE_LABEL: Record<string, string> = {
  management: '管理层', ae: 'AE/销售', optimizer: '优化师', creative: '创意',
  client: '客户方(外部)', finance: '财务', admin: '运维',
}

/** 星图·模拟（compose 起 mock-douyin 服务，spec §3）；同主机名 8100 端口 */
export const platformUrl = () => `http://${window.location.hostname}:8100`

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  roles: string[]
  /** 页面尚未交付：置灰展示 */
  ready?: boolean
  /** 外链（如模拟平台，M2 起生效） */
  external?: string
}

// Agent 助手不在导航里：全局悬浮窗（AppLayout 挂 AgentDock，所有角色可唤起，spec §6）
export const NAV: NavItem[] = [
  { to: '/', label: '数据看板', icon: LayoutDashboard,
    roles: ['management', 'ae', 'optimizer', 'finance', 'client'] },
  { to: '/creators', label: '达人库', icon: Users,
    roles: ['management', 'ae', 'optimizer', 'finance'] },
  { to: '/platform', label: '数据平台(模拟)', icon: BarChart3,
    roles: ['management', 'ae', 'optimizer'], external: platformUrl() },
  { to: '/brands', label: '客户', icon: Building2,
    roles: ['management', 'ae', 'client'] },
  { to: '/settlements', label: '财务结算', icon: Wallet,
    roles: ['management', 'finance'] },
  { to: '/graph', label: '图谱', icon: Network,
    roles: ['management', 'ae', 'optimizer', 'creative'] },
  { to: '/admin', label: '管理后台', icon: ShieldCheck,
    roles: ['management', 'admin'], ready: false },
]
