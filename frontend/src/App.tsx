import { createContext, useContext, useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, type Bootstrap } from './api'
import Dashboard from './pages/Dashboard'
import Changes from './pages/Changes'
import ChangeDetail from './pages/ChangeDetail'
import Simulator from './pages/Simulator'
import GraphPage from './pages/GraphPage'
import CABPage from './pages/CABPage'
import SlackDemo from './pages/SlackDemo'
import Freezes from './pages/Freezes'

interface Ctx {
  boot: Bootstrap
  refresh: () => void
}
const BootCtx = createContext<Ctx | null>(null)
export function useBoot(): Ctx {
  const ctx = useContext(BootCtx)
  if (!ctx) throw new Error('useBoot outside provider')
  return ctx
}

const NAV = [
  { to: '/', label: 'Dashboard' },
  { to: '/changes', label: 'Changes' },
  { to: '/simulator', label: 'Simulator' },
  { to: '/graph', label: 'Blast radius' },
  { to: '/cab', label: 'CAB' },
  { to: '/slack', label: 'Slack demo' },
  { to: '/freezes', label: 'Freezes' },
]

export default function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null)
  const [tick, setTick] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api<Bootstrap>('/api/bootstrap')
      .then(setBoot)
      .catch((e) => setError(String(e)))
  }, [tick])

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <div className="card p-6 max-w-md">
          <h1 className="font-bold text-lg mb-2">Backend unreachable</h1>
          <p className="text-sm text-slate-600 mb-4">
            Start the API with <code>uvicorn ricozchange.main:app</code> and reload.
          </p>
          <button className="btn btn-primary" onClick={() => setTick((t) => t + 1)}>
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!boot) {
    return <div className="min-h-screen flex items-center justify-center text-slate-500">Loading…</div>
  }

  return (
    <BootCtx.Provider value={{ boot, refresh: () => setTick((t) => t + 1) }}>
      <div className="min-h-screen flex">
        <aside className="w-56 shrink-0 border-r border-slate-200 bg-white flex flex-col">
          <div className="px-5 py-4 border-b border-slate-200">
            <div className="font-extrabold tracking-tight text-lg">RicozChange</div>
            <div className="text-xs text-slate-500">AI-native change management</div>
          </div>
          <nav className="flex-1 py-3">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.to === '/'}
                className={({ isActive }) =>
                  `block px-5 py-2 text-sm ${
                    isActive
                      ? 'bg-indigo-50 text-indigo-700 font-semibold border-r-2 border-indigo-600'
                      : 'text-slate-600 hover:bg-slate-50'
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="px-5 py-3 border-t border-slate-200 text-xs text-slate-500">
            Signed in as <span className="font-semibold text-slate-700">{boot.actor.name}</span>
            <div>
              {boot.actor.email} · {boot.actor.role}
            </div>
          </div>
          <div className="px-5 pb-4 text-[10px] text-slate-400">
            MVP · demo mode (single-user auth)
          </div>
        </aside>
        <main className="flex-1 min-w-0">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/changes" element={<Changes />} />
            <Route path="/changes/:id" element={<ChangeDetail />} />
            <Route path="/simulator" element={<Simulator />} />
            <Route path="/graph" element={<GraphPage />} />
            <Route path="/cab" element={<CABPage />} />
            <Route path="/slack" element={<SlackDemo />} />
            <Route path="/freezes" element={<Freezes />} />
            <Route path="*" element={<div className="p-8 text-slate-500">Not found</div>} />
          </Routes>
        </main>
      </div>
    </BootCtx.Provider>
  )
}
