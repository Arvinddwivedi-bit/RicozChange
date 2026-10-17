import { Loading } from '../App'
import { useCallback, useEffect, useState } from 'react'
import { api, fmtDate, type FreezeT } from '../api'
import { Snowflake, Plus, Calendar, Clock, AlertTriangle, CheckCircle2, ShieldBan, Info, ArrowRight } from 'lucide-react'

export default function Freezes() {
  const [freezes, setFreezes] = useState<FreezeT[] | null>(null)
  const [name, setName] = useState('')
  const [reason, setReason] = useState('')
  const [starts, setStarts] = useState('')
  const [ends, setEnds] = useState('')
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(() => {
    api<FreezeT[]>('/api/freezes').then(setFreezes)
  }, [])

  useEffect(load, [load])

  async function create() {
    setErr(null)
    try {
      await api('/api/freezes', {
        method: 'POST',
        body: JSON.stringify({ name, reason, starts_at: starts, ends_at: ends }),
      })
      setName('')
      setReason('')
      setStarts('')
      setEnds('')
      load()
    } catch (e) {
      setErr(String(e))
    }
  }

  if (!freezes) return <Loading />
  
  const now = new Date()
  
  const getStatus = (f: FreezeT) => {
    const s = new Date(f.starts_at)
    const e = new Date(f.ends_at)
    if (now > e) return 'expired'
    if (now >= s && now <= e) return 'active'
    return 'upcoming'
  }

  return (
    <div className="p-8 max-w-7xl mx-auto grid lg:grid-cols-3 gap-8 items-start">
      <div className="lg:col-span-2 space-y-6 min-w-0">
        <div>
          <div className="eyebrow flex items-center gap-2 text-brand-600">
            <ShieldBan size={16} />
            Protect Peak Business
          </div>
          <h1 className="page-title flex items-center gap-2 mt-2">
            <Snowflake className="text-sky-500" />
            Freeze Windows
          </h1>
          <p className="mt-2 text-sm text-slate-500 max-w-2xl leading-relaxed">
            Periods where changes are blocked. Overlapping a freeze adds +25 to the risk score — the simulator and collision
            detector both respect these constraints.
          </p>
        </div>
        
        <div className="space-y-4">
          {freezes.length === 0 && (
            <div className="card p-12 text-center text-slate-500 border-dashed border-2">
              <Snowflake className="mx-auto text-slate-300 mb-3" size={32} />
              <h3 className="text-sm font-semibold text-slate-700 mb-1">No active freezes</h3>
              <p className="text-xs">Create a new freeze window to block changes during critical periods.</p>
            </div>
          )}
          {freezes.map((f) => {
            const status = getStatus(f);
            return (
              <div key={f.id} className={`card p-5 min-w-0 flex flex-col sm:flex-row sm:items-start gap-4 transition-all ${status === 'active' ? 'ring-2 ring-brand-500/20 border-brand-200 bg-brand-50/10' : ''}`}>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-2">
                    <h3 className="font-bold text-slate-800 text-lg truncate">{f.name}</h3>
                    {status === 'active' && <span className="inline-flex items-center gap-1 rounded-full bg-brand-100 px-2 py-0.5 text-[10px] font-bold text-brand-700 uppercase tracking-wider"><span className="w-1.5 h-1.5 rounded-full bg-brand-500 animate-pulse"/>Active</span>}
                    {status === 'upcoming' && <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-700 uppercase tracking-wider">Upcoming</span>}
                    {status === 'expired' && <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500 uppercase tracking-wider">Expired</span>}
                  </div>
                  
                  <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm font-medium text-slate-600 mb-3">
                    <div className="flex items-center gap-1.5">
                      <Calendar size={14} className="text-slate-400" />
                      {fmtDate(f.starts_at)} <ArrowRight size={12} className="text-slate-300" /> {fmtDate(f.ends_at)}
                    </div>
                  </div>
                  
                  {f.reason && (
                    <div className="flex items-start gap-2 bg-slate-50 rounded-lg p-3 border border-slate-100 text-sm text-slate-700">
                      <Info size={16} className="text-slate-400 shrink-0 mt-0.5" />
                      <span className="leading-relaxed">{f.reason}</span>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div className="card p-6 space-y-5 lg:sticky lg:top-6 border-slate-200/60 shadow-sm bg-white">
        <h2 className="font-bold text-lg flex items-center gap-2 text-slate-800 pb-2 border-b border-slate-100">
          <Plus size={18} className="text-brand-500" /> New freeze window
        </h2>
        
        {err && (
          <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700 flex items-start gap-2">
            <AlertTriangle size={16} className="shrink-0 mt-0.5" />
            <span>{err}</span>
          </div>
        )}
        
        <div className="space-y-4">
          <div>
            <label className="text-xs font-bold tracking-wide text-slate-500 uppercase block mb-1.5">Name</label>
            <input className="input w-full" placeholder="e.g. Black Friday freeze" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          
          <div>
            <label className="text-xs font-bold tracking-wide text-slate-500 uppercase block mb-1.5">Reason</label>
            <textarea className="input w-full min-h-[80px] resize-y" placeholder="Why is this freeze necessary?" value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-bold tracking-wide text-slate-500 uppercase flex items-center gap-1.5 mb-1.5">
                <Clock size={12} /> Starts
              </label>
              <input type="datetime-local" className="input w-full text-sm" value={starts} onChange={(e) => setStarts(e.target.value)} />
            </div>
            <div>
              <label className="text-xs font-bold tracking-wide text-slate-500 uppercase flex items-center gap-1.5 mb-1.5">
                <Clock size={12} /> Ends
              </label>
              <input type="datetime-local" className="input w-full text-sm" value={ends} onChange={(e) => setEnds(e.target.value)} />
            </div>
          </div>
          
          <button className="btn btn-primary w-full mt-2 shadow-sm shadow-brand-500/20 group" disabled={!name || !starts || !ends} onClick={create}>
            <CheckCircle2 size={16} className="mr-1 opacity-70 group-hover:opacity-100" />
            Create freeze
          </button>
        </div>
      </div>
    </div>
  )
}
