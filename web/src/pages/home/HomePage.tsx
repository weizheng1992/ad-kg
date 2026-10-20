// 主应用页：顶栏（页签/角色身份）+ 问答 / 图谱两个功能区 + 页脚
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Header, type Tab } from '@/components/layout/Header'
import { Footer } from '@/components/layout/Footer'
import { AskPage } from '@/features/ask/AskPage'
import { GraphPage } from '@/features/graph/GraphPage'
import { useSession } from '@/lib/session'
import type { Persona } from '@/lib/api'

export function HomePage() {
  const { session, logout } = useSession()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('ask')
  const [persona, setPersona] = useState<Persona>(session?.persona ?? { role: 'management', user: 'Person:chen' })

  // RequireAuth 保证挂载时必有会话；类型上仍给兜底避免窄化噪音
  if (!session) return null

  return (
    <div className="flex min-h-screen flex-col">
      <Header tab={tab} onTab={setTab} session={session} persona={persona}
              onPersona={(role, user) => setPersona({ role, user })}
              onLogout={() => { logout(); navigate('/login', { replace: true }) }} />
      <main className="flex-1">
        {tab === 'ask' ? <AskPage persona={persona} /> : <GraphPage persona={persona} />}
      </main>
      <Footer />
    </div>
  )
}
