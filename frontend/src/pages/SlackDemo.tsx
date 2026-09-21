import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type NotificationT } from '../api'

export default function SlackDemo() {
  const [notes, setNotes] = useState<NotificationT[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

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

  if (!notes) return <div className="p-8 text-slate-500">Loading…</div>

  return (
    <div className="p-8 max-w-3xl space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Slack approvals — demo outbox</h1>
        <p className="text-sm text-slate-500">
          In production these are real Slack interactive messages. The payload here is exactly what the Slack app would send —
          score, the "why", and one-click decisions. Approve one and watch the change move.
        </p>
      </div>

      {err && <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{err}</div>}

      {notes.length === 0 && (
        <div className="card p-6 text-sm text-slate-500">
          Nothing queued yet. Submit a normal/major change and the approval requests land here.
        </div>
      )}

      <div className="space-y-4">
        {notes.map((n) => (
          <div key={n.id} className="card overflow-hidden">
            <div className="bg-slate-800 text-slate-100 px-4 py-2 text-xs flex items-center gap-2">
              <span className="font-bold">{n.channel}</span>
              <span className="text-slate-400">· Slack</span>
              {n.acted && (
                <span className={`ml-auto rounded px-2 py-0.5 font-semibold ${n.acted_action === 'approved' ? 'bg-emerald-600' : 'bg-red-600'}`}>
                  {n.acted_action}
                </span>
              )}
            </div>
            <div className="p-4 space-y-3">
              <div className="font-semibold text-sm">{n.message.text}</div>
              {n.message.blocks.map((b, i) => {
                if (b.type === 'section' && b.text) {
                  return <div key={i} className="text-sm">{b.text.replace(/\*/g, '')}</div>
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
                    <div key={i} className="rounded-lg border border-indigo-100 bg-indigo-50/50 p-3 space-y-1">
                      <div className="text-[10px] font-bold uppercase text-indigo-500">Why this score</div>
                      {b.items.map((f, j) => (
                        <div key={j} className="flex gap-2 text-xs">
                          <span className={`font-mono font-bold ${f.points >= 0 ? 'text-red-500' : 'text-emerald-600'}`}>
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
