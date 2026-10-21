// 主应用页：顶栏（页签/角色身份）+ Agent 助手（问答+生成合一）/ 图谱 + 页脚
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Header, type Tab } from '@/components/layout/Header'
import { Footer } from '@/components/layout/Footer'
import { GraphPage } from '@/features/graph/GraphPage'
import { AgentPage } from '@/features/agent/AgentPage'
import { useSession } from '@/lib/session'
import type { Persona } from '@/lib/api'

export function HomePage() {
  const { session, logout, switchPersona } = useSession()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('agent')
  const [focusEntity, setFocusEntity] = useState<string | null>(null)
  // 身份单一事实源 = session.persona（切换写回，刷新不丢，README §9.7）
  const persona: Persona = session?.persona ?? { role: 'management', user: 'Person:chen' }

  // RequireAuth 保证挂载时必有会话；类型上仍给兜底避免窄化噪音
  if (!session) return null

  return (
    <div className="flex min-h-screen flex-col">
      <Header tab={tab} onTab={setTab} session={session} persona={persona}
              onPersona={(role, user) => switchPersona({ role, user })}
              onLogout={() => { logout(); navigate('/login', { replace: true }) }} />
      <main className="flex-1">
        {/* key=角色：切换演示身份即清空上一角色的查询结果，防证据误导（README §9.7） */}
        {tab === 'agent' ? <AgentPage key={persona.role} persona={persona}
                                      onOpenGraph={(id) => { setFocusEntity(id); setTab('graph') }} />
                         : <GraphPage key={persona.role} persona={persona} focusEntity={focusEntity} />}
      </main>
      <Footer />
    </div>
  )
}
