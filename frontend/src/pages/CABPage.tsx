import { Loading } from '../App'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDate, type ChangeT } from '../api'
import { ScoreBadge, StatusBadge } from '../components/Components'
import { MiniDonut } from '../components/Charts'
import { Users, Plus, Calendar, FileText, CheckCircle2, Clock, ChevronRight, AlertTriangle, XCircle, MoreHorizontal, MessageSquare, TrendingUp, Presentation, Info } from 'lucide-react'

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

  // Decision outcomes across all agenda items (chart data)
  const decisionCounts: Record<string, number> = {}
  for (const m of meetings) for (const it of m.items) decisionCounts[it.decision] = (decisionCounts[it.decision] ?? 0) + 1

  return (
    <div className="p-8 max-w-7xl mx-auto grid lg:grid-cols-12 gap-8 items-start">
      <div className="lg:col-span-8 space-y-6 min-w-0">
        <div>
          <div className="eyebrow flex items-center gap-2 text-brand-600">
            <Presentation size={16} />
            Governance
          </div>
          <h1 className="page-title flex items-center gap-2 mt-2">
            <Users className="text-slate-800" />
            CAB Meetings
          </h1>
          <p className="mt-2 text-sm text-slate-500 leading-relaxed max-w-2xl">
            The Tuesday ritual, minus the spreadsheet. Review high-risk changes, verify risk models, and approve straight from the agenda.
          </p>
        </div>

        <section className="card p-6 border-slate-200/60 shadow-sm flex flex-col sm:flex-row gap-6 sm:items-center">
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline justify-between gap-3 mb-2">
              <h2 className="font-bold flex items-center gap-2 text-slate-800">
                <TrendingUp size={18} className="text-brand-500" /> Decision Outcomes
              </h2>
            </div>
            <p className="text-sm text-slate-500">Historical resolution of all agenda items across past meetings.</p>
          </div>
          <div className="w-32 h-32 shrink-0">
            <MiniDonut
              data={decisionCounts}
              colors={{ approved: '#10b981', rejected: '#d4222c', deferred: '#f59e0b', pending: '#94a3b8' }}
              centerLabel="items"
            />
          </div>
        </section>

        {err && (
          <div className="rounded-xl bg-red-50 border border-red-200 p-4 text-sm text-red-700 flex items-start gap-3 shadow-sm">
            <AlertTriangle size={18} className="shrink-0 mt-0.5 text-red-500" />
            <span className="font-medium">{err}</span>
          </div>
        )}

        <div className="space-y-4">
          <h3 className="font-bold text-slate-800 flex items-center gap-2">
            <Calendar size={18} /> Meeting Schedule
          </h3>
          <div className="card divide-y divide-slate-100/80 shadow-sm border-slate-200/60 overflow-hidden">
            {meetings.length === 0 && (
              <div className="p-10 text-center text-slate-500">
                <Calendar className="mx-auto text-slate-300 mb-3" size={32} />
                <p className="text-sm font-medium">No meetings scheduled yet.</p>
              </div>
            )}
            {meetings.map((m) => (
              <button 
                key={m.id} 
                className={`w-full text-left p-5 transition-colors group flex items-center justify-between ${m.id === openId ? 'bg-brand-50/50 relative' : 'hover:bg-slate-50'}`} 
                onClick={() => setOpenId(m.id)}
              >
                {m.id === openId && <div className="absolute left-0 top-0 bottom-0 w-1 bg-brand-500" />}
                <div>
                  <div className="flex items-center gap-3 mb-1.5">
                    <span className="font-bold text-slate-800 group-hover:text-brand-700 transition-colors">CAB #{m.id}</span>
                    <span className="text-slate-400 text-sm font-medium flex items-center gap-1.5">
                      <Clock size={14} /> {fmtDate(m.scheduled_at)}
                    </span>
                  </div>
                  <div className="text-sm text-slate-600 flex items-center gap-3">
                    <span className="flex items-center gap-1.5"><FileText size={14} className="text-slate-400" /> {m.items.length} item(s)</span>
                    <span className="text-slate-300">•</span>
                    <span className="truncate max-w-[200px] sm:max-w-md flex items-center gap-1.5">
                      <MessageSquare size={14} className="text-slate-400" />
                      {m.notes || 'No agenda notes'}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <StatusBadge status={m.status} />
                  <ChevronRight size={18} className={`transition-transform ${m.id === openId ? 'text-brand-500 translate-x-1' : 'text-slate-300 group-hover:text-slate-400'}`} />
                </div>
              </button>
            ))}
          </div>
        </div>

        {open && (
          <div className="card p-0 shadow-sm border-slate-200/60 overflow-hidden mt-8">
            <div className="bg-slate-50 p-5 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h2 className="font-bold text-lg text-slate-800 flex items-center gap-2">
                  <FileText size={20} className="text-brand-500" />
                  Agenda — CAB #{open.id}
                </h2>
                <p className="text-sm font-medium text-slate-500 mt-1">{fmtDate(open.scheduled_at)}</p>
              </div>
              <StatusBadge status={open.status} />
            </div>
            
            <div className="p-5 space-y-4">
              {open.items.length === 0 && (
                <div className="p-8 text-center border-2 border-dashed border-slate-200 rounded-xl">
                  <FileText className="mx-auto text-slate-300 mb-3" size={32} />
                  <p className="text-sm font-medium text-slate-600">Empty agenda.</p>
                  <p className="text-xs text-slate-400 mt-1">Submitted major changes will appear here automatically.</p>
                </div>
              )}
              {open.items.map((it) => (
                <div key={it.id} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm hover:shadow-md transition-shadow">
                  {it.change ? (
                    <>
                      <div className="flex flex-wrap items-start justify-between gap-4 mb-3">
                        <div className="flex items-center gap-3">
                          <ScoreBadge score={it.change.risk_score} />
                          <div>
                            <Link to={`/changes/${it.change.id}`} className="font-bold text-base text-slate-800 hover:text-brand-600 hover:underline flex items-center gap-1.5">
                              #{it.change.id} {it.change.title}
                            </Link>
                            <div className="text-xs font-medium text-slate-500 mt-1 flex items-center gap-2">
                              <span className="uppercase tracking-wide">{it.change.risk_type}</span>
                              <span className="text-slate-300">•</span>
                              <span className="flex items-center gap-1">
                                {it.change.systems.map((s) => s.name).join(', ')}
                              </span>
                            </div>
                          </div>
                        </div>
                        
                        <div className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide border ${
                          it.decision === 'approved' ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 
                          it.decision === 'rejected' ? 'bg-red-50 text-red-700 border-red-200' : 
                          it.decision === 'deferred' ? 'bg-amber-50 text-amber-700 border-amber-200' : 
                          'bg-slate-50 text-slate-600 border-slate-200'
                        }`}>
                          {it.decision === 'approved' && <CheckCircle2 size={12} />}
                          {it.decision === 'rejected' && <XCircle size={12} />}
                          {it.decision === 'deferred' && <Clock size={12} />}
                          {it.decision === 'pending' && <MoreHorizontal size={12} />}
                          {it.decision}
                        </div>
                      </div>
                      
                      {it.change.factors && it.change.factors.length > 0 && (
                        <div className="bg-slate-50 rounded-lg p-3 text-xs text-slate-700 mb-4 border border-slate-100 flex items-start gap-2">
                          <TrendingUp size={14} className="text-slate-400 shrink-0 mt-0.5" />
                          <div>
                            <span className="font-semibold text-slate-900 mr-2">Top risk drivers:</span>
                            {it.change.factors
                              .slice()
                              .sort((a, b) => b.points - a.points)
                              .slice(0, 2)
                              .map((f) => `${f.points > 0 ? '+' : ''}${f.points} ${f.label}`)
                              .join(' • ')}
                          </div>
                        </div>
                      )}
                      
                      {it.decision === 'pending' && it.change.status === 'submitted' && (
                        <div className="flex flex-wrap gap-3 pt-3 border-t border-slate-100">
                          <button className="btn btn-approve flex-1 sm:flex-none flex items-center justify-center gap-2" onClick={() => decide(it.id, 'approved')}>
                            <CheckCircle2 size={16} /> Approve
                          </button>
                          <button className="btn btn-reject flex-1 sm:flex-none flex items-center justify-center gap-2" onClick={() => decide(it.id, 'rejected')}>
                            <XCircle size={16} /> Reject
                          </button>
                          <button className="btn btn-ghost flex-1 sm:flex-none flex items-center justify-center gap-2" onClick={() => decide(it.id, 'deferred')}>
                            <Clock size={16} /> Defer
                          </button>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="flex items-center gap-3 text-slate-500 p-2">
                      <AlertTriangle size={18} />
                      <span className="text-sm font-medium">Change #{it.change_id} (missing)</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="lg:col-span-4 lg:sticky lg:top-6 space-y-6 min-w-0">
        <div className="card p-6 shadow-sm border-slate-200/60 bg-white">
          <h2 className="font-bold text-lg flex items-center gap-2 text-slate-800 pb-3 border-b border-slate-100 mb-4">
            <Plus size={18} className="text-brand-500" /> Schedule a meeting
          </h2>
          <div className="space-y-4">
            <div>
              <label className="text-xs font-bold tracking-wide text-slate-500 uppercase flex items-center gap-1.5 mb-1.5">
                <Calendar size={12} /> Date & Time
              </label>
              <input type="datetime-local" className="input w-full" value={newWhen} onChange={(e) => setNewWhen(e.target.value)} />
            </div>
            
            <div>
              <label className="text-xs font-bold tracking-wide text-slate-500 uppercase flex items-center gap-1.5 mb-1.5">
                <FileText size={12} /> Notes
              </label>
              <input className="input w-full" placeholder="Optional description..." value={newNotes} onChange={(e) => setNewNotes(e.target.value)} />
            </div>
            
            <button className="btn btn-primary w-full mt-2 shadow-sm shadow-brand-500/20 group" disabled={!newWhen} onClick={createMeeting}>
              <CheckCircle2 size={16} className="mr-1 opacity-70 group-hover:opacity-100" />
              Create CAB meeting
            </button>
            
            <div className="bg-slate-50 rounded-lg p-3 flex items-start gap-2 border border-slate-100 mt-4">
              <Info size={16} className="text-brand-500 shrink-0 mt-0.5" />
              <p className="text-xs font-medium text-slate-600 leading-relaxed">
                Submitted high-risk changes automatically attach to the next scheduled meeting.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
