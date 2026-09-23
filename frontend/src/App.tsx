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

const GROUP_KEY = 'rc.nav.open'

function openGroupFor(path: string): string {
  const hit = NAV.find((g) => g.items.some((i) => i.to === path))
  return hit?.group ?? 'Operate'
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      className={`nav-group-chevron ${open ? 'open' : ''}`}
      width="10"
      height="10"
      viewBox="0 0 10 10"
      fill="none"
      aria-hidden
    >
      <path d="M2 3.5 5 6.5 8 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function Loading() {
  return (
    <div className="loading-pane">
      <span className="spinner" aria-label="Loading" />
    </div>
  )
}

export default function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null)
  const [tick, setTick] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [waking, setWaking] = useState(false)
  const [openGroups, setOpenGroups] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem(GROUP_KEY)
      if (saved) return JSON.parse(saved) as string[]
    } catch {
      /* ignore */
    }
    return ['Operate']
  })

  // Keep the group containing the current path reachable: if the user deep-links
  // to /audit with Trust collapsed, expand Trust once on mount.
  useEffect(() => {
    const current = openGroupFor(window.location.pathname)
    setOpenGroups((prev) => (prev.includes(current) ? prev : [...prev, current]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(GROUP_KEY, JSON.stringify(openGroups))
    } catch {
      /* ignore */
    }
  }, [openGroups])

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
          if (attempts === 1) setWaking(true)
          if (attempts >= maxAttempts) {
            if (!cancelled) setError('Could not reach the server. Check your connection and retry.')
            return
          }
          await new Promise((r) => setTimeout(r, 8000))
        }
      }
    }

    tryFetch()
    return () => { cancelled = true }
  }, [tick])

  function toggleGroup(group: string) {
    setOpenGroups((prev) => (prev.includes(group) ? prev.filter((g) => g !== group) : [...prev, group]))
  }

  if (waking && !boot && !error) {
    return (
      <div className="min-h-screen flex items-center justify-center p-8">
        <div className="card p-6 max-w-md text-center">
          <div className="flex justify-center mb-3"><span className="spinner" /></div>
          <h1 className="font-bold text-lg mb-2">Waking up the server</h1>
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
          <h1 className="font-bold text-lg mb-2">Server unreachable</h1>
          <p className="text-sm text-slate-600 mb-4 font-mono text-xs">{error}</p>
          <button className="btn btn-primary" onClick={() => setTick((t) => t + 1)}>
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (!boot) return <Loading />

  return (
    <BootCtx.Provider value={{ boot, refresh: () => setTick((t) => t + 1) }}>
      <div className="min-h-screen flex">
        <aside className="sidebar w-56 shrink-0 flex flex-col sticky top-0 h-screen">
          <div className="px-4 py-4 border-b border-white/60">
            <BrandMark />
          </div>
          <nav className="flex-1 py-2 overflow-y-auto">
            {NAV.map((g) => {
              const open = openGroups.includes(g.group)
              const hasActive = g.items.some((i) => i.to === window.location.pathname)
              return (
                <div key={g.group}>
                  <button
                    className="nav-group-btn"
                    onClick={() => toggleGroup(g.group)}
                    aria-expanded={open}
                  >
                    <span className="flex items-center gap-1.5">
                      {g.group}
                      {hasActive && !open && <span className="w-1 h-1 rounded-full bg-brand-600" title="active page inside" />}
                    </span>
                    <Chevron open={open} />
                  </button>
                  <div className={`nav-collapse ${open ? 'open' : ''}`}>
                    <div>
                      {g.items.map((n) => (
                        <NavLink
                          key={n.to}
                          to={n.to}
                          end={n.to === '/'}
                          className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                          onClick={() => {
                            setOpenGroups((prev) => (prev.includes(g.group) ? prev : [...prev, g.group]))
                          }}
                        >
                          {n.label}
                        </NavLink>
                      ))}
                    </div>
                  </div>
                </div>
              )
            })}
          </nav>
          <div className="px-5 py-3 border-t border-white/60 text-xs text-slate-500">
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
