// 权限管理（spec §17）：权限矩阵独立页——角色×类×属性/指标×动作×行过滤（只读可视化）
// 角色定义真源是 permissions.yaml（配置即真源）；账号-角色绑定在「人员管理」
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { getPermissionMatrix, type PermissionMatrix } from '@/lib/api'
import { MatrixTab } from '@/pages/admin/AdminPage'

export function PermissionsPage() {
  const [m, setM] = useState<PermissionMatrix | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getPermissionMatrix().then(setM).catch((e) => setError(`${e}`))
  }, [])

  if (error) return <div className="p-6 text-sm text-red-600">{error}</div>
  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-bold">权限管理</h2>
        <span className="text-xs text-muted-foreground">
          角色 × 类白名单 × 属性/指标 × 动作 × 行过滤——同一问题不同角色得到不同的行与字段；
          角色定义真源 <code className="font-mono">permissions.yaml</code>（配置即真源），
          账号-角色绑定去
          <Link to="/people" className="mx-1 text-primary hover:underline">人员管理</Link>
        </span>
      </div>
      <MatrixTab m={m} />
    </div>
  )
}
