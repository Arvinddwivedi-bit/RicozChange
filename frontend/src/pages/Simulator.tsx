import { useEffect, useMemo, useState } from 'react'
import { api, scoreColor, type SimResult } from '../api'
import { BlastRadiusGraph, RiskWhy, useDebounced } from '../components/Components'
import { useBoot } from '../App'

const TYPES = ['standard', 'normal', 'major', 'emergency']

function localIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function Simulator() {
  const { boot } = useBoot()
  const [riskType, setRiskType] = useState('major')
  const [systemKeys, setSystemKeys] = useState<string[]>(['payments-db', 'payments-api'])
  const [rollback, setRollback] = useState(true)
  const [start, setStart] = useState(() => {
    const d = new Date(Date.now() + 24 * 3600 * 1000)
    d.setHours(2, 0, 0, 0)
    return localIso(d)
  })
  const [durationH, setDurationH] = useState(3)

  const simKey = JSON.stringify({ riskType, systemKeys, rollback, start, durationH })
  const debounced = useDebounced(simKey, 250)
  const [sim, setSim] = useState<SimResult | null>(null)

  useEffect(() => {
    const args = JSON.parse(debounced)
    if (!args.systemKeys.length) {
      setSim(null)
      return
    }
    const s = new Date(args.start)
    const e = new Date(s.getTime() + args.durationH * 3600 * 1000)
    api<SimResult>('/api/simulate', {
      method: 'POST',
      body: JSON.stringify({
        system_keys: args.systemKeys,
        risk_type: args.riskType,
        window_start: localIso(s),
        window_end: localIso(e),
        rollback_plan_present: args.rollback,
      }),
    }).then(setSim).catch(() => setSim(null))
  }, [debounced])

  const highlighted = useMemo(
    () => boot.systems.filter((s) => systemKeys.includes(s.key)).map((s) => s.id),
    [boot.systems, systemKeys],
  )

  return (
    <div className="p-8 grid xl:grid-cols-2 gap-6 items-start">
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Change Simulator</h1>
          <p className="text-sm text-slate-500">
            Drag the sliders. Watch the score, collisions and blast radius react in real time. Find the safe slot <em>before</em> you file.
          </p>
        </div>

        <div className="card p-5 space-y-5">
          <div>
            <label className="text-xs font-semibold text-slate-600">Risk class</label>
            <div className="mt-1 flex gap-2">
              {TYPES.map((t) => (
                <button
                  key={t}
                  onClick={() => setRiskType(t)}
                  className={`rounded-full px-3 py-1 text-xs font-semibold capitalize ${riskType === t ? 'bg-brand-600 text-white' : 'bg-white border border-slate-200 text-slate-600'}`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-600">Window start — drag me</label>
            <input
              type="range"
              min={0}
              max={24 * 14}
              step={1}
              value={(() => {
                const s = new Date(start)
                const base = new Date(s)
                base.setHours(0, 0, 0, 0)
                return Math.min(24 * 14, Math.round((s.getTime() - base.getTime()) / 3600000) + 24)
              })()}
              onChange={(e) => {
                const hours = Number(e.target.value) - 24
                const s = new Date(Date.now() + 24 * 3600 * 1000)
                s.setHours(0, 0, 0, 0)
                s.setHours(s.getHours() + hours)
                setStart(localIso(s))
              }}
              className="mt-2 w-full accent-brand-600"
            />
            <div className="mt-1 text-sm font-semibold">{new Date(start).toLocaleString(undefined, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</div>
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-600">Duration: {durationH}h</label>
            <input type="range" min={0.5} max={8} step={0.5} value={durationH} onChange={(e) => setDurationH(Number(e.target.value))} className="mt-1 w-full accent-brand-600" />
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-600">Systems</label>
            <div className="mt-1 flex flex-wrap gap-2">
              {boot.systems.map((s) => {
                const on = systemKeys.includes(s.key)
                return (
                  <button
                    key={s.key}
                    onClick={() => setSystemKeys(on ? systemKeys.filter((k) => k !== s.key) : [...systemKeys, s.key])}
                    className={`rounded-full border px-3 py-1 text-xs ${on ? 'border-red-500 bg-red-50 text-red-700 font-semibold' : 'border-slate-200 text-slate-600'}`}
                  >
                    {s.name}
                  </button>
                )
              })}
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={rollback} onChange={(e) => setRollback(e.target.checked)} />
            Rollback plan in place
          </label>
        </div>
      </div>

      <div className="space-y-5 xl:sticky xl:top-6">
        <div className="card p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-bold">Score right now</h2>
            {sim && <span className={`rounded-full px-4 py-1.5 text-2xl font-extrabold ${scoreColor(sim.score)}`}>{sim.score}</span>}
          </div>
          {sim ? (
            <>
              <div className="mt-3"><RiskWhy factors={sim.factors} compact /></div>
              {sim.collisions.length > 0 && (
                <div className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800">
                  Collisions: {sim.collisions.map((c) => `#${c.change_id} “${c.title}”`).join(', ')}
                </div>
              )}
              {sim.freeze_overlaps.length > 0 && (
                <div className="mt-2 rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700">
                  🧊 Freeze: {sim.freeze_overlaps.map((f) => f.name).join(', ')}
                </div>
              )}
            </>
          ) : (
            <p className="text-sm text-slate-500">Pick at least one system.</p>
          )}
        </div>

        <div>
          <h2 className="font-bold mb-2">Blast radius</h2>
          <BlastRadiusGraph systems={boot.systems} edges={boot.edges} highlightedIds={highlighted} height={360} />
        </div>
      </div>
    </div>
  )
}
