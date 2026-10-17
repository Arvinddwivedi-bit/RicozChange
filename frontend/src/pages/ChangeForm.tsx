import { useEffect, useMemo, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { api, scoreColor, type SimResult, type WindowSuggestion } from '../api'
import { BlastRadiusGraph, RiskWhy, useDebounced } from '../components/Components'
import { useBoot } from '../App'
import { FileText, Calendar, Shield, ChevronLeft, Save, Sparkles, AlertCircle, CheckCircle2, Info, Activity, Clock, Box, Zap } from 'lucide-react'
import clsx from 'clsx'

const TYPES = [
  { value: 'standard', label: 'Standard (pre-approved template)' },
  { value: 'normal', label: 'Normal' },
  { value: 'major', label: 'Major' },
  { value: 'emergency', label: 'Emergency' },
]

function localIso(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function ChangeForm() {
  const { boot, refresh } = useBoot()
  const navigate = useNavigate()

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [riskType, setRiskType] = useState('normal')
  const [systemKeys, setSystemKeys] = useState<string[]>([])
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')
  const [rollback, setRollback] = useState('')
  const [templateId, setTemplateId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const simKey = JSON.stringify({ title, riskType, systemKeys, windowStart, windowEnd, rollback: rollback.length > 0, templateId })
  const debouncedKey = useDebounced(simKey, 350)
  const [sim, setSim] = useState<SimResult | null>(null)
  const [suggestions, setSuggestions] = useState<WindowSuggestion[]>([])

  useEffect(() => {
    const args = JSON.parse(debouncedKey) as {
      title: string; riskType: string; systemKeys: string[]; windowStart: string; windowEnd: string; rollback: boolean
    }
    if (!args.systemKeys.length || !args.windowStart || !args.windowEnd) {
      setSim(null)
      return
    }
    api<SimResult>('/api/simulate', {
      method: 'POST',
      body: JSON.stringify({
        system_keys: args.systemKeys,
        risk_type: args.riskType,
        window_start: args.windowStart,
        window_end: args.windowEnd,
        rollback_plan_present: args.rollback,
      }),
    }).then(setSim).catch(() => setSim(null))
  }, [debouncedKey])

  useEffect(() => {
    if (!systemKeys.length) {
      setSuggestions([])
      return
    }
    api<WindowSuggestion[]>(`/api/suggest-windows?system_keys=${systemKeys.join(',')}`).then(setSuggestions).catch(() => {})
  }, [systemKeys])

  const highlighted = useMemo(
    () => boot.systems.filter((s) => systemKeys.includes(s.key)).map((s) => s.id),
    [boot.systems, systemKeys],
  )

  function applyTemplate(id: number) {
    const t = boot.templates.find((x) => x.id === id)
    setTemplateId(id)
    if (!t) return
    if (!title) setTitle(`${t.name}`)
    setDescription(t.description)
    setRollback(t.rollback_plan)
    const start = new Date(Date.now() + 24 * 3600 * 1000)
    start.setMinutes(0, 0, 0)
    setWindowStart(localIso(start))
    setWindowEnd(localIso(new Date(start.getTime() + t.default_duration_minutes * 60 * 1000)))
  }

  async function submit(asDraft: boolean) {
    setError(null)
    setSubmitting(true)
    try {
      const created = await api<{ id: number }>('/api/changes', {
        method: 'POST',
        body: JSON.stringify({
          title,
          description,
          risk_type: riskType,
          system_keys: systemKeys,
          window_start: windowStart || null,
          window_end: windowEnd || null,
          rollback_plan: rollback,
          template_id: templateId,
        }),
      })
      if (!asDraft) {
        await api(`/api/changes/${created.id}/submit`, { method: 'POST' })
      }
      refresh()
      navigate(`/changes/${created.id}`)
    } catch (e) {
      setError(String(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <Link to="/changes" className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 hover:text-slate-800 transition-colors">
          <ChevronLeft className="w-4 h-4" /> Back
        </Link>
        <div className="mt-4 flex flex-col md:flex-row md:items-end justify-between gap-4">
          <div>
            <div className="eyebrow flex items-center gap-1.5"><Zap className="w-4 h-4" /> File With Confidence</div>
            <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">New Change Request</h1>
            <p className="mt-2 text-sm text-slate-500 flex items-center gap-1.5">
              <Info className="w-4 h-4" /> The risk score updates live as you fill this in — that's the point.
            </p>
          </div>
          <div className="flex flex-wrap gap-3">
            <button className="btn btn-ghost flex items-center gap-2 border-slate-300" disabled={submitting || title.length < 3} onClick={() => submit(true)}>
              <Save className="w-4 h-4" /> Save as draft
            </button>
            <button className="btn btn-primary flex items-center gap-2 shadow-sm" disabled={submitting || title.length < 3 || !systemKeys.length} onClick={() => submit(false)}>
              <CheckCircle2 className="w-4 h-4" /> Submit for approval
            </button>
          </div>
        </div>
      </div>

      <div className="grid xl:grid-cols-[1fr_400px] gap-8 items-start">
        <div className="space-y-6">
          
          {/* Templates Section */}
          <div className="card p-6 shadow-sm border-slate-200 bg-slate-50/50">
            <label className="text-sm font-semibold text-slate-700 flex items-center gap-2 mb-3">
              <Sparkles className="w-4 h-4 text-brand-500" /> Templates (fast-track eligible)
            </label>
            <div className="flex flex-wrap gap-2">
              {boot.templates.map((t) => (
                <button
                  key={t.id}
                  onClick={() => applyTemplate(t.id)}
                  className={clsx(
                    "rounded-full border px-4 py-1.5 text-sm font-medium transition-colors flex items-center gap-2",
                    templateId === t.id 
                      ? 'border-brand-600 bg-brand-50 text-brand-700 shadow-sm' 
                      : 'border-slate-200 text-slate-600 hover:bg-white hover:border-slate-300 hover:shadow-sm bg-white/50'
                  )}
                >
                  <span className="text-lg leading-none">{t.icon}</span> {t.name}
                </button>
              ))}
            </div>
          </div>

          <div className="card p-6 shadow-sm border-slate-200 space-y-8">
            
            {/* Basic Info Section */}
            <section className="space-y-5">
              <h3 className="text-sm font-bold text-slate-800 uppercase tracking-wider flex items-center gap-2 pb-2 border-b border-slate-100">
                <FileText className="w-4 h-4 text-slate-400" /> Basic Info
              </h3>
              
              <div className="space-y-1.5">
                <label htmlFor="field-title" className="text-sm font-semibold text-slate-700">Title <span className="text-red-500">*</span></label>
                <input id="field-title" className="input w-full bg-slate-50 focus:bg-white transition-colors" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What is changing?" />
              </div>

              <div className="space-y-1.5">
                <label htmlFor="field-desc" className="text-sm font-semibold text-slate-700">Description</label>
                <textarea id="field-desc" className="input w-full bg-slate-50 focus:bg-white transition-colors" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Why, how, and what could go wrong" />
              </div>

              <div className="space-y-1.5 w-full sm:w-1/2">
                <label htmlFor="field-type" className="text-sm font-semibold text-slate-700">Risk class</label>
                <select id="field-type" className="input w-full bg-slate-50 focus:bg-white transition-colors cursor-pointer" value={riskType} onChange={(e) => setRiskType(e.target.value)}>
                  {TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
            </section>

            {/* Systems Section */}
            <section className="space-y-5">
              <h3 className="text-sm font-bold text-slate-800 uppercase tracking-wider flex items-center gap-2 pb-2 border-b border-slate-100">
                <Box className="w-4 h-4 text-slate-400" /> Systems & Impact
              </h3>
              
              <div className="space-y-2">
                <label className="text-sm font-semibold text-slate-700">Affected systems <span className="text-red-500">*</span></label>
                <p className="text-xs text-slate-500 mb-3">Select all systems that might be impacted by this change.</p>
                <div className="flex flex-wrap gap-2.5">
                  {boot.systems.map((s) => {
                    const on = systemKeys.includes(s.key)
                    return (
                      <button
                        key={s.key}
                        type="button"
                        onClick={() => setSystemKeys(on ? systemKeys.filter((k) => k !== s.key) : [...systemKeys, s.key])}
                        className={clsx(
                          "rounded-full border px-4 py-1.5 text-sm font-medium transition-all flex items-center gap-1.5",
                          on 
                            ? 'border-brand-500 bg-brand-50 text-brand-700 shadow-sm ring-1 ring-brand-500/20' 
                            : 'border-slate-200 text-slate-600 hover:bg-slate-50 hover:border-slate-300'
                        )}
                        title={`${s.environment} · ${s.criticality}`}
                      >
                        {on && <CheckCircle2 className="w-3.5 h-3.5" />}
                        {s.name}
                      </button>
                    )
                  })}
                </div>
              </div>
            </section>

            {/* Schedule Section */}
            <section className="space-y-5">
              <h3 className="text-sm font-bold text-slate-800 uppercase tracking-wider flex items-center gap-2 pb-2 border-b border-slate-100">
                <Calendar className="w-4 h-4 text-slate-400" /> Schedule
              </h3>
              
              <div className="space-y-2">
                <label className="text-sm font-semibold text-slate-700">Duration / Window <span className="text-red-500">*</span></label>
                <div className="grid sm:grid-cols-2 gap-4">
                  <div className="space-y-1">
                    <span className="text-xs text-slate-500 font-medium">Start</span>
                    <input type="datetime-local" className="input w-full bg-slate-50 focus:bg-white" value={windowStart} onChange={(e) => setWindowStart(e.target.value)} />
                  </div>
                  <div className="space-y-1">
                    <span className="text-xs text-slate-500 font-medium">End</span>
                    <input type="datetime-local" className="input w-full bg-slate-50 focus:bg-white" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} />
                  </div>
                </div>
              </div>
            </section>

            {/* Plans Section */}
            <section className="space-y-5">
              <h3 className="text-sm font-bold text-slate-800 uppercase tracking-wider flex items-center gap-2 pb-2 border-b border-slate-100">
                <Shield className="w-4 h-4 text-slate-400" /> Execution Plans
              </h3>
              
              <div className="space-y-1.5">
                <label htmlFor="field-rollback" className="text-sm font-semibold text-slate-700">Rollback plan</label>
                <textarea id="field-rollback" className="input w-full bg-slate-50 focus:bg-white transition-colors" rows={3} value={rollback} onChange={(e) => setRollback(e.target.value)} placeholder="How do we undo this? (drafts can be AI-generated later)" />
              </div>
            </section>

            {error && (
              <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-sm text-red-800 flex items-center gap-2">
                <AlertCircle className="w-5 h-5 text-red-500 shrink-0" />
                {error}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-6 xl:sticky xl:top-6">
          {/* Live Risk Preview Card */}
          <div className="card p-0 shadow-sm border-slate-200 overflow-hidden flex flex-col">
            <div className="bg-slate-50 p-5 border-b border-slate-100 flex items-center justify-between">
              <h2 className="font-bold text-slate-800 flex items-center gap-2">
                <Activity className="w-5 h-5 text-brand-500" /> Live Risk Preview
              </h2>
              {sim && (
                <div className="flex flex-col items-end">
                  <span className={clsx("rounded-full px-3 py-1 text-xl font-extrabold shadow-sm bg-white border border-slate-100", scoreColor(sim.score))}>
                    {sim.score}
                  </span>
                </div>
              )}
            </div>
            
            <div className="p-5">
              {sim ? (
                <div className="space-y-4">
                  <RiskWhy factors={sim.factors} compact />
                  
                  {sim.collisions.length > 0 && (
                    <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 flex gap-2">
                      <AlertCircle className="w-4 h-4 text-amber-500 shrink-0 mt-0.5" />
                      <div>
                        <div className="text-sm font-semibold text-amber-900">{sim.collisions.length} overlapping change(s)</div>
                        <div className="text-xs text-amber-800 mt-1">
                          {sim.collisions.map((c) => `#${c.change_id} “${c.title}”`).join(', ')}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="py-8 flex flex-col items-center justify-center text-center space-y-3">
                  <div className="w-12 h-12 rounded-full bg-slate-50 flex items-center justify-center">
                    <Shield className="w-6 h-6 text-slate-300" />
                  </div>
                  <p className="text-sm text-slate-500 max-w-[200px]">Pick systems and a window to see the real-time risk score.</p>
                </div>
              )}
            </div>
          </div>

          {suggestions.length > 0 && (
            <div className="card p-5 shadow-sm border-brand-200 bg-brand-50/30">
              <h2 className="font-bold text-brand-900 mb-3 flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-brand-500" /> Safer windows suggested
              </h2>
              <div className="space-y-2.5">
                {suggestions.map((s) => (
                  <button
                    key={s.start}
                    type="button"
                    className="w-full text-left rounded-lg border border-brand-100 bg-white p-3 text-sm hover:border-brand-300 hover:shadow-sm transition-all focus:ring-2 focus:ring-brand-500/20"
                    onClick={() => {
                      const start = new Date(s.start)
                      const end = new Date(s.end)
                      setWindowStart(localIso(start))
                      setWindowEnd(localIso(end))
                    }}
                  >
                    <div className="font-semibold text-slate-800 flex items-center justify-between">
                      <span className="flex items-center gap-1.5"><Clock className="w-3.5 h-3.5 text-slate-400" /> {new Date(s.start).toLocaleString(undefined, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
                      {s.weekend && <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-700 uppercase tracking-wider font-bold">weekend</span>}
                    </div>
                    <div className="text-xs text-slate-500 mt-1">{s.why}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="card p-5 shadow-sm border-slate-200">
            <h2 className="font-bold text-slate-800 mb-3 flex items-center gap-2">
              <Activity className="w-4 h-4 text-slate-400" /> Blast radius preview
            </h2>
            <div className="rounded-xl overflow-hidden bg-slate-50 border border-slate-100">
              <BlastRadiusGraph
                systems={boot.systems}
                edges={boot.edges}
                highlightedIds={highlighted}
                height={260}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
