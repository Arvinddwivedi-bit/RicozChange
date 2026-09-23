import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, scoreColor, type SimResult, type WindowSuggestion } from '../api'
import { BlastRadiusGraph, RiskWhy, useDebounced } from '../components/Components'
import { useBoot } from '../App'

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
    <div className="p-8 grid xl:grid-cols-2 gap-6 items-start">
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">New change</h1>
          <p className="text-sm text-slate-500">The risk score updates live as you fill this in — that's the point.</p>
        </div>

        <div className="card p-5 space-y-4">
          <div>
            <label className="text-xs font-semibold text-slate-600">Templates (fast-track eligible)</label>
            <div className="mt-1 flex flex-wrap gap-2">
              {boot.templates.map((t) => (
                <button
                  key={t.id}
                  onClick={() => applyTemplate(t.id)}
                  className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                    templateId === t.id ? 'border-brand-600 bg-brand-50 text-brand-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {t.icon} {t.name}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-600">Title</label>
            <input className="input mt-1" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="What is changing?" />
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-600">Description</label>
            <textarea className="input mt-1" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Why, how, and what could go wrong" />
          </div>

          <div className="grid sm:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-slate-600">Risk class</label>
              <select className="input mt-1" value={riskType} onChange={(e) => setRiskType(e.target.value)}>
                {TYPES.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-semibold text-slate-600">Duration / window</label>
              <div className="mt-1 grid grid-cols-2 gap-2">
                <input type="datetime-local" className="input" value={windowStart} onChange={(e) => setWindowStart(e.target.value)} />
                <input type="datetime-local" className="input" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} />
              </div>
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-600">Affected systems</label>
            <div className="mt-1 flex flex-wrap gap-2">
              {boot.systems.map((s) => {
                const on = systemKeys.includes(s.key)
                return (
                  <button
                    key={s.key}
                    onClick={() => setSystemKeys(on ? systemKeys.filter((k) => k !== s.key) : [...systemKeys, s.key])}
                    className={`rounded-full border px-3 py-1 text-xs font-medium ${
                      on ? 'border-red-500 bg-red-50 text-red-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'
                    }`}
                    title={`${s.environment} · ${s.criticality}`}
                  >
                    {s.name}
                  </button>
                )
              })}
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-slate-600">Rollback plan</label>
            <textarea className="input mt-1" rows={3} value={rollback} onChange={(e) => setRollback(e.target.value)} placeholder="How do we undo this? (drafts can be AI-generated later)" />
          </div>

          {error && <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{error}</div>}

          <div className="flex gap-2">
            <button className="btn btn-ghost" disabled={submitting || title.length < 3} onClick={() => submit(true)}>
              Save as draft
            </button>
            <button className="btn btn-primary" disabled={submitting || title.length < 3 || !systemKeys.length} onClick={() => submit(false)}>
              Submit for approval
            </button>
          </div>
        </div>
      </div>

      <div className="space-y-5 xl:sticky xl:top-6">
        <div className="card p-5">
          <div className="flex items-center justify-between">
            <h2 className="font-bold">Live risk preview</h2>
            {sim && (
              <span className={`rounded-full px-3 py-1 text-lg font-extrabold ${scoreColor(sim.score)}`}>{sim.score}</span>
            )}
          </div>
          {sim ? (
            <div className="mt-2">
              <RiskWhy factors={sim.factors} compact />
              {sim.collisions.length > 0 && (
                <div className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800">
                  ⚠ {sim.collisions.length} overlapping change(s):{' '}
                  {sim.collisions.map((c) => `#${c.change_id} “${c.title}”`).join(', ')}
                </div>
              )}
            </div>
          ) : (
            <p className="mt-2 text-sm text-slate-500">Pick systems and a window to see the score.</p>
          )}
        </div>

        {suggestions.length > 0 && (
          <div className="card p-5">
            <h2 className="font-bold mb-2">Safer windows</h2>
            <div className="space-y-2">
              {suggestions.map((s) => (
                <button
                  key={s.start}
                  className="w-full text-left rounded-lg border border-slate-200 p-3 text-sm hover:border-brand-300 hover:bg-brand-50/50"
                  onClick={() => {
                    const start = new Date(s.start)
                    const end = new Date(s.end)
                    setWindowStart(localIso(start))
                    setWindowEnd(localIso(end))
                  }}
                >
                  <div className="font-semibold">
                    {new Date(s.start).toLocaleString(undefined, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                    {s.weekend && <span className="ml-2 rounded bg-emerald-100 px-1.5 py-0.5 text-xs text-emerald-700">weekend</span>}
                  </div>
                  <div className="text-xs text-slate-500">{s.why}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        <div>
          <h2 className="font-bold mb-2">Blast radius preview</h2>
          <BlastRadiusGraph
            systems={boot.systems}
            edges={boot.edges}
            highlightedIds={highlighted}
            height={300}
          />
        </div>
      </div>
    </div>
  )
}
