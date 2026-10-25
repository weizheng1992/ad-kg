// 人员管理独立页（spec §16）：侧边栏直达——账号一览 + admin 专属开户/改密/启停
import { useCallback, useEffect, useState } from 'react'
import { getAdminAccounts, getPermissionMatrix, type AdminAccount
       , type PermissionMatrix } from '@/lib/api'
import { AccountsTab } from '@/pages/admin/AdminPage'
import { useSession } from '@/lib/session'

export function PeoplePage() {
  const { session } = useSession()
  const [items, setItems] = useState<AdminAccount[] | null>(null)
  const [m, setM] = useState<PermissionMatrix | null>(null)
  const [error, setError] = useState('')

  const load = useCallback(() => {
    getAdminAccounts().then((r) => setItems(r.items)).catch((e) => setError(`${e}`))
  }, [])

  useEffect(() => {
    load()
    getPermissionMatrix().then(setM).catch((e) => setError(`${e}`))
  }, [load])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-bold">人员管理</h2>
        <span className="text-xs text-muted-foreground">
          账号 · 角色 · Person 绑定——开户/改密/停启用为 admin 专属（改密与停用即吊销会话），management 只读
        </span>
      </div>
      <AccountsTab items={items} roles={m ? Object.keys(m.roles) : []}
                   canWrite={session?.role === 'admin'} onChanged={load} />
    </div>
  )
}
