import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDate } from '../api'
import { ActivitySpark } from '../components/Charts'
import { ScrollText, Search, Filter, Clock, Activity, Download, Plus, CheckCircle2, XCircle, ArrowRight, Zap, Box, ShieldCheck, FileTerminal } from 'lucide-react'

interface AuditRow {
  id: number
  entity_type: string
  entity_id: number
  action: string
  actor: string
  detail: string
  created_at: string
}

const ACTION_COLORS: Record<string, string> = {
  created: 'bg-sky-50 text-sky-700 ring-sky-600/20',
  submitted: 'bg-blue-50 text-blue-700 ring-blue-600/20',
  approved: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  rejected: 'bg-brand-50 text-brand-700 ring-brand-600/20',
  implementing: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  completed: 'bg-emerald-100 text-emerald-800 ring-emerald-600/20',
  failed: 'bg-red-50 text-red-700 ring-red-600/20',
  cancelled: 'bg-slate-100 text-slate-500 ring-slate-500/20',
  denied: 'bg-red-50 text-red-600 ring-red-600/20',
  user_provisioned: 'bg-purple-50 text-purple-700 ring-purple-600/20',
  slack_installed: 'bg-purple-50 text-purple-700 ring-purple-600/20',
  slack_delivery: 'bg-slate-100 text-slate-600 ring-slate-500/20',
}

function actionColor(action: string): string {
  for (const key of Object.keys(ACTION_COLORS)) {
    if (action.startsWith(key)) return ACTION_COLORS[key]
  }
  return 'bg-slate-100 text-slate-600 ring-slate-500/20'
}

function ActionIcon({ action, className }: { action: string, className?: string }) {
  const s = action.toLowerCase();
  let Icon = ArrowRight;
  if (s.includes('created')) Icon = Plus;
  else if (s.includes('approved') || s.includes('completed')) Icon = CheckCircle2;
  else if (s.includes('rejected') || s.includes('failed') || s.includes('denied') || s.includes('cancelled')) Icon = XCircle;
  else if (s.includes('provisioned') || s.includes('slack')) Icon = Zap;
  return <Icon className={className} size={14} />
}

function getInitials(name: string) {
  if (!name) return '?'
  return name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase()
}

export default function AuditLog() {
  const [rows, setRows] = useState<AuditRow[] | null>(null)
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(150)

  useEffect(() => {
    api<AuditRow[]>(`/api/audit?limit=${limit}`).then(setRows)
  }, [limit])

  const filtered = rows?.filter((r) => {
    if (!query) return true
    const q = query.toLowerCase()
    return (
      r.actor.toLowerCase().includes(q) ||
      r.action.toLowerCase().includes(q) ||
      r.detail.toLowerCase().includes(q) ||
      `${r.entity_type} ${r.entity_id}`.toLowerCase().includes(q)
    )
  }) || []

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div>
          <div className="eyebrow flex items-center gap-2 text-brand-600">
            <ShieldCheck size={16} />
            Trust &amp; Compliance
          </div>
          <h1 className="page-title flex items-center gap-2 mt-2">
            <ScrollText className="text-slate-800" />
            Audit Log
          </h1>
          <p className="mt-2 text-sm text-slate-500 max-w-2xl">
            Append-only trail of every action — transitions, decisions, denials, deliveries and provisions. Written once, never edited.
          </p>
        </div>
        <button className="btn btn-ghost flex items-center gap-2 text-slate-600">
          <Download size={16} />
          Export CSV
        </button>
      </div>

      <section className="card p-5 border border-slate-200/60 shadow-sm">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="font-bold flex items-center gap-2 text-slate-800">
            <Activity size={18} className="text-brand-500" />
            Activity
          </h2>
          <span className="text-xs font-medium text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">
            {rows ? rows.length : 0} entries loaded
          </span>
        </div>
        <div className="mt-4 h-24">
          {rows ? (
            <ActivitySpark rows={rows} days={14} />
          ) : (
            <div className="w-full h-full bg-slate-50 animate-pulse rounded-md" />
          )}
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-3 bg-white p-2 rounded-lg border border-slate-200 shadow-sm">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
          <input
            className="input w-full pl-9 border-none shadow-none focus:ring-0 bg-transparent"
            placeholder="Filter by actor, action, detail…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="h-6 w-px bg-slate-200 mx-2" />
        <div className="relative flex items-center">
          <Filter className="absolute left-3 text-slate-400" size={16} />
          <select className="input w-[9rem] pl-9 border-none shadow-none focus:ring-0 bg-transparent text-sm font-medium text-slate-600 cursor-pointer appearance-none" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
            <option value={150}>Last 150</option>
            <option value={300}>Last 300</option>
            <option value={500}>Last 500</option>
          </select>
        </div>
        <span className="text-xs text-slate-400 font-medium px-3 ml-auto border-l border-slate-100">
          {filtered.length} matching
        </span>
      </div>

      <div className="card divide-y divide-slate-100/80 shadow-sm border-slate-200/60 overflow-hidden">
        {!rows && (
          <div className="p-6 space-y-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="flex gap-4 animate-pulse">
                <div className="w-24 h-6 bg-slate-100 rounded-md shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="w-48 h-4 bg-slate-100 rounded" />
                  <div className="w-full h-3 bg-slate-50 rounded" />
                </div>
              </div>
            ))}
          </div>
        )}
        {rows && filtered.length === 0 && (
          <div className="p-12 text-center text-slate-500">
            <Search className="mx-auto text-slate-300 mb-3" size={32} />
            <p className="text-sm">No entries match your filter.</p>
          </div>
        )}
        {filtered.map((r) => (
          <div key={r.id} className="px-5 py-4 flex items-start gap-4 text-sm group hover:bg-slate-50/50 transition-colors">
            <span className={`shrink-0 flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${actionColor(r.action)}`}>
              <ActionIcon action={r.action} />
              <span className="capitalize">{r.action.replace(/_/g, ' ')}</span>
            </span>
            
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2">
                <div className="flex items-center gap-1.5 text-slate-700">
                  <div className="w-5 h-5 rounded-full bg-slate-200 text-[10px] font-bold flex items-center justify-center text-slate-600 shrink-0">
                    {getInitials(r.actor)}
                  </div>
                  <span className="font-semibold">{r.actor}</span>
                </div>
                {r.entity_type !== 'auth' && (
                  <>
                    <span className="text-slate-300">→</span>
                    <span className="text-xs font-medium text-slate-500 flex items-center gap-1">
                      {r.entity_type === 'change' ? <FileTerminal size={12}/> : <Box size={12}/>}
                      {r.entity_type} #{r.entity_id}
                    </span>
                  </>
                )}
              </div>
              {r.detail && (
                <div className="text-[13px] text-slate-600 mt-2 bg-slate-50/80 p-2.5 rounded-md border border-slate-100 break-words leading-relaxed">
                  {r.detail}
                </div>
              )}
            </div>

            <div className="shrink-0 flex flex-col items-end gap-1.5">
              <div className="flex items-center gap-1 text-[11px] font-medium text-slate-400 uppercase tracking-wider">
                <Clock size={12} />
                {fmtDate(r.created_at)}
              </div>
              {r.entity_type === 'change' && (
                <Link to={`/changes/${r.entity_id}`} className="text-xs font-semibold text-brand-600 hover:text-brand-700 hover:underline inline-flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  View Record <ArrowRight size={12} />
                </Link>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
