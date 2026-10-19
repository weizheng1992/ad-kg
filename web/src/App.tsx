import { useState } from 'react'
import { ROLES } from './api'
import { AskPage } from './Ask'
import { GraphPage } from './Graph'
import './App.css'

export interface Persona { role: string; user: string }

export default function App() {
  const [tab, setTab] = useState<'ask' | 'graph'>('ask')
  const [persona, setPersona] = useState<Persona>(ROLES[0])

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="logo">AdKG</span>
          <span className="sub">本体驱动的广告营销知识中台 · 演示</span>
        </div>
        <nav className="tabs">
          <button className={tab === 'ask' ? 'on' : ''} onClick={() => setTab('ask')}>问答</button>
          <button className={tab === 'graph' ? 'on' : ''} onClick={() => setTab('graph')}>图谱</button>
        </nav>
        <label className="persona">
          当前角色
          <select
            value={persona.user}
            onChange={(e) => setPersona(ROLES.find((r) => r.user === e.target.value) ?? ROLES[0])}>
            {ROLES.map((r) => (
              <option key={r.user} value={r.user}>{r.label}</option>
            ))}
          </select>
        </label>
      </header>
      <main>
        {tab === 'ask' ? <AskPage persona={persona} /> : <GraphPage persona={persona} />}
      </main>
      <footer className="footer">
        同一问题不同角色得到不同的行与字段——这不是功能，是本体权限的副作用
      </footer>
    </div>
  )
}
