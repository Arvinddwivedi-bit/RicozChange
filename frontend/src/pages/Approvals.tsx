import { Loading } from '../App'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type NotificationT } from '../api'
import { useBoot } from '../App'

export default function Approvals() {
  const { boot } = useBoot()
  const [notes, setNotes] = useState<NotificationT[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [showDecided, setShowDecided] = useState(false)

  const load = useCallback(() => {
    api<NotificationT[]>('/api/notifications').then(setNotes)
  }, [])

  useEffect(load, [load])

  async function act(id: number, action: 'approve' | 'reject') {
    setErr(null)
    setBusyId(id)
    try {
      await api(`/api/notifications/${id}/act`, { method: 'POST', body: JSON.stringify({ action }) })
      load()
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusyId(null)
    }
  }

  if (!notes) return <Loading />

  const pending = notes.filter((n) => !n.acted)
  const decided = notes.filter((n) => n.acted)
  const visible = showDecided ? notes : pending

  const pendingForMe = pending.filter((n) => {
    const blocks = JSON.stringify(n.message.blocks)
    return blocks.includes(boot.actor.name)
  })

  return (
    <div className="p-8 max-w-4xl space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Approval inbox</h1>
          <p className="text-sm text-slate-500">
            Every decision lands here — and in Slack when the workspace is connected. The card shows the full risk picture:
            score, the &ldquo;why&rdquo;, and one-click approve/reject.
          </p>
        </div>
        <span className="card px-3 py-2 text-xs shrink-0">
          <span className="font-bold text-brand-600">{pending.length}</span> pending ·{' '}
          <span className="font-semibold text-slate-700">{pendingForMe.length}</span> awaiting you
        </span>
      </div>

      {err && <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{err}</div>}

      <label className="inline-flex items-center gap-2 text-sm text-slate-600">
        <input type="checkbox" checked={showDecided} onChange={(e) => setShowDecided(e.target.checked)} />
        Show decided ({decided.length})
      </label>

      {visible.length === 0 && (
        <div className="card p-6 text-sm text-slate-500">
          {showDecided ? 'No approval history yet.' : 'Inbox zero. New approval requests appear here automatically.'}
        </div>
      )}

      <div className="space-y-4">
        {visible.map((n) => (
          <div key={n.id} className="card overflow-hidden">
            <div className="bg-navy/95 text-white px-4 py-2.5 text-xs flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 font-semibold">
                <span className="w-4 h-4 rounded bg-brand-600 inline-flex items-center justify-center text-[9px] font-bold">#</span>
                {n.channel}
              </span>
              <span className="text-white/40">approval request</span>
              {n.sent_at && <span className="text-white/30">delivered via Slack</span>}
              {n.acted && (
                <span
                  className={`ml-auto rounded px-2 py-0.5 font-semibold ${
                    n.acted_action === 'approved' ? 'bg-emerald-600' : 'bg-brand-600'
                  }`}
                >
                  {n.acted_action}
                </span>
              )}
            </div>
            <div className="p-4 space-y-3">
              <div className="font-semibold text-sm">Approval needed: change #{n.change_id} — see details below</div>
              {n.message.blocks.map((b, i) => {
                if (b.type === 'section' && b.text) {
                  const cleaned = b.text.replace(/\*/g, '').replace(/^🔔\s*/, '')
                  if (cleaned.includes(`change #${n.change_id}`) && cleaned.startsWith('Approval needed')) return null
                  return <div key={i} className="text-sm text-slate-700">{cleaned}</div>
                }
                if (b.type === 'context' && b.fields) {
                  return (
                    <div key={i} className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                      {Object.entries(b.fields).map(([k, v]) => (
                        <div key={k} className="rounded bg-slate-50 border border-slate-100 p-2">
                          <div className="text-slate-400 uppercase tracking-wide">{k}</div>
                          <div className="font-semibold text-slate-700">{String(v) || '—'}</div>
                        </div>
                      ))}
                    </div>
                  )
                }
                if (b.type === 'risk_why' && b.items) {
                  return (
                    <div key={i} className="rounded-lg border border-brand-100 bg-brand-50/60 p-3 space-y-1">
                      <div className="text-[10px] font-bold uppercase text-brand-700 tracking-wide">Why this score</div>
                      {b.items.map((f, j) => (
                        <div key={j} className="flex gap-2 text-xs">
                          <span className={`font-mono font-bold ${f.points >= 0 ? 'text-brand-600' : 'text-emerald-600'}`}>
                            {f.points > 0 ? `+${f.points}` : f.points}
                          </span>
                          <span className="text-slate-700">{f.label}</span>
                        </div>
                      ))}
                    </div>
                  )
                }
                if (b.type === 'actions' && b.actions) {
                  return (
                    <div key={i} className="flex gap-2">
                      {b.actions.map((a) => (
                        <button
                          key={a.action}
                          disabled={n.acted || busyId === n.id}
                          className={`btn ${a.action === 'approve' ? 'btn-success' : 'btn-danger'}`}
                          onClick={() => act(n.id, a.action as 'approve' | 'reject')}
                        >
                          {a.label}
                        </button>
                      ))}
                      {n.change_id && (
                        <Link to={`/changes/${n.change_id}`} className="btn btn-ghost">
                          Open change #{n.change_id}
                        </Link>
                      )}
                    </div>
                  )
                }
                if (b.type === 'footer' && b.text) {
                  return <div key={i} className="text-[10px] text-slate-400">{b.text}</div>
                }
                return null
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
