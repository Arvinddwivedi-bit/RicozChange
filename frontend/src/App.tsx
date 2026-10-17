import { createContext, useContext, useEffect, useState } from 'react'
import { NavLink, Route, Routes, useLocation, Link } from 'react-router-dom'
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
import NotFound from './pages/NotFound'
import {
  LayoutDashboard,
  GitPullRequest,
  CheckCircle2,
  FlaskConical,
  Network,
  Snowflake,
  Plug,
  Users,
  ScrollText,
  LogOut,
  Bell,
  Plus,
  ChevronRight,
} from 'lucide-react'
import { Toaster } from 'sonner'

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
      <svg className="logo-tile" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><path d="M3 9l9-3 9 3v9a3 3 0 0 1-3 3H6z"/><circle cx="8.5" cy="21" r="1.5"/><circle cx="15.5" cy="21" r="1.5"/></svg>
      <div className="min-w-0">
        <div className="font-extrabold tracking-tight text-[18px] leading-none" style={{ color: 'var(--color-navy)' }}>
          RicozChange
        </div>
        <div className="text-[10.5px] text-slate-500 mt-1 truncate">{subtitle ?? 'IT change management platform'}</div>
      </div>
    </div>
  )
}

const NAV: { group: string; items: { to: string; label: string; badge?: 'approvals'; icon: any }[] }[] = [
  {
    group: 'Operate',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/changes', label: 'Changes', icon: GitPullRequest },
      { to: '/approvals', label: 'Approvals', badge: 'approvals', icon: CheckCircle2 },
    ],
  },
  {
    group: 'Plan',
    items: [
      { to: '/simulator', label: 'Simulator', icon: FlaskConical },
      { to: '/graph', label: 'Blast radius', icon: Network },
      { to: '/freezes', label: 'Freezes', icon: Snowflake },
      { to: '/integrations', label: 'Integrations', icon: Plug },
    ],
  },
  {
    group: 'Govern',
    items: [
      { to: '/cab', label: 'CAB Meetings', icon: Users },
    ],
  },
  {
    group: 'Trust',
    items: [{ to: '/audit', label: 'Audit log', icon: ScrollText }],
  },
]

const GROUP_KEY = 'rc.nav.open'

function openGroupFor(path: string): string {
  const hit = NAV.find((g) => g.items.some((i) => i.to === path))
  return hit?.group ?? 'Operate'
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg className={`nav-group-chevron ${open ? 'open' : ''}`} width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden>
      <path d="M2 3.5 5 6.5 8 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function NavBody({
  boot,
  openGroups,
  toggleGroup,
  ensureGroupOpen,
  pendingCount,
  onNavigate,
}: {
  boot: Bootstrap
  openGroups: string[]
  toggleGroup: (g: string) => void
  ensureGroupOpen: (g: string) => void
  pendingCount: number | null
  onNavigate?: () => void
}) {
  const roleColors: Record<string, string> = {
    admin: 'bg-brand-100 text-brand-700',
    manager: 'bg-blue-100 text-blue-700',
  }
  const roleClass = roleColors[boot.actor.role] || 'bg-slate-100 text-slate-700'

  return (
    <>
      <div className="px-4 pt-4 pb-3">
        <BrandMark />
      </div>
      <nav className="flex-1 overflow-y-auto pb-2">
        {NAV.map((g) => {
          const open = openGroups.includes(g.group)
          const hasActive = g.items.some((i) => i.to === window.location.pathname)
          return (
            <div key={g.group}>
              <button className="nav-group-label w-full text-left" onClick={() => toggleGroup(g.group)} aria-expanded={open}>
                <span className="flex items-center gap-1.5">
                  {g.group}
                  {hasActive && !open && <span className="w-1 h-1 rounded-full bg-brand-600" />}
                </span>
                <Chevron open={open} />
              </button>
              <div className={`nav-collapse ${open ? 'open' : ''}`}>
                <div>
                  {g.items.map((n) => {
                    const Icon = n.icon
                    return (
                      <NavLink
                        key={n.to}
                        to={n.to}
                        end={n.to === '/'}
                        className={({ isActive }) => `nav-link ${isActive ? 'active' : ''} flex items-center gap-2`}
                        onClick={() => {
                          ensureGroupOpen(g.group)
                          onNavigate?.()
                        }}
                      >
                        <Icon size={16} className="opacity-70" />
                        <span className="flex-1">{n.label}</span>
                        {n.badge === 'approvals' && pendingCount != null && pendingCount > 0 && (
                          <span className="nav-count">{pendingCount}</span>
                        )}
                      </NavLink>
                    )
                  })}
                </div>
              </div>
            </div>
          )
        })}
      </nav>
      <div className="border-t border-slate-100 p-3">
        <div className="flex items-center gap-2.5 rounded-xl border border-slate-100 bg-slate-50/60 px-2.5 py-2">
          <span
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-navy text-[11px] font-bold text-white"
            title={boot.actor.name}
          >
            {boot.actor.name.split(' ').map((p) => p[0]).slice(0, 2).join('')}
          </span>
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-[13px] font-semibold" style={{ color: 'var(--color-navy)' }}>
              {boot.actor.name}
            </div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className={`text-[9px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded-sm ${roleClass}`}>
                {boot.actor.role}
              </span>
            </div>
          </div>
          {CLERK_ENABLED && (
            <button 
              className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200 rounded-md transition-colors" 
              onClick={() => { window.location.href = '/sign-out' }}
              title="Sign out"
            >
              <LogOut size={16} />
            </button>
          )}
        </div>
        <div className="mt-2 px-1 text-[10px] text-slate-400 text-center">
          {CLERK_ENABLED ? 'Clerk authentication' : 'Demo mode · single-user auth'}
        </div>
      </div>
    </>
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
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [pendingCount, setPendingCount] = useState<number | null>(null)
  const [openGroups, setOpenGroups] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem(GROUP_KEY)
      if (saved) return JSON.parse(saved) as string[]
    } catch {
      /* ignore */
    }
    return ['Operate']
  })

  // We can use the current path for the breadcrumb name
  const loc = useLocation()
  let currentPageName = 'Dashboard'
  if (loc.pathname.startsWith('/changes/new')) currentPageName = 'New Change'
  else if (loc.pathname.startsWith('/changes/')) currentPageName = 'Change Details'
  else if (loc.pathname.startsWith('/changes')) currentPageName = 'Changes'
  else if (loc.pathname.startsWith('/simulator')) currentPageName = 'Simulator'
  else if (loc.pathname.startsWith('/graph')) currentPageName = 'Blast Radius'
  else if (loc.pathname.startsWith('/cab')) currentPageName = 'CAB Meetings'
  else if (loc.pathname.startsWith('/approvals')) currentPageName = 'Approvals'
  else if (loc.pathname.startsWith('/audit')) currentPageName = 'Audit Log'
  else if (loc.pathname.startsWith('/integrations')) currentPageName = 'Integrations'
  else if (loc.pathname.startsWith('/freezes')) currentPageName = 'Freezes'

  const [dropdownOpen, setDropdownOpen] = useState(false)

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
    const maxAttempts = 12
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

  // Pending approvals badge (nav + user trust): light, refreshed on every refresh().
  useEffect(() => {
    if (!boot) return
    let cancelled = false
    api<{ acted: boolean }[]>('/api/notifications')
      .then((rows) => { if (!cancelled) setPendingCount(rows.filter((r) => !r.acted).length) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [boot, tick])

  function toggleGroup(group: string) {
    setOpenGroups((prev) => (prev.includes(group) ? prev.filter((g) => g !== group) : [...prev, group]))
  }

  if (waking && !boot && !error) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-8 bg-slate-50">
        <BrandMark />
        <div className="card p-8 max-w-md text-center mt-8 shadow-sm border-slate-200">
          <div className="flex justify-center mb-6">
            <div className="relative w-12 h-12 flex items-center justify-center">
              <span className="absolute inset-0 border-4 border-slate-100 rounded-full"></span>
              <span className="absolute inset-0 border-4 border-brand-500 rounded-full border-t-transparent animate-spin"></span>
              <FlaskConical size={20} className="text-brand-500" />
            </div>
          </div>
          <h1 className="font-bold text-xl mb-3" style={{ color: 'var(--color-navy)' }}>Waking up the workspace</h1>
          <p className="text-slate-500 leading-relaxed">
            Your dedicated instance is starting up. This usually takes about 30-60 seconds on the first load.
          </p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center p-8 bg-slate-50">
        <BrandMark />
        <div className="card p-8 max-w-md text-center mt-8 border-red-100 shadow-sm">
          <div className="flex justify-center mb-6 text-red-500">
            <Network size={32} />
          </div>
          <h1 className="font-bold text-xl mb-3" style={{ color: 'var(--color-navy)' }}>Server Unreachable</h1>
          <p className="text-sm text-slate-600 mb-6 font-mono bg-slate-100 p-3 rounded-md text-left overflow-hidden text-ellipsis">{error}</p>
          <button className="btn btn-primary w-full justify-center" onClick={() => setTick((t) => t + 1)}>
            Retry Connection
          </button>
        </div>
      </div>
    )
  }

  if (!boot) return <Loading />

  const sidebar = (
    <div className="sidebar flex h-full w-[260px] shrink-0 flex-col">
      <NavBody
        ensureGroupOpen={(g) => setOpenGroups((prev) => (prev.includes(g) ? prev : [...prev, g]))}
        boot={boot}
        openGroups={openGroups}
        toggleGroup={toggleGroup}
        pendingCount={pendingCount}
        onNavigate={() => setDrawerOpen(false)}
      />
    </div>
  )

  return (
    <BootCtx.Provider value={{ boot, refresh: () => setTick((t) => t + 1) }}>
      <Toaster richColors position="bottom-right" />
      {/* Mobile top bar */}
      <div className="sticky top-0 z-30 flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 lg:hidden">
        <button className="icon-btn" aria-label="Open menu" onClick={() => setDrawerOpen(true)}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
        <BrandMark subtitle={undefined} />
      </div>

      <div className="flex bg-slate-50 min-h-screen">
        {/* Desktop sidebar */}
        <aside className="sidebar sticky top-0 hidden h-screen w-[260px] shrink-0 lg:block">{sidebar}</aside>

        {/* Mobile drawer */}
        {drawerOpen && (
          <>
            <div className="drawer-scrim lg:hidden" onClick={() => setDrawerOpen(false)} />
            <div className="drawer-panel lg:hidden">
              {sidebar}
            </div>
          </>
        )}

        <main className="min-w-0 flex-1 flex flex-col">
          {/* Top Header */}
          <header className="sticky top-0 z-20 hidden lg:flex h-16 items-center justify-between border-b border-slate-200 bg-white px-8 shadow-sm">
            <div className="flex items-center gap-2 text-sm text-slate-500 font-medium">
              <span>Workspace</span>
              <ChevronRight size={14} />
              <span className="text-slate-900">{currentPageName}</span>
            </div>
            
            <div className="flex items-center gap-4">
              <Link to="/changes/new" className="btn btn-primary shadow-sm">
                <Plus size={16} className="-ml-1 mr-1" />
                New Change
              </Link>
              
              <div className="h-6 w-px bg-slate-200 mx-1"></div>
              
              <button className="relative p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-full transition-colors">
                <Bell size={20} />
                {pendingCount != null && pendingCount > 0 && (
                  <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-brand-500 border-2 border-white"></span>
                )}
              </button>
              
              <div className="relative">
                <button 
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-navy text-[12px] font-bold text-white shadow-sm ring-2 ring-white hover:ring-slate-100 transition-all"
                  onClick={() => setDropdownOpen(!dropdownOpen)}
                  title={boot.actor.name}
                >
                  {boot.actor.name.split(' ').map((p) => p[0]).slice(0, 2).join('')}
                </button>
                
                {dropdownOpen && (
                  <>
                    <div className="fixed inset-0 z-10" onClick={() => setDropdownOpen(false)}></div>
                    <div className="absolute right-0 mt-2 w-48 rounded-lg bg-white shadow-lg border border-slate-100 py-1 z-20">
                      <div className="px-4 py-2 border-b border-slate-100 mb-1">
                        <div className="text-sm font-semibold truncate" style={{ color: 'var(--color-navy)' }}>{boot.actor.name}</div>
                        <div className="text-xs text-slate-500 truncate">{boot.actor.email}</div>
                      </div>
                      {CLERK_ENABLED && (
                        <button 
                          className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
                          onClick={() => { window.location.href = '/sign-out' }}
                        >
                          <LogOut size={14} />
                          Sign out
                        </button>
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          </header>

          <div className="flex-1 overflow-auto">
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
              <Route path="*" element={<NotFound />} />
            </Routes>
          </div>
        </main>
      </div>
    </BootCtx.Provider>
  )
}
