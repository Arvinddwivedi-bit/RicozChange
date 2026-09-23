import { Loading } from '../App'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDate, type ChangeT } from '../api'
import { ScoreBadge, StatusBadge } from '../components/Components'

interface CabItem {
  id: number
  change_id: number
  decision: string
  votes: { voter: string; vote: string }[]
  change: ChangeT | null
}
interface CabMeeting {
  id: number
  scheduled_at: string
  notes: string
  status: string
  items: CabItem[]
}

export default function CABPage() {
  const [meetings, setMeetings] = useState<CabMeeting[] | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)
  const [newWhen, setNewWhen] = useState('')
  const [newNotes, setNewNotes] = useState('')
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(() => {
    api<CabMeeting[]>('/api/cab').then((rows) => {
      setMeetings(rows)
      const upcoming = rows.find((m) => m.status === 'scheduled')
      if (upcoming) setOpenId((cur) => cur ?? upcoming.id)
    })
  }, [])

  useEffect(load, [load])

  async function decide(itemId: number, decision: string) {
    setErr(null)
    try {
      await api(`/api/cab/items/${itemId}/decide`, { method: 'POST', body: JSON.stringify({ decision }) })
      load()
    } catch (e) {
      setErr(String(e))
    }
  }

  async function createMeeting() {
    setErr(null)
    try {
      await api('/api/cab', { method: 'POST', body: JSON.stringify({ scheduled_at: newWhen, notes: newNotes }) })
      setNewWhen('')
      setNewNotes('')
      load()
    } catch (e) {
      setErr(String(e))
    }
  }

  if (!meetings) return <Loading />

  const open = meetings.find((m) => m.id === openId)

  return (
    <div className="p-8 grid xl:grid-cols-3 gap-6 items-start">
      <div className="xl:col-span-2 space-y-5">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">CAB meetings</h1>
          <p className="text-sm text-slate-500">The Tuesday ritual, minus the spreadsheet. Approve straight from the agenda.</p>
        </div>

        {err && <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{err}</div>}

        <div className="card divide-y divide-slate-100">
          {meetings.length === 0 && <div className="p-6 text-sm text-slate-500">No meetings yet.</div>}
          {meetings.map((m) => (
            <button key={m.id} className={`w-full text-left p-4 hover:bg-slate-50 ${m.id === openId ? 'bg-brand-50/50' : ''}`} onClick={() => setOpenId(m.id)}>
              <div className="flex items-center justify-between">
                <span className="font-semibold">CAB #{m.id} · {fmtDate(m.scheduled_at)}</span>
                <StatusBadge status={m.status} />
              </div>
              <div className="text-xs text-slate-500 mt-1">{m.notes || 'no notes'} · {m.items.length} item(s)</div>
            </button>
          ))}
        </div>

        {open && (
          <div className="card p-5">
            <h2 className="font-bold mb-3">Agenda — CAB #{open.id} ({fmtDate(open.scheduled_at)})</h2>
            <div className="space-y-3">
              {open.items.length === 0 && <p className="text-sm text-slate-500">Empty agenda.</p>}
              {open.items.map((it) => (
                <div key={it.id} className="rounded-lg border border-slate-200 p-4">
                  {it.change ? (
                    <>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex items-center gap-2">
                          <ScoreBadge score={it.change.risk_score} />
                          <Link to={`/changes/${it.change.id}`} className="font-semibold hover:underline">
                            #{it.change.id} {it.change.title}
                          </Link>
                        </div>
                        <span className={`text-xs font-bold uppercase ${it.decision === 'approved' ? 'text-emerald-600' : it.decision === 'rejected' ? 'text-red-600' : 'text-slate-400'}`}>
                          {it.decision}
                        </span>
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {it.change.risk_type} · {it.change.systems.map((s) => s.name).join(', ')}
                      </div>
                      {it.change.factors && it.change.factors.length > 0 && (
                        <div className="mt-2 text-xs text-slate-600">
                          Top risk drivers:{' '}
                          {it.change.factors
                            .slice()
                            .sort((a, b) => b.points - a.points)
                            .slice(0, 2)
                            .map((f) => `${f.points > 0 ? '+' : ''}${f.points} ${f.label}`)
                            .join(' · ')}
                        </div>
                      )}
                      {it.decision === 'pending' && it.change.status === 'submitted' && (
                        <div className="mt-3 flex gap-2">
                          <button className="btn btn-success" onClick={() => decide(it.id, 'approved')}>Approve</button>
                          <button className="btn btn-danger" onClick={() => decide(it.id, 'rejected')}>Reject</button>
                          <button className="btn btn-ghost" onClick={() => decide(it.id, 'deferred')}>⏸ Defer</button>
                        </div>
                      )}
                    </>
                  ) : (
                    <span className="text-sm text-slate-500">Change #{it.change_id} (missing)</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="card p-5 space-y-3">
        <h2 className="font-bold">Schedule a meeting</h2>
        <input type="datetime-local" className="input" value={newWhen} onChange={(e) => setNewWhen(e.target.value)} />
        <input className="input" placeholder="Notes (optional)" value={newNotes} onChange={(e) => setNewNotes(e.target.value)} />
        <button className="btn btn-primary w-full" disabled={!newWhen} onClick={createMeeting}>
          Create CAB meeting
        </button>
        <p className="text-xs text-slate-500">Submitted changes auto-attach to the next scheduled meeting.</p>
      </div>
    </div>
  )
}
