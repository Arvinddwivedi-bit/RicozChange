import { createContext, useContext, useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api, CLERK_ENABLED, type Bootstrap } from './api'
import Dashboard from './pages/Dashboard'
import Changes from './pages/Changes'
import ChangeDetail from './pages/ChangeDetail'
import ChangeForm from './pages/ChangeForm'
import Simulator from './pages/Simulator'
import GraphPage from './pages/GraphPage'
import CABPage from './pages/CABPage'
import Approvals from './pages/Approvals'
import AuditLog from './pages/AuditLog'
import Integrations from './pages/Integrations'
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

export function BrandMark({ subtitle }: { subtitle?: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="logo-tile">R</span>
      <div>
        <div className="font-extrabold tracking-tight text-lg leading-none" style={{ color: 'var(--color-navy)' }}>
          Ricoz<span className="text-brand-600">Change</span>
        </div>
        <div className="text-[11px] text-slate-500 mt-0.5">{subtitle ?? 'AI-native change management'}</div>
      </div>
    </div>
  )
}

const NAV: { group: string; items: { to: string; label: string }[] }[] = [
  {
    group: 'Operate',
    items: [
      { to: '/', label: 'Dashboard' },
      { to: '/changes', label: 'Changes' },
      { to: '/approvals', label: 'Approvals' },
      { to: '/cab', label: 'CAB' },
    ],
  },
  {
    group: 'Plan',
    items: [
      { to: '/simulator', label: 'Simulator' },
      { to: '/graph', label: 'Blast radius' },
      { to: '/freezes', label: 'Freezes' },
    ],
  },
  {
    group: 'Trust',
    items: [
      { to: '/audit', label: 'Audit log' },
      { to: '/integrations', label: 'Integrations' },
    ],
  },
]

export default function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null)
  const [tick, setTick] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [waking, setWaking] = useState(false)

  useEffect(() => {
    setError(null)
    setWaking(false)

    let attempts = 0
    const maxAttempts = 12   // 12 × 8s = ~96s total wait (covers Render cold start)
    let cancelled = false

    async function tryFetch() {
      while (attempts < maxAttempts && !cancelled) {
        try {
          const data = await api<Bootstrap>('/api/bootstrap')
          if (!cancelled) { setBoot(data); setWaking(false) }
          return
        } catch {
          attempts++
          if (attempts === 1) setWaking(true)   // show "waking up" after first fail
          if (attempts >= maxAttempts) {
            if (!cancelled) setError('Could not reach backend after 90 s.')
            return
          }
          await new Promise((r) => setTimeout(r, 8000))  // wait 8 s between retries
        }
      }
    }

    tryFetch()
    return () => { cancelled = true }
  }, [tick])

  if (waking && !boot && !error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <div className="card p-6 max-w-md text-center">
          <div className="text-2xl mb-3">⏳</div>
          <h1 className="font-bold text-lg mb-2">Waking up the server…</h1>
          <p className="text-sm text-slate-500">
            Free hosting spins down after inactivity. This takes up to 60 seconds on first load.
          </p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <div className="card p-6 max-w-md">
          <h1 className="font-bold text-lg mb-2">Backend unreachable</h1>
          <p className="text-sm text-slate-600 mb-4 font-mono text-xs">{error}</p>
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
            <BrandMark />
          </div>
          <nav className="flex-1 py-1 overflow-y-auto">
            {NAV.map((g) => (
              <div key={g.group}>
                <div className="nav-group-label">{g.group}</div>
                {g.items.map((n) => (
                  <NavLink
                    key={n.to}
                    to={n.to}
                    end={n.to === '/'}
                    className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                  >
                    {n.label}
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
          <div className="px-5 py-3 border-t border-slate-200 text-xs text-slate-500">
            Signed in as <span className="font-semibold text-slate-700">{boot.actor.name}</span>
            <div>
              {boot.actor.email} · {boot.actor.role}
            </div>
          </div>
          <div className="px-5 pb-4 text-[10px] text-slate-400">
            {CLERK_ENABLED ? 'Clerk authentication' : 'Demo mode · single-user auth'}
          </div>
        </aside>
        <main className="flex-1 min-w-0">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/changes" element={<Changes />} />
            <Route path="/changes/new" element={<ChangeForm />} />
            <Route path="/changes/:id" element={<ChangeDetail />} />
            <Route path="/simulator" element={<Simulator />} />
            <Route path="/graph" element={<GraphPage />} />
            <Route path="/cab" element={<CABPage />} />
            <Route path="/approvals" element={<Approvals />} />
            <Route path="/audit" element={<AuditLog />} />
            <Route path="/integrations" element={<Integrations />} />
            <Route path="/freezes" element={<Freezes />} />
            <Route path="*" element={<div className="p-8 text-slate-500">Not found</div>} />
          </Routes>
        </main>
      </div>
    </BootCtx.Provider>
  )
}
