// 数据看板（M5 交付真实聚合；口径全走 metrics.py 汇总比）——本里程碑先落角色视图占位
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ROLE_LABEL } from '@/lib/nav'
import { useSession } from '@/lib/session'

export function DashboardPage() {
  const { session } = useSession()
  if (!session) return null
  return (
    <div className="mx-auto max-w-3xl space-y-4 p-6">
      <div>
        <h2 className="text-base font-bold">数据看板</h2>
        <p className="text-xs text-muted-foreground">
          大盘消耗/转化趋势、平台分布、品牌与达人排行（echarts，M5 交付）
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">当前身份</CardTitle>
          <CardDescription>菜单与数据随角色变化——权限是本体矩阵的副作用</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-3 text-sm">
          <b>{session.display_name}</b>
          <Badge variant="secondary">{ROLE_LABEL[session.role] ?? session.role}</Badge>
          {session.person && (
            <span className="font-mono text-xs text-muted-foreground">{session.person}</span>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">施工里程碑</CardTitle>
          <CardDescription>spec：docs/specs/2026-10-24-真实系统化升级-spec.md</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-1.5 text-xs text-muted-foreground">
          {[
            ['✅', 'M1 认证 + 应用骨架（本页即新骨架）'],
            ['⏳', 'M2 Creator 本体 + 达人库 + 模拟数据平台'],
            ['⏳', 'M3 客户页（商品详情 / 使用人群 / 拒因）'],
            ['⏳', 'M4 财务结算中心'],
            ['⏳', 'M5 数据看板（本页替换为真实聚合）'],
            ['⏳', 'M6 Agent SSE 透明化 + 平台浏览工具'],
            ['⏳', 'M7 管理后台（权限矩阵 / 账号 / 审计）'],
          ].map(([mark, text]) => (
            <div key={text} className="flex items-center gap-2"><span>{mark}</span>{text}</div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
