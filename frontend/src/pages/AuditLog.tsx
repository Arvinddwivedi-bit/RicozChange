import { Loading } from '../App'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDate } from '../api'
import { ActivitySpark } from '../components/Charts'

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
  created: 'bg-sky-50 text-sky-700',
  submitted: 'bg-blue-50 text-blue-700',
  approved: 'bg-emerald-50 text-emerald-700',
  rejected: 'bg-brand-50 text-brand-700',
  implementing: 'bg-amber-50 text-amber-700',
  completed: 'bg-emerald-100 text-emerald-800',
  failed: 'bg-red-50 text-red-700',
  cancelled: 'bg-slate-100 text-slate-500',
  denied: 'bg-red-50 text-red-600',
  user_provisioned: 'bg-brand-50 text-brand-700',
  slack_installed: 'bg-brand-50 text-brand-700',
  slack_delivery: 'bg-slate-100 text-slate-600',
}

function actionColor(action: string): string {
  for (const key of Object.keys(ACTION_COLORS)) {
    if (action.startsWith(key)) return ACTION_COLORS[key]
  }
  return 'bg-slate-100 text-slate-600'
}

export default function AuditLog() {
  const [rows, setRows] = useState<AuditRow[] | null>(null)
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(150)

  useEffect(() => {
    api<AuditRow[]>(`/api/audit?limit=${limit}`).then(setRows)
  }, [limit])

  if (!rows) return <Loading />

  const filtered = rows.filter((r) => {
    if (!query) return true
    const q = query.toLowerCase()
    return (
      r.actor.toLowerCase().includes(q) ||
      r.action.toLowerCase().includes(q) ||
      r.detail.toLowerCase().includes(q) ||
      `${r.entity_type} ${r.entity_id}`.toLowerCase().includes(q)
    )
  })

  return (
    <div className="p-8 max-w-5xl space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Audit log</h1>
        <p className="text-sm text-slate-500">
          Append-only trail of every action — transitions, decisions, denials, deliveries and provisions. Written once, never edited.
        </p>
      </div>

      <section className="card p-5">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="font-bold">Activity</h2>
          <span className="text-xs text-slate-400">{rows.length} entries loaded</span>
        </div>
        <div className="mt-4">
          <ActivitySpark rows={rows} days={14} />
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <input
          className="input max-w-sm"
          placeholder="Filter by actor, action, detail…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select className="input max-w-[9rem]" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
          <option value={150}>Last 150</option>
          <option value={300}>Last 300</option>
          <option value={500}>Last 500</option>
        </select>
        <span className="text-xs text-slate-500">{filtered.length} entries</span>
      </div>

      <div className="card divide-y divide-slate-100">
        {filtered.length === 0 && <div className="p-6 text-sm text-slate-500">No entries match.</div>}
        {filtered.map((r) => (
          <div key={r.id} className="px-4 py-3 flex items-start gap-3 text-sm">
            <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-semibold ${actionColor(r.action)}`}>
              {r.action}
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-semibold text-slate-800">{r.actor}</span>
                <span className="text-xs text-slate-400">
                  {r.entity_type === 'auth' ? '' : `→ ${r.entity_type} #${r.entity_id}`}
                </span>
              </div>
              {r.detail && <div className="text-xs text-slate-500 mt-0.5 break-words">{r.detail}</div>}
            </div>
            <div className="shrink-0 text-right">
              <div className="text-xs text-slate-500">{fmtDate(r.created_at)}</div>
              {r.entity_type === 'change' && (
                <Link to={`/changes/${r.entity_id}`} className="text-xs text-brand-600 hover:underline">
                  view #{r.entity_id}
                </Link>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
