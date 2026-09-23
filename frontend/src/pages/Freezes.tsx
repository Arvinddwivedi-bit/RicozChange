import { Loading } from '../App'
import { useCallback, useEffect, useState } from 'react'
import { api, fmtDate, type FreezeT } from '../api'

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

  return (
    <div className="p-8 grid xl:grid-cols-3 gap-6 items-start">
      <div className="xl:col-span-2 space-y-5 min-w-0">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Freeze windows</h1>
          <p className="text-sm text-slate-500">
            Periods where changes are blocked. Overlapping a freeze adds +25 to the risk score — the simulator and collision
            detector both respect these.
          </p>
        </div>
        <div className="card divide-y divide-slate-100">
          {freezes.length === 0 && <div className="p-6 text-sm text-slate-500">No freezes defined.</div>}
          {freezes.map((f) => (
            <div key={f.id} className="p-4 min-w-0">
              <div className="font-semibold truncate">{f.name}</div>
              <div className="text-sm text-slate-600">{fmtDate(f.starts_at)} → {fmtDate(f.ends_at)}</div>
              {f.reason && <div className="text-xs text-slate-500 mt-1">{f.reason}</div>}
            </div>
          ))}
        </div>
      </div>

      <div className="card p-5 space-y-3">
        <h2 className="font-bold">New freeze</h2>
        {err && <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-xs text-red-700">{err}</div>}
        <input className="input" placeholder="Name (e.g. Black Friday freeze)" value={name} onChange={(e) => setName(e.target.value)} />
        <input className="input" placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
        <label className="text-xs font-semibold text-slate-600">Starts</label>
        <input type="datetime-local" className="input" value={starts} onChange={(e) => setStarts(e.target.value)} />
        <label className="text-xs font-semibold text-slate-600">Ends</label>
        <input type="datetime-local" className="input" value={ends} onChange={(e) => setEnds(e.target.value)} />
        <button className="btn btn-primary w-full" disabled={!name || !starts || !ends} onClick={create}>
          Create freeze
        </button>
      </div>
    </div>
  )
}
