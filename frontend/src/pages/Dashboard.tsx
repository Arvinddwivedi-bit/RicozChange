import { Loading } from '../App'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type ChangeT } from '../api'
import { ChangeRowMeta, ScoreBadge, StatusBadge, TypeBadge } from '../components/Components'

interface Dash {
  total_changes: number
  by_status: Record<string, number>
  pending_approvals: number
  cfr: { total: number; success: number; failed: number; partial: number; failure_rate_pct: number }
  upcoming: ChangeT[]
  top_risk: ChangeT[]
}

export default function Dashboard() {
  const [data, setData] = useState<Dash | null>(null)

  useEffect(() => {
    api<Dash>('/api/dashboard').then(setData)
  }, [])

  if (!data) return <Loading />

  const cfr = data.cfr.failure_rate_pct
  const cfrTone = cfr >= 20 ? 'text-red-600' : cfr >= 10 ? 'text-amber-600' : 'text-emerald-600'

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Dashboard</h1>
          <p className="text-sm text-slate-500">Live view of every change, approval and outcome</p>
        </div>
        <Link to="/changes?new=1" className="btn btn-primary">
          + New change
        </Link>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Kpi label="Total changes" value={data.total_changes} />
        <Kpi label="Pending approvals" value={data.pending_approvals} accent="text-sky-600" />
        <Kpi label="In flight" value={(data.by_status['submitted'] ?? 0) + (data.by_status['approved'] ?? 0) + (data.by_status['implementing'] ?? 0)} accent="text-brand-600" />
        <div className="card p-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Change failure rate</div>
          <div className={`mt-1 text-3xl font-extrabold ${cfrTone}`}>{cfr}%</div>
          <div className="mt-1 text-xs text-slate-500">
            {data.cfr.failed + data.cfr.partial} of {data.cfr.total} outcomes failed or partial
          </div>
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <section className="card p-5">
          <h2 className="font-bold mb-3">Top open risk</h2>
          <div className="space-y-3">
            {data.top_risk.length === 0 && <p className="text-sm text-slate-500">No open changes.</p>}
            {data.top_risk.map((c) => (
              <Link key={c.id} to={`/changes/${c.id}`} className="block rounded-lg border border-slate-100 p-3 hover:border-brand-200 hover:bg-brand-50/40">
                <div className="flex items-center gap-2">
                  <ScoreBadge score={c.risk_score} />
                  <span className="font-semibold text-sm">{c.title}</span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <StatusBadge status={c.status} />
                  <TypeBadge type={c.risk_type} />
                </div>
                <ChangeRowMeta change={c} />
              </Link>
            ))}
          </div>
        </section>

        <section className="card p-5">
          <h2 className="font-bold mb-3">Upcoming windows</h2>
          <div className="space-y-3">
            {data.upcoming.length === 0 && <p className="text-sm text-slate-500">Nothing scheduled yet.</p>}
            {data.upcoming.map((c) => (
              <Link key={c.id} to={`/changes/${c.id}`} className="block rounded-lg border border-slate-100 p-3 hover:border-brand-200 hover:bg-brand-50/40">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-sm">{c.title}</span>
                  <StatusBadge status={c.status} />
                </div>
                <ChangeRowMeta change={c} />
              </Link>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}

function Kpi({ label, value, accent = 'text-slate-800' }: { label: string; value: number; accent?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-extrabold ${accent}`}>{value}</div>
    </div>
  )
}
