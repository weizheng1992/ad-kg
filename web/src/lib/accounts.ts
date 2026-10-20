// 演示账号表（README §9.7：AdKG 不做用户管理——登录壳是前端演示层，
// 账号↔角色绑定写死在此，服务端仍以 X-Adkg-Role → token 认证，见 docs/deployment.md §四）
import type { Persona } from './api'

export interface Account {
  name: string
  password: string
  label: string
  persona: Persona
  /** 演示管理员可自由切换角色；业务账号锁定绑定角色（权限隔离演示更真实） */
  admin?: boolean
}

export const ACCOUNTS: Account[] = [
  { name: 'chen', password: 'adkg-demo', label: '管理层 · 陈朔', persona: { role: 'management', user: 'Person:chen' } },
  { name: 'li', password: 'adkg-demo', label: '优化师 · 李昂', persona: { role: 'optimizer', user: 'Person:li' } },
  { name: 'wang', password: 'adkg-demo', label: '创意 · 王雪', persona: { role: 'creative', user: 'Person:wang' } },
  { name: 'gu', password: 'adkg-demo', label: '客户方 · 顾佳（外部）', persona: { role: 'client', user: 'Person:client_a' } },
  { name: 'zhou', password: 'adkg-demo', label: '财务 · 周荃', persona: { role: 'finance', user: 'Person:zhou' } },
  { name: 'admin', password: 'adkg-admin', label: '演示管理员', persona: { role: 'management', user: 'Person:chen' }, admin: true },
]

export interface Session {
  account: string
  label: string
  admin: boolean
  /** 登录账号绑定的角色（切换资格看它，不随视角切换而变） */
  baseRole: string
  persona: Persona
}

/** 管理员与管理层账号可自由切换演示身份（README §9.7）；其余账号角色随账号绑定。 */
export function canSwitchRoles(s: Session): boolean {
  return s.admin || s.baseRole === 'management'
}

const KEY = 'adkg.session'

export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const s = JSON.parse(raw) as Session
    // 兼容切换功能上线前的旧会话：baseRole 缺失时按当前视角角色兜底
    return { ...s, baseRole: s.baseRole ?? s.persona?.role ?? 'management' }
  } catch {
    return null
  }
}

export function saveSession(s: Session): void {
  sessionStorage.setItem(KEY, JSON.stringify(s))
}

export function clearSession(): void {
  sessionStorage.removeItem(KEY)
}
