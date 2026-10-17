import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, scoreColor, type SimResult } from '../api'
import { BlastRadiusGraph, RiskWhy, useDebounced } from '../components/Components'
import { useBoot } from '../App'
import { FlaskConical, Play, RotateCcw, AlertTriangle, CheckCircle2, Zap, Calendar, Activity, ArrowRight, ShieldAlert } from 'lucide-react'

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
    <div className="p-8 max-w-7xl mx-auto grid lg:grid-cols-12 gap-8 items-start">
      <div className="lg:col-span-5 xl:col-span-4 space-y-6 min-w-0">
        <div>
          <div className="eyebrow flex items-center gap-2 text-brand-600">
            <FlaskConical size={16} />
            Score Before You File
          </div>
          <h1 className="page-title flex items-center gap-2 mt-2">
            Change Simulator
          </h1>
          <p className="mt-2 text-sm text-slate-500 leading-relaxed">
            Drag the sliders. Watch the score, collisions and blast radius react in real time. Find the safe slot <em>before</em> you file.
          </p>
        </div>

        <div className="card p-6 space-y-6 shadow-sm border-slate-200/60">
          <div>
            <label className="text-xs font-bold tracking-wide text-slate-500 uppercase flex items-center gap-1.5 mb-2.5">
              <Activity size={14} /> Risk class
            </label>
            <div className="flex flex-wrap gap-2">
              {TYPES.map((t) => (
                <button
                  key={t}
                  onClick={() => setRiskType(t)}
                  className={`rounded-full px-4 py-1.5 text-xs font-semibold capitalize transition-all ${riskType === t ? 'bg-slate-800 text-white shadow-md shadow-slate-800/20 ring-2 ring-slate-800 ring-offset-1' : 'bg-white border border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50'}`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs font-bold tracking-wide text-slate-500 uppercase flex items-center gap-1.5 mb-2.5">
              <Calendar size={14} /> Window start
            </label>
            <div className="bg-slate-50 rounded-lg p-3 border border-slate-100">
              <div className="text-sm font-semibold text-slate-800 mb-3 flex items-center justify-between">
                <span>{new Date(start).toLocaleString(undefined, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
                <span className="text-xs text-brand-600 font-bold bg-brand-50 px-2 py-0.5 rounded-full">Interactive</span>
              </div>
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
                className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-brand-600"
              />
            </div>
          </div>

          <div>
            <label className="text-xs font-bold tracking-wide text-slate-500 uppercase flex items-center justify-between mb-2.5">
              <span className="flex items-center gap-1.5"><Calendar size={14} /> Duration</span>
              <span className="text-brand-600 bg-brand-50 px-2 py-0.5 rounded-full">{durationH}h</span>
            </label>
            <input type="range" min={0.5} max={8} step={0.5} value={durationH} onChange={(e) => setDurationH(Number(e.target.value))} className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-brand-600" />
          </div>

          <div>
            <label className="text-xs font-bold tracking-wide text-slate-500 uppercase flex items-center gap-1.5 mb-2.5">
              <Zap size={14} /> Affected Systems
            </label>
            <div className="flex flex-wrap gap-2">
              {boot.systems.map((s) => {
                const on = systemKeys.includes(s.key)
                return (
                  <button
                    key={s.key}
                    onClick={() => setSystemKeys(on ? systemKeys.filter((k) => k !== s.key) : [...systemKeys, s.key])}
                    className={`rounded-full px-3 py-1.5 text-xs font-medium transition-all ${on ? 'border-brand-200 bg-brand-50 text-brand-700 shadow-sm border' : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-50'}`}
                  >
                    {s.name}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="pt-2 border-t border-slate-100">
            <label className="flex items-center gap-3 p-3 rounded-lg border border-slate-200 bg-white cursor-pointer hover:bg-slate-50 transition-colors group">
              <div className="relative flex items-center justify-center">
                <input type="checkbox" className="peer sr-only" checked={rollback} onChange={(e) => setRollback(e.target.checked)} />
                <div className="w-5 h-5 rounded border-2 border-slate-300 peer-checked:border-brand-600 peer-checked:bg-brand-600 transition-colors" />
                <CheckCircle2 size={14} className="absolute text-white opacity-0 peer-checked:opacity-100 transition-opacity" />
              </div>
              <div className="flex-1">
                <div className="text-sm font-semibold text-slate-700 group-hover:text-slate-900">Rollback plan in place</div>
                <div className="text-[11px] text-slate-500">Automatically decreases risk score if provided.</div>
              </div>
            </label>
          </div>
        </div>
      </div>

      <div className="lg:col-span-7 xl:col-span-8 space-y-6 min-w-0 lg:sticky lg:top-6">
        <div className="card p-6 border-slate-200/60 shadow-md">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="font-bold text-lg flex items-center gap-2 text-slate-800">
                <Play size={20} className="text-emerald-500" fill="currentColor" /> Simulation Results
              </h2>
              <p className="text-xs text-slate-500 mt-1">Live prediction based on current parameters</p>
            </div>
            {sim && (
              <div className="flex flex-col items-end">
                <span className={`rounded-lg px-4 py-1.5 text-3xl font-extrabold shadow-sm ${scoreColor(sim.score)}`}>{sim.score}</span>
                <span className="text-[10px] uppercase font-bold text-slate-400 mt-1 tracking-wider">Risk Score</span>
              </div>
            )}
          </div>

          <div className="min-h-[140px]">
            {sim ? (
              <div className="space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-300">
                <div className="bg-slate-50 rounded-xl p-4 border border-slate-100">
                  <h3 className="text-xs font-bold uppercase text-slate-500 tracking-wider mb-3">Score Factors</h3>
                  <RiskWhy factors={sim.factors} compact />
                </div>
                
                {(sim.collisions.length > 0 || sim.freeze_overlaps.length > 0) && (
                  <div className="grid sm:grid-cols-2 gap-4">
                    {sim.collisions.length > 0 && (
                      <div className="rounded-xl bg-amber-50/80 border border-amber-200/60 p-4">
                        <div className="flex items-center gap-2 text-amber-800 font-bold mb-2">
                          <RotateCcw size={16} /> Schedule Collisions
                        </div>
                        <ul className="space-y-1.5">
                          {sim.collisions.map((c) => (
                            <li key={c.change_id} className="text-xs text-amber-700/90 font-medium flex items-center gap-1.5">
                              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                              <Link to={`/changes/${c.change_id}`} className="hover:underline">#{c.change_id}</Link> “{c.title}”
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {sim.freeze_overlaps.length > 0 && (
                      <div className="rounded-xl bg-rose-50/80 border border-rose-200/60 p-4">
                        <div className="flex items-center gap-2 text-rose-700 font-bold mb-2">
                          <ShieldAlert size={16} /> Freeze Overlap
                        </div>
                        <ul className="space-y-1.5">
                          {sim.freeze_overlaps.map((f, i) => (
                            <li key={i} className="text-xs text-rose-600/90 font-medium flex items-center gap-1.5">
                              <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                              {f.name}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
                
                <div className="pt-4 flex justify-end">
                  <Link to="/create" state={{ simKey }} className="btn btn-primary shadow-md shadow-brand-500/20 group">
                    Create Change from Simulation
                    <ArrowRight size={16} className="group-hover:translate-x-1 transition-transform" />
                  </Link>
                </div>
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-center p-8 bg-slate-50/50 rounded-xl border border-dashed border-slate-200">
                <AlertTriangle size={32} className="text-slate-300 mb-3" />
                <p className="text-sm font-medium text-slate-600">Pick at least one system to run simulation.</p>
                <p className="text-xs text-slate-400 mt-1">The simulator requires an affected system to calculate blast radius.</p>
              </div>
            )}
          </div>
        </div>

        <div className="card p-6 border-slate-200/60 shadow-sm">
          <h2 className="font-bold mb-4 flex items-center gap-2 text-slate-800">
            <Zap size={18} className="text-amber-500" />
            Blast Radius Topology
          </h2>
          <div className="bg-slate-900 rounded-xl overflow-hidden border border-slate-800 relative">
            <div className="absolute inset-0 bg-grid-slate-800/[0.2] bg-[length:16px_16px]" />
            <div className="relative">
              <BlastRadiusGraph systems={boot.systems} edges={boot.edges} highlightedIds={highlighted} height={360} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
