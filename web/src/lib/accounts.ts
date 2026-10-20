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
  persona: Persona
}

const KEY = 'adkg.session'

export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as Session) : null
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
