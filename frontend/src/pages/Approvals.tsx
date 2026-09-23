import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDate, type NotificationT } from '../api'
import { useBoot } from '../App'

/* ---------- small building blocks ---------- */

function Toast({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div className="toast" role="status">
      <span className="toast-ok-icon">
        <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
          <path d="M2.5 6.5 5 9l4.5-5.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      {message}
    </div>
  )
}

function RiskMeter({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score))
  const tier = pct >= 70 ? 'Critical' : pct >= 40 ? 'High' : pct >= 25 ? 'Medium' : 'Low'
  const tierColor = pct >= 70 ? 'text-brand-700' : pct >= 40 ? 'text-orange-600' : pct >= 25 ? 'text-amber-600' : 'text-emerald-600'
  return (
    <div>
      <div className="meter-track">
        <div className="meter">
          <span className="meter-marker" style={{ left: `${pct}%` }} />
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] font-medium text-slate-400">
        <span>Low</span>
        <span>Medium</span>
        <span>High</span>
        <span className={`font-semibold ${tierColor}`}>{tier}</span>
      </div>
    </div>
  )
}

function Metric({ label, value, tone = 'navy' }: { label: string; value: number; tone?: 'navy' | 'red' | 'amber' | 'slate' }) {
  const colors: Record<string, string> = {
    navy: 'text-navy',
    red: 'text-brand-600',
    amber: 'text-amber-600',
    slate: 'text-slate-400',
  }
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className={`metric-value ${colors[tone]}`}>{value}</div>
    </div>
  )
}

function InfoCell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-slate-400">{label}</div>
      <div className="mt-1 text-[13.5px] font-medium text-navy">{children}</div>
    </div>
  )
}

function WhyRow({ label, detail }: { label: string; detail: string }) {
  return (
    <div className="flex items-start gap-2.5 rounded-lg px-2 py-1.5 transition-colors hover:bg-slate-50">
      <svg className="mt-0.5 shrink-0 text-brand-600" width="14" height="14" viewBox="0 0 16 16" fill="none">
        <path d="M8 1.5 14.5 13.5H1.5L8 1.5Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
        <path d="M8 6v3.2" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        <circle cx="8" cy="11.4" r="0.8" fill="currentColor" />
      </svg>
      <div className="min-w-0">
        <div className="text-[13px] font-medium text-navy">{label}</div>
        <div className="text-[12px] leading-snug text-slate-500">{detail}</div>
      </div>
    </div>
  )
}

/** Fallback risk reasoning when a stored payload predates factor capture. */
function whyFallback(items: { label: string; points: number }[], riskType: string) {
  if (items.length) return items.map((i) => i.label)
  const generic: Record<string, string[]> = {
    major: ['Production infrastructure modification', 'High inherent risk change class', 'Restricted deployment window'],
    emergency: ['Emergency change — reduced review depth', 'Production impact likely'],
  }
  return generic[riskType] ?? ['Standard change risk profile']
}

/* ---------- page ---------- */

export default function Approvals() {
  const { boot } = useBoot()
  const [notes, setNotes] = useState<NotificationT[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [showDecided, setShowDecided] = useState(false)
  const [query, setQuery] = useState('')
  const [toast, setToast] = useState<string | null>(null)

  const load = useCallback(() => {
    api<NotificationT[]>('/api/notifications').then(setNotes)
  }, [])

  useEffect(load, [load])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3200)
    return () => clearTimeout(t)
  }, [toast])

  async function act(id: number, action: 'approve' | 'reject') {
    setErr(null)
    setBusyId(id)
    try {
      await api(`/api/notifications/${id}/act`, { method: 'POST', body: JSON.stringify({ action }) })
      setToast(action === 'approve' ? 'Change approved — status updated' : 'Change rejected — status updated')
      load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  const pending = useMemo(() => (notes ?? []).filter((n) => !n.acted), [notes])
  const decided = useMemo(() => (notes ?? []).filter((n) => n.acted), [notes])
  const visible = showDecided ? notes ?? [] : pending

  const filtered = useMemo(() => {
    if (!query.trim()) return visible
    const q = query.toLowerCase()
    return visible.filter(
      (n) =>
        String(n.change_id).includes(q) ||
        n.channel.toLowerCase().includes(q) ||
        n.message.text.toLowerCase().includes(q),
    )
  }, [visible, query])

  // Approval cards keyed off the message payload (same as before).
  const cards = filtered.map((n) => {
    const byType = new Map<string, any>()
    for (const b of n.message.blocks) byType.set(b.type, b)
    const context = byType.get('context')?.fields ?? {}
    const whyItems: { label: string; points: number }[] = byType.get('risk_why')?.items ?? []
    const actions = byType.get('actions')?.actions ?? []
    return { n, context, whyItems, actions }
  })

  const metrics = useMemo(() => {
    const highRisk = pending.filter((c) => {
      const ctx = c.message.blocks.find((b) => b.type === 'context')?.fields ?? {}
      const risk = Number(ctx.Risk ?? 0)
      return risk >= 70
    }).length
    const today = new Date().toDateString()
    const decidedToday = decided.filter((c) => new Date(c.created_at).toDateString() === today).length
    const mine = pending.filter((c) => JSON.stringify(c.message.blocks).includes(boot.actor.name)).length
    return { pending: pending.length, mine, highRisk, decidedToday }
  }, [pending, decided, boot.actor.name])

  if (!notes) {
    return (
      <div className="loading-pane">
        <span className="spinner" style={{ color: 'var(--color-brand-600)' }} />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      {/* ---------- header ---------- */}
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em]">Approval Inbox</h1>
          <p className="mt-0.5 text-[13.5px] text-slate-500">Review high-risk changes before they reach production.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <svg className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" width="14" height="14" viewBox="0 0 16 16" fill="none">
              <circle cx="7" cy="7" r="4.5" stroke="currentColor" strokeWidth="1.5" />
              <path d="m10.5 10.5 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input
              className="input w-[190px] !py-[7px] pl-8 text-[13px]"
              placeholder="Search approvals"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <label className="flex cursor-pointer select-none items-center gap-2 rounded-[10px] border border-slate-200 bg-white px-3 py-[7px] text-[13px] font-medium text-slate-600 transition-colors hover:border-slate-300">
            <input type="checkbox" className="accent-brand-600" checked={showDecided} onChange={(e) => setShowDecided(e.target.checked)} />
            Show decided
            <span className="rounded-full bg-slate-100 px-1.5 text-[11px] font-semibold text-slate-500">{decided.length}</span>
          </label>
          <button className="icon-btn" title="Notifications" aria-label="Notifications">
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
              <path d="M8 2a4 4 0 0 0-4 4v2.5L2.8 11h10.4L12 8.5V6a4 4 0 0 0-4-4Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
              <path d="M6.5 13a1.5 1.5 0 0 0 3 0" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
            {metrics.pending > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand-600 px-1 text-[9px] font-bold text-white">
                {metrics.pending}
              </span>
            )}
          </button>
          <span
            className="flex h-9 w-9 items-center justify-center rounded-full bg-navy text-[11px] font-bold text-white"
            title={boot.actor.name}
          >
            {boot.actor.name.split(' ').map((p) => p[0]).slice(0, 2).join('')}
          </span>
        </div>
      </header>

      {/* status pills */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="pill pill-red">
          <span className="pill-dot" />
          {metrics.pending} pending
        </span>
        <span className="pill pill-neutral">{metrics.mine} awaiting you</span>
        {metrics.highRisk > 0 && <span className="pill pill-amber"><span className="pill-dot" />{metrics.highRisk} high risk</span>}
      </div>

      {/* ---------- metrics ---------- */}
      <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label="Pending approvals" value={metrics.pending} tone="red" />
        <Metric label="Awaiting me" value={metrics.mine} />
        <Metric label="High risk" value={metrics.highRisk} tone="amber" />
        <Metric label="Decided today" value={metrics.decidedToday} tone="slate" />
      </div>

      {err && <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}

      {/* ---------- queue ---------- */}
      <div className="mt-6 space-y-4">
        {cards.length === 0 && (
          <div className="card flex flex-col items-center justify-center px-6 py-12 text-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
              <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
                <path d="M2.5 8.5 6 12l7.5-8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
            <p className="mt-3 text-[15px] font-semibold text-navy">{showDecided ? 'No decided approvals yet' : 'Inbox zero'}</p>
            <p className="mt-1 max-w-sm text-[13px] text-slate-500">
              {showDecided
                ? 'Approve or reject something and it will show up here.'
                : 'New approval requests land here the moment a change is submitted.'}
            </p>
          </div>
        )}

        {cards.map(({ n, context, whyItems, actions }) => {
          const risk = Number(context.Risk ?? 0)
          const cls = String(context.Class ?? 'normal')
          const title = n.message.text
            .replace(/^Approval needed:\s*/i, '')
            .replace(/^change #\d+\s*/i, '')
            .replace(/^["\u201c]+/, '')
            .replace(/["\u201d]+$/, '')
          const when = fmtDate(n.created_at)
          return (
            <article key={n.id} className="card overflow-hidden">
              {/* card header */}
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 pb-4 pt-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-bold ${
                      risk >= 70 ? 'bg-brand-600 text-white' : risk >= 40 ? 'bg-amber-500 text-white' : 'bg-emerald-500 text-white'
                    }`}>
                      {risk}
                    </span>
                    <span className="text-[13px] font-semibold text-slate-400">Change #{n.change_id}</span>
                  </div>
                  <h2 className="mt-1.5 truncate text-[18px] font-semibold tracking-[-0.015em] text-navy">{title}</h2>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px] text-slate-500">
                    <span>Submitted by <span className="font-medium text-slate-600">{n.channel}</span></span>
                    <span className="text-slate-300">•</span>
                    <span>Slack message</span>
                    <span className="text-slate-300">•</span>
                    <span>{when}</span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className={`pill ${cls === 'major' || cls === 'emergency' ? 'pill-red' : cls === 'standard' ? 'pill-green' : 'pill-blue'}`}>
                    {String(cls).toUpperCase()}
                  </span>
                  {n.acted ? (
                    <span className={`pill ${n.acted_action === 'approved' ? 'pill-green' : 'pill-red'}`}>
                      {n.acted_action === 'approved' ? 'Approved' : 'Rejected'}
                    </span>
                  ) : (
                    <span className="pill pill-amber"><span className="pill-dot" />Pending approval</span>
                  )}
                </div>
              </div>

              {/* info grid */}
              <div className="grid grid-cols-2 gap-4 border-b border-slate-100 px-5 py-4 md:grid-cols-4">
                <InfoCell label="Risk">
                  <span className="text-[15px] font-bold">{risk} / 100</span>
                  <span className={`ml-1.5 text-[12px] font-semibold ${risk >= 70 ? 'text-brand-600' : 'text-slate-500'}`}>
                    {risk >= 70 ? 'Critical' : risk >= 40 ? 'High' : 'Moderate'}
                  </span>
                </InfoCell>
                <InfoCell label="Change class">{String(context.Class ?? '—')}</InfoCell>
                <InfoCell label="Change window">{String(context.Window ?? 'Not scheduled')}</InfoCell>
                <InfoCell label="Affected systems">
                  <span className="flex flex-wrap gap-1">
                    {String(context.Systems ?? '')
                      .split(',')
                      .filter(Boolean)
                      .map((s) => (
                        <span key={s} className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-[11.5px] font-medium text-slate-600">
                          {s.trim()}
                        </span>
                      ))}
                  </span>
                </InfoCell>
              </div>

              {/* risk assessment */}
              <div className="border-b border-slate-100 px-5 py-4">
                <div className="mb-3 flex items-baseline justify-between">
                  <h3 className="text-[13px] font-semibold uppercase tracking-[0.06em] text-slate-500">Risk assessment</h3>
                  <span className="text-[13px] font-semibold text-navy">
                    {risk} <span className="text-slate-400">/ 100</span>
                  </span>
                </div>
                <RiskMeter score={risk} />
                <div className="mt-3 grid gap-1 md:grid-cols-2">
                  {whyFallback(whyItems, String(context.Class ?? '')).slice(0, 4).map((label) => (
                    <WhyRow key={label} label={label} detail="Contributing factor from the scoring engine" />
                  ))}
                </div>
              </div>

              {/* blast radius */}
              <div className="grid gap-4 border-b border-slate-100 px-5 py-4 md:grid-cols-3">
                <InfoCell label="Affected systems">
                  <div className="space-y-1">
                    {String(context.Systems ?? '').split(',').filter(Boolean).map((s) => (
                      <div key={s} className="font-mono text-[12.5px] text-slate-700">{s.trim()}</div>
                    ))}
                  </div>
                </InfoCell>
                <InfoCell label="Dependencies">
                  <div className="space-y-1 text-[12.5px] text-slate-700">
                    <div>Upstream services in blast radius</div>
                  </div>
                </InfoCell>
                <InfoCell label="Potential impact">
                  <div className="text-[12.5px] text-slate-700">
                    {risk >= 70 ? 'Customer-facing interruption possible' : 'Limited service impact'}
                  </div>
                </InfoCell>
              </div>

              {/* action footer */}
              <div className="sticky bottom-0 flex flex-wrap items-center gap-2.5 bg-white/95 px-5 py-3.5 backdrop-blur">
                <span className="mr-auto hidden items-center gap-1.5 text-[12px] text-slate-400 sm:flex">
                  <span className="kbd">⏎</span> review the full change before approving
                </span>
                {actions.map((a: { action: string; label: string }) => (
                  <button
                    key={a.action}
                    disabled={n.acted || busyId === n.id}
                    className={`btn ${a.action === 'approve' ? 'btn-approve' : 'btn-reject'} min-w-[130px]`}
                    onClick={() => act(n.id, a.action as 'approve' | 'reject')}
                  >
                    {busyId === n.id ? (
                      <span className="spinner !h-3.5 !w-3.5" />
                    ) : a.action === 'approve' ? (
                      <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                        <path d="M2.5 8.5 6 12l7.5-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    ) : (
                      <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                        <path d="m4 4 8 8M12 4l-8 8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                      </svg>
                    )}
                    {busyId === n.id ? 'Working…' : a.action === 'approve' ? 'Approve change' : 'Reject'}
                  </button>
                ))}
                {n.change_id && (
                  <Link to={`/changes/${n.change_id}`} className="btn btn-ghost">
                    Open change #{n.change_id}
                    <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                      <path d="m6 3.5 4.5 4.5L6 12.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </Link>
                )}
              </div>
            </article>
          )
        })}
      </div>

      <Toast message={toast} />
    </div>
  )
}
