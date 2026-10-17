import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDate, type NotificationT } from '../api'
import { useBoot } from '../App'
import { CheckCircle2, XCircle, Clock, Bell, Shield, MessageSquare, ExternalLink, Activity, Search, AlertTriangle, Inbox, Check } from 'lucide-react'
import clsx from 'clsx'

/* ---------- small building blocks ---------- */

function Toast({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div className="toast bg-slate-900 text-white font-medium flex items-center gap-2 shadow-xl" role="status">
      <span className="toast-ok-icon flex items-center justify-center bg-emerald-500 rounded-full w-5 h-5 shrink-0">
        <Check className="w-3.5 h-3.5 text-white" />
      </span>
      {message}
    </div>
  )
}

function RiskMeter({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, score))
  const tier = pct >= 70 ? 'Critical' : pct >= 40 ? 'High' : pct >= 25 ? 'Medium' : 'Low'
  const tierColor = pct >= 70 ? 'text-brand-600' : pct >= 40 ? 'text-orange-600' : pct >= 25 ? 'text-amber-600' : 'text-emerald-600'
  const trackBg = pct >= 70 ? 'bg-brand-500' : pct >= 40 ? 'bg-orange-500' : pct >= 25 ? 'bg-amber-500' : 'bg-emerald-500'
  
  return (
    <div>
      <div className="meter-track bg-slate-100 overflow-hidden relative">
        <div className={clsx("absolute top-0 bottom-0 left-0 transition-all duration-1000 ease-out", trackBg)} style={{ width: `${pct}%` }} />
        <div className="absolute top-0 bottom-0 right-0 w-full bg-gradient-to-r from-transparent to-white/20" />
      </div>
      <div className="mt-2 flex items-center justify-between text-[11px] font-medium text-slate-400">
        <span>Low</span>
        <span>Medium</span>
        <span>High</span>
        <span className={clsx("font-semibold uppercase tracking-wider text-xs flex items-center gap-1", tierColor)}>
          {pct >= 70 && <AlertTriangle className="w-3.5 h-3.5" />}
          {tier}
        </span>
      </div>
    </div>
  )
}

function Metric({ label, value, tone = 'navy', icon }: { label: string; value: number; tone?: 'navy' | 'red' | 'amber' | 'slate'; icon?: React.ReactNode }) {
  const colors: Record<string, string> = {
    navy: 'text-slate-900',
    red: 'text-brand-600',
    amber: 'text-amber-600',
    slate: 'text-slate-500',
  }
  return (
    <div className="metric flex flex-col justify-between border border-slate-100 shadow-sm bg-white hover:border-slate-200 transition-colors">
      <div className="metric-label flex items-center gap-1.5 text-slate-500">{icon}{label}</div>
      <div className={clsx("metric-value text-3xl font-bold mt-2", colors[tone])}>{value}</div>
    </div>
  )
}

function InfoCell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 bg-slate-50/50 p-3 rounded-lg border border-slate-100">
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.07em] text-slate-400 mb-1.5 flex items-center gap-1.5">
        {label}
      </div>
      <div className="text-[13.5px] font-medium text-slate-900 leading-snug">{children}</div>
    </div>
  )
}

function WhyRow({ label, detail }: { label: string; detail: string }) {
  return (
    <div className="flex items-start gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-slate-50 border border-transparent hover:border-slate-100">
      <AlertTriangle className="w-4 h-4 text-brand-500 shrink-0 mt-0.5" />
      <div className="min-w-0">
        <div className="text-[13px] font-semibold text-slate-900">{label}</div>
        <div className="text-[12px] leading-snug text-slate-500 mt-0.5">{detail}</div>
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
  const [kindFilter, setKindFilter] = useState<'all' | 'slack' | 'teams' | 'email'>('all')
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

  const pending = useMemo(() => (notes ?? []).filter((n) => !n.acted && (n.kind === 'slack' || n.kind === 'teams')), [notes])
  const decided = useMemo(() => (notes ?? []).filter((n) => n.acted && (n.kind === 'slack' || n.kind === 'teams')), [notes])
  const visible = showDecided
    ? notes ?? []
    : (notes ?? []).filter((n) => !n.acted || n.kind !== 'teams')

  const filtered = useMemo(() => {
    let rows = kindFilter === 'all' ? visible : visible.filter((n) => n.kind === kindFilter)
    if (!query.trim()) return rows
    const q = query.toLowerCase()
    rows = rows.filter(
      (n) =>
        String(n.change_id).includes(q) ||
        n.channel.toLowerCase().includes(q) ||
        n.message.text.toLowerCase().includes(q) ||
        (n.message.subject ?? '').toLowerCase().includes(q),
    )
    return rows
  }, [visible, query, kindFilter])

  // Approval cards
  const cards = filtered
    .filter((n) => n.kind === 'slack' || n.kind === 'teams')
    .map((n) => {
    const byType = new Map<string, any>()
    for (const b of n.message.blocks ?? []) byType.set(b.type, b)
    const context = byType.get('context')?.fields ?? {}
    const whyItems: { label: string; points: number }[] = byType.get('risk_why')?.items ?? []
    const actions = byType.get('actions')?.actions ?? []
    return { n, context, whyItems, actions }
  })

  const emailCards = filtered.filter((n) => n.kind === 'email')

  const metrics = useMemo(() => {
    const highRisk = pending.filter((c) => {
      const ctx = c.message.blocks?.find((b) => b.type === 'context')?.fields ?? {}
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
      <div className="mx-auto max-w-[1200px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7 space-y-6">
        <div className="flex justify-between items-center animate-pulse">
          <div className="space-y-3">
            <div className="h-4 w-32 bg-slate-200 rounded" />
            <div className="h-8 w-64 bg-slate-200 rounded" />
          </div>
          <div className="flex gap-2">
            <div className="h-10 w-48 bg-slate-200 rounded-lg" />
            <div className="h-10 w-32 bg-slate-200 rounded-lg" />
            <div className="h-10 w-10 bg-slate-200 rounded-full" />
          </div>
        </div>
        <div className="flex gap-2 animate-pulse mt-4">
           <div className="h-6 w-24 bg-slate-200 rounded-full" />
           <div className="h-6 w-24 bg-slate-200 rounded-full" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 animate-pulse">
          {[1,2,3,4].map(i => <div key={i} className="h-24 bg-slate-100 rounded-xl" />)}
        </div>
        <div className="space-y-4 animate-pulse mt-8">
          {[1,2].map(i => <div key={i} className="h-64 bg-slate-100 rounded-xl" />)}
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1200px] px-4 py-5 sm:px-6 lg:px-8 lg:py-7">
      {/* ---------- header ---------- */}
      <header className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div>
          <div className="eyebrow flex items-center gap-1.5"><Shield className="w-4 h-4 text-brand-500" /> Decide In Seconds</div>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">Approval Inbox</h1>
          <p className="mt-2 text-sm text-slate-500 flex items-center gap-1.5">Review high-risk changes before they reach production.</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative group">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 group-focus-within:text-brand-500 transition-colors" />
            <input
              className="input w-[220px] pl-9 bg-slate-50 focus:bg-white transition-colors text-sm"
              placeholder="Search approvals..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <label className="flex cursor-pointer select-none items-center gap-2 rounded-lg border border-slate-200 bg-white px-3.5 py-[9px] text-sm font-medium text-slate-700 hover:bg-slate-50 transition-colors shadow-sm">
            <input type="checkbox" className="accent-brand-600 w-4 h-4 rounded border-slate-300" checked={showDecided} onChange={(e) => setShowDecided(e.target.checked)} />
            Show decided
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-bold text-slate-600">{decided.length}</span>
          </label>
          <button className="relative p-2.5 rounded-full hover:bg-slate-100 text-slate-500 hover:text-slate-700 transition-colors" title="Notifications" aria-label="Notifications">
            <Bell className="w-5 h-5" />
            {metrics.pending > 0 && (
              <span className="absolute 0 top-1 right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand-600 px-1 text-[10px] font-bold text-white shadow-sm ring-2 ring-white">
                {metrics.pending}
              </span>
            )}
          </button>
          <div
            className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-900 text-sm font-bold text-white shadow-sm ring-2 ring-white ml-1 cursor-help"
            title={boot.actor.name}
          >
            {boot.actor.name.split(' ').map((p) => p[0]).slice(0, 2).join('')}
          </div>
        </div>
      </header>

      {/* status pills */}
      <div className="mt-6 flex flex-wrap items-center gap-2">
        <span className="pill pill-red shadow-sm border-brand-100">
          <span className="pill-dot animate-pulse" />
          {metrics.pending} pending
        </span>
        <span className="pill pill-neutral bg-white shadow-sm">{metrics.mine} awaiting you</span>
        {metrics.highRisk > 0 && <span className="pill pill-amber shadow-sm border-amber-200"><span className="pill-dot" />{metrics.highRisk} high risk</span>}
        
        <div className="ml-auto flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1">
          {(['all', 'slack', 'teams', 'email'] as const).map((k) => (
            <button
              key={k}
              onClick={() => setKindFilter(k)}
              className={clsx(
                "rounded-md px-3 py-1.5 text-xs font-semibold capitalize transition-all",
                kindFilter === k 
                  ? 'bg-white text-slate-900 shadow-sm ring-1 ring-slate-200/50' 
                  : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'
              )}
            >
              {k}
            </button>
          ))}
        </div>
      </div>

      {/* ---------- metrics ---------- */}
      <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Metric label="Pending approvals" value={metrics.pending} tone="red" icon={<Clock className="w-4 h-4" />} />
        <Metric label="Awaiting me" value={metrics.mine} tone="navy" icon={<Inbox className="w-4 h-4" />} />
        <Metric label="High risk" value={metrics.highRisk} tone="amber" icon={<AlertTriangle className="w-4 h-4" />} />
        <Metric label="Decided today" value={metrics.decidedToday} tone="slate" icon={<CheckCircle2 className="w-4 h-4" />} />
      </div>

      {err && <div className="mt-6 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 flex items-center gap-2 shadow-sm"><AlertTriangle className="w-5 h-5 text-red-500" />{err}</div>}

      {/* ---------- queue ---------- */}
      <div className="mt-8 space-y-6">
        {cards.length === 0 && (
          <div className="card flex flex-col items-center justify-center p-12 text-center border-dashed border-2 border-slate-200 bg-slate-50/50">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 mb-4 shadow-sm">
              <CheckCircle2 className="w-8 h-8" />
            </div>
            <h3 className="text-xl font-bold text-slate-900">{showDecided ? 'No decided approvals yet' : 'Inbox zero'}</h3>
            <p className="mt-2 max-w-md text-sm text-slate-500">
              {showDecided
                ? 'Approve or reject something and it will show up here in your history.'
                : 'You are all caught up! New approval requests will land here the moment a change is submitted.'}
            </p>
          </div>
        )}

        {emailCards.map((n) => (
          <article key={n.id} className="card p-4 hover:border-slate-300 transition-colors group cursor-default shadow-sm border-slate-200">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="flex min-w-0 items-center gap-4">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-100 text-slate-500 group-hover:bg-slate-200 transition-colors">
                  <MessageSquare className="w-5 h-5" />
                </span>
                <div className="min-w-0">
                  <div className="truncate text-[15px] font-semibold text-slate-900">{n.message.subject ?? n.message.text}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500 font-medium">
                    <span className="text-slate-700 bg-slate-100 px-2 py-0.5 rounded">{n.channel}</span>
                    <span>•</span>
                    <span className="flex items-center gap-1"><Inbox className="w-3.5 h-3.5" /> Email digest</span>
                    {n.sent_at && <><span className="text-slate-300">•</span><span className="flex items-center gap-1"><Clock className="w-3.5 h-3.5" /> {fmtDate(n.sent_at)}</span></>}
                  </div>
                </div>
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <span className="pill pill-blue border-slate-200 bg-slate-50 shadow-sm">Email</span>
                {n.change_id && (
                  <Link to={`/changes/${n.change_id}`} className="btn btn-ghost hover:bg-slate-100 border-slate-200 shadow-sm flex items-center gap-1.5">
                    Open #{n.change_id} <ExternalLink className="w-3.5 h-3.5" />
                  </Link>
                )}
              </div>
            </div>
          </article>
        ))}

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
            <article key={n.id} className="card overflow-hidden shadow-sm border-slate-200 hover:shadow-md transition-shadow">
              {/* card header */}
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 p-5 bg-white">
                <div className="min-w-0">
                  <div className="flex items-center gap-2.5 mb-1.5">
                    <span className={clsx(
                      "inline-flex items-center justify-center rounded-lg min-w-[28px] h-6 px-2 text-[12px] font-bold shadow-sm ring-1 ring-inset",
                      risk >= 70 ? 'bg-brand-50 text-brand-700 ring-brand-500/30' : 
                      risk >= 40 ? 'bg-amber-50 text-amber-700 ring-amber-500/30' : 'bg-emerald-50 text-emerald-700 ring-emerald-500/30'
                    )}>
                      {risk}
                    </span>
                    <span className="text-[13px] font-bold uppercase tracking-wider text-slate-500">Change #{n.change_id}</span>
                  </div>
                  <h2 className="truncate text-xl font-bold tracking-tight text-slate-900">{title}</h2>
                  <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-slate-500 font-medium">
                    <span className="flex items-center gap-1.5">By <span className="text-slate-800 bg-slate-100 px-2 py-0.5 rounded shadow-sm">{n.channel}</span></span>
                    <span className="text-slate-300">•</span>
                    <span className="flex items-center gap-1.5"><MessageSquare className="w-4 h-4 text-slate-400" /> {n.sent_at ? `Delivered ${fmtDate(n.sent_at)}` : 'Slack message'}</span>
                    <span className="text-slate-300">•</span>
                    <span className="flex items-center gap-1.5"><Clock className="w-4 h-4 text-slate-400" /> {when}</span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2 flex-col sm:flex-row items-end sm:items-center">
                  <span className={clsx(
                    "pill uppercase tracking-wider font-bold shadow-sm border",
                    cls === 'major' || cls === 'emergency' ? 'pill-red border-red-200' : 
                    cls === 'standard' ? 'pill-green border-emerald-200' : 'pill-blue border-blue-200'
                  )}>
                    {String(cls)}
                  </span>
                  {n.acted ? (
                    <span className={clsx("pill font-bold shadow-sm border", n.acted_action === 'approved' ? 'pill-green border-emerald-200' : 'pill-red border-red-200')}>
                      {n.acted_action === 'approved' ? <CheckCircle2 className="w-3.5 h-3.5 inline mr-1" /> : <XCircle className="w-3.5 h-3.5 inline mr-1" />}
                      {n.acted_action === 'approved' ? 'Approved' : 'Rejected'}
                    </span>
                  ) : (
                    <span className="pill pill-amber shadow-sm border-amber-200 font-bold"><span className="pill-dot animate-pulse" />Pending</span>
                  )}
                </div>
              </div>

              {/* info grid */}
              <div className="grid grid-cols-2 gap-4 border-b border-slate-100 p-5 md:grid-cols-4 bg-slate-50/30">
                <InfoCell label="Risk Score">
                  <div className="flex items-baseline gap-2">
                    <span className="text-lg font-bold">{risk}</span>
                    <span className="text-sm font-medium text-slate-400">/ 100</span>
                    <span className={clsx("ml-auto text-[12px] font-bold uppercase tracking-wider px-2 py-0.5 rounded", 
                      risk >= 70 ? 'bg-brand-100 text-brand-700' : 
                      risk >= 40 ? 'bg-orange-100 text-orange-700' : 'bg-emerald-100 text-emerald-700'
                    )}>
                      {risk >= 70 ? 'Critical' : risk >= 40 ? 'High' : 'Moderate'}
                    </span>
                  </div>
                </InfoCell>
                <InfoCell label="Change class"><span className="capitalize">{String(context.Class ?? '—')}</span></InfoCell>
                <InfoCell label="Change window">{String(context.Window ?? 'Not scheduled')}</InfoCell>
                <InfoCell label="Affected systems">
                  <div className="flex flex-wrap gap-1.5 mt-0.5">
                    {String(context.Systems ?? '')
                      .split(',')
                      .filter(Boolean)
                      .map((s) => (
                        <span key={s} className="rounded border border-slate-200 bg-white px-2 py-0.5 font-mono text-[11px] font-bold text-slate-700 shadow-sm">
                          {s.trim()}
                        </span>
                      ))}
                  </div>
                </InfoCell>
              </div>

              {/* risk assessment */}
              <div className="border-b border-slate-100 p-5">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="text-sm font-bold uppercase tracking-wider text-slate-800 flex items-center gap-2">
                    <Activity className="w-4 h-4 text-brand-500" /> Risk Assessment
                  </h3>
                  <span className="text-sm font-bold text-slate-900 bg-slate-100 px-2.5 py-0.5 rounded-full shadow-sm">
                    {risk} <span className="text-slate-400 font-medium">/ 100</span>
                  </span>
                </div>
                <div className="mb-6 bg-slate-50 p-4 rounded-xl border border-slate-100">
                  <RiskMeter score={risk} />
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {whyFallback(whyItems, String(context.Class ?? '')).slice(0, 4).map((label) => (
                    <WhyRow key={label} label={label} detail="Contributing factor from scoring engine" />
                  ))}
                </div>
              </div>

              {/* blast radius */}
              <div className="grid gap-4 border-b border-slate-100 p-5 md:grid-cols-3 bg-slate-50/30">
                <InfoCell label="Affected systems">
                  <div className="space-y-1.5 mt-1">
                    {String(context.Systems ?? '').split(',').filter(Boolean).map((s) => (
                      <div key={s} className="font-mono text-xs font-medium text-slate-700 flex items-center gap-1.5 before:content-[''] before:w-1.5 before:h-1.5 before:bg-slate-300 before:rounded-full">{s.trim()}</div>
                    ))}
                  </div>
                </InfoCell>
                <InfoCell label="Dependencies">
                  <div className="mt-1 text-xs font-medium text-slate-700 flex items-start gap-1.5">
                    <Activity className="w-4 h-4 text-slate-400 shrink-0" />
                    Upstream services in blast radius
                  </div>
                </InfoCell>
                <InfoCell label="Potential impact">
                  <div className={clsx("mt-1 text-xs font-medium flex items-start gap-1.5 p-2 rounded-lg border", 
                    risk >= 70 ? 'bg-brand-50 text-brand-800 border-brand-100' : 'bg-slate-50 text-slate-700 border-slate-200'
                  )}>
                    {risk >= 70 ? <AlertTriangle className="w-4 h-4 shrink-0 text-brand-500" /> : <Shield className="w-4 h-4 shrink-0 text-slate-400" />}
                    {risk >= 70 ? 'Customer-facing interruption possible' : 'Limited service impact'}
                  </div>
                </InfoCell>
              </div>

              {/* action footer */}
              <div className="flex flex-wrap items-center gap-3 bg-slate-50/80 px-5 py-4 border-t border-slate-100">
                <span className="mr-auto hidden items-center gap-1.5 text-xs font-medium text-slate-500 sm:flex">
                  <span className="kbd bg-white border border-slate-200 shadow-sm text-slate-700 px-2 py-0.5 rounded font-mono">⏎</span> 
                  Review the full change before making a decision
                </span>
                
                {actions.map((a: { action: string; label: string }) => (
                  <button
                    key={a.action}
                    disabled={n.acted || busyId === n.id}
                    className={clsx(
                      "btn min-w-[140px] flex items-center justify-center gap-2 shadow-sm font-semibold transition-all",
                      a.action === 'approve' 
                        ? 'btn-approve hover:shadow-md' 
                        : 'btn-reject hover:shadow-md'
                    )}
                    onClick={() => act(n.id, a.action as 'approve' | 'reject')}
                  >
                    {busyId === n.id ? (
                      <Clock className="w-4 h-4 animate-spin" />
                    ) : a.action === 'approve' ? (
                      <CheckCircle2 className="w-4 h-4" />
                    ) : (
                      <XCircle className="w-4 h-4" />
                    )}
                    {busyId === n.id ? 'Processing...' : a.action === 'approve' ? 'Approve Change' : 'Reject Change'}
                  </button>
                ))}
                
                {n.change_id && (
                  <Link to={`/changes/${n.change_id}`} className="btn btn-ghost bg-white border border-slate-200 shadow-sm hover:bg-slate-50 hover:border-slate-300 font-semibold flex items-center gap-1.5 ml-2">
                    View Details
                    <ExternalLink className="w-4 h-4" />
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
