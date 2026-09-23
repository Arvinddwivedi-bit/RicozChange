import { Loading } from '../App'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fmtDate, type ChangeT, type WindowSuggestion } from '../api'
import { BlastRadiusGraph, RiskWhy, ScoreBadge, StatusBadge, TypeBadge } from '../components/Components'
import { useBoot } from '../App'

export default function ChangeDetail() {
  const { id } = useParams()
  const { boot, refresh } = useBoot()
  const [change, setChange] = useState<ChangeT | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [suggestions, setSuggestions] = useState<WindowSuggestion[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)

  const load = useCallback(() => {
    api<ChangeT>(`/api/changes/${id}`).then(setChange).catch((e) => setErr(String(e)))
  }, [id])

  useEffect(load, [load])

  useEffect(() => {
    if (change?.systems.length) {
      api<WindowSuggestion[]>(`/api/suggest-windows?system_keys=${change.systems.map((s) => s.key).join(',')}`)
        .then(setSuggestions)
        .catch(() => {})
    }
  }, [change?.systems])

  const highlighted = useMemo(() => (change ? change.systems.map((s) => s.id) : []), [change])

  if (err) return <div className="p-8 text-red-600">{err}</div>
  if (!change) return <Loading />

  async function act(fn: () => Promise<unknown>, okMsg: string) {
    setErr(null)
    setMsg(null)
    try {
      await fn()
      setMsg(okMsg)
      load()
      refresh()
    } catch (e) {
      setErr(String(e))
    }
  }

  const pendingMine = (change.approvals ?? []).filter((a) => a.decision === 'pending')

  return (
    <div className="p-8 space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-3">
            <Link to="/changes" className="text-sm text-slate-400 hover:text-slate-600">← Changes</Link>
          </div>
          <h1 className="mt-1 text-2xl font-extrabold tracking-tight flex items-center gap-3">
            #{change.id} {change.title}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <ScoreBadge score={change.risk_score} />
            <StatusBadge status={change.status} />
            <TypeBadge type={change.risk_type} />
            <span className="text-sm text-slate-500">
              {fmtDate(change.window_start)} → {fmtDate(change.window_end)} · owner {change.owner?.name ?? '—'}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {change.transitions?.map((t) => (
            <button
              key={t}
              className={`btn ${t === 'rejected' || t === 'cancelled' || t === 'failed' ? 'btn-danger' : t === 'completed' ? 'btn-success' : 'btn-ghost'}`}
              onClick={() => act(() => api(`/api/changes/${change.id}/status`, { method: 'POST', body: JSON.stringify({ status: t }) }), `Status → ${t}`)}
            >
              {t === 'implementing' ? 'Start implementing' : t === 'completed' ? 'Mark completed' : t === 'failed' ? 'Mark failed' : t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {msg && <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3 text-sm text-emerald-800">{msg}</div>}
      {err && <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">{err}</div>}

      {change.collisions && change.collisions.length > 0 && (
        <div className="rounded-xl bg-amber-50 border border-amber-300 p-4">
          <div className="font-bold text-amber-900 text-sm">Collision detector — {change.collisions.length} overlapping change(s)</div>
          <ul className="mt-1 text-sm text-amber-800 list-disc list-inside">
            {change.collisions.map((c) => (
              <li key={c.change_id}>
                <Link to={`/changes/${c.change_id}`} className="font-semibold underline">#{c.change_id} {c.title}</Link>{' '}
                ({c.status}) · shared: {c.shared_systems.map((s) => s.name).join(', ')}
              </li>
            ))}
          </ul>
        </div>
      )}

      {change.freeze_overlaps && change.freeze_overlaps.length > 0 && (
        <div className="rounded-xl bg-rose-50 border border-rose-300 p-4 text-sm text-rose-800">
          🧊 Freeze period overlap: {change.freeze_overlaps.map((f) => f.name).join(', ')}
        </div>
      )}

      <div className="grid xl:grid-cols-2 gap-6 items-start">
        <div className="space-y-6">
          <section className="card p-5">
            <h2 className="font-bold">Why this score</h2>
            <p className="text-xs text-slate-500 mb-2">Every point, explained. No black box.</p>
            <RiskWhy factors={change.factors ?? []} />
          </section>

          <section className="card p-5">
            <h2 className="font-bold">Plans</h2>
            <PlanBlock label="Rollback plan" value={change.rollback_plan} />
            <PlanBlock label="Test plan" value={change.test_plan} />
            <PlanBlock label="Comms plan" value={change.comms_plan} />
            <AiDrafts changeId={change.id} change={change} onDone={() => { load(); refresh() }} />
          </section>

          {(change.status === 'completed' || change.status === 'failed') && !change.post_change_result && (
            <section className="card p-5 border-brand-300">
              <h2 className="font-bold">Post-change check</h2>
              <p className="text-sm text-slate-500 mb-2">Did it work? This feeds the failure-rate dashboard and future risk scores.</p>
              <textarea className="input" rows={2} placeholder="What happened?" value={notes} onChange={(e) => setNotes(e.target.value)} />
              <div className="mt-2 flex gap-2">
                {(['success', 'partial', 'failed'] as const).map((r) => (
                  <button
                    key={r}
                    className={`btn ${r === 'success' ? 'btn-success' : r === 'failed' ? 'btn-danger' : 'btn-ghost'}`}
                    onClick={() => act(() => api(`/api/changes/${change.id}/post-change`, { method: 'POST', body: JSON.stringify({ result: r, notes }) }), 'Outcome recorded')}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </section>
          )}

          <section className="card p-5">
            <h2 className="font-bold">Audit trail</h2>
            <p className="text-xs text-slate-500 mb-2">Append-only. Every action, who did it, when.</p>
            <ol className="space-y-1.5">
              {(change.audit ?? []).map((e) => (
                <li key={e.id} className="text-sm flex gap-2">
                  <span className="text-slate-400 font-mono text-xs whitespace-nowrap">{new Date(e.created_at).toLocaleString()}</span>
                  <span><span className="font-semibold">{e.actor}</span> · {e.action}{e.detail ? ` — ${e.detail}` : ''}</span>
                </li>
              ))}
            </ol>
          </section>
        </div>

        <div className="space-y-6">
          {change.status === 'submitted' && (
            <section className="card p-5 border-sky-200">
              <h2 className="font-bold">Approvals</h2>
              <div className="mt-2 space-y-2">
                {(change.approvals ?? []).map((a) => (
                  <div key={a.id} className="flex items-center justify-between rounded-lg border border-slate-100 p-2.5 text-sm">
                    <span>{a.approver?.name}</span>
                    <span className={`font-semibold ${a.decision === 'approved' ? 'text-emerald-600' : a.decision === 'rejected' ? 'text-red-600' : 'text-slate-400'}`}>
                      {a.decision}
                    </span>
                  </div>
                ))}
              </div>
              <div className="mt-3 text-xs text-slate-500">
                Approvers also got this in the <Link to="/slack" className="underline">Slack demo</Link>. Any single approval (with no rejection) resolves it.
              </div>
            </section>
          )}

          {change.status === 'submitted' && pendingMine.length > 0 && (
            <section className="card p-5">
              <h2 className="font-bold">Your decision</h2>
              <div className="mt-2 flex gap-2">
                <button className="btn btn-success" onClick={() => act(() => api(`/api/changes/${change.id}/approvals`, { method: 'POST', body: JSON.stringify({ decision: 'approved' }) }), 'Approved')}>Approve</button>
                <button className="btn btn-danger" onClick={() => act(() => api(`/api/changes/${change.id}/approvals`, { method: 'POST', body: JSON.stringify({ decision: 'rejected' }) }), 'Rejected')}>Reject</button>
              </div>
            </section>
          )}

          <section>
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-bold">Blast radius</h2>
              {suggestions.length > 0 && (
                <button className="text-xs font-semibold text-brand-600 underline" onClick={() => setShowSuggestions((v) => !v)}>
                  {showSuggestions ? 'hide' : 'suggest safer windows'}
                </button>
              )}
            </div>
            <BlastRadiusGraph systems={boot.systems} edges={boot.edges} highlightedIds={highlighted} height={340} />
            {showSuggestions && (
              <div className="card mt-3 p-4 space-y-2">
                {suggestions.map((s) => (
                  <div key={s.start} className="text-sm">
                    <span className="font-semibold">{new Date(s.start).toLocaleString(undefined, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
                    <span className="ml-2 text-xs text-slate-500">{s.why}</span>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

function PlanBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-3">
      <div className="text-xs font-semibold text-slate-600">{label}</div>
      <pre className="mt-1 whitespace-pre-wrap rounded-lg bg-slate-50 border border-slate-100 p-3 text-sm">{value || '—'}</pre>
    </div>
  )
}

function AiDrafts({ changeId, change, onDone }: { changeId: number; change: ChangeT; onDone: () => void }) {
  const [busy, setBusy] = useState(false)
  const [engine, setEngine] = useState<string | null>(null)
  const [edited, setEdited] = useState<{ rollback: string; test: string; comms: string } | null>(null)

  async function generate() {
    setBusy(true)
    try {
      const res = await api<{ engine: string; drafts: { rollback_plan: string; test_plan: string; comms_plan: string } }>(
        `/api/changes/${changeId}/ai-draft`,
        { method: 'POST' },
      )
      setEngine(res.engine)
      setEdited({ rollback: res.drafts.rollback_plan, test: res.drafts.test_plan, comms: res.drafts.comms_plan })
    } finally {
      setBusy(false)
    }
  }

  const hasDrafts = !!(change.ai_rollback_draft || change.ai_test_draft || change.ai_comms_draft)
  const shown = edited ?? (hasDrafts ? {
    rollback: change.ai_rollback_draft ?? '',
    test: change.ai_test_draft ?? '',
    comms: change.ai_comms_draft ?? '',
  } : null)

  return (
    <div className="mt-4 rounded-lg border border-brand-100 bg-brand-50/40 p-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-bold text-brand-800">AI drafting</span>
        {engine && <span className="text-[10px] uppercase text-brand-500">engine: {engine}</span>}
      </div>
      <p className="text-xs text-brand-700/80 mt-1">Drafts only — nothing is applied until a human reviews and approves.</p>
      <button className="btn btn-ghost mt-2" disabled={busy} onClick={generate}>
        {busy ? 'Drafting…' : hasDrafts ? 'Re-generate drafts' : 'Generate rollback / test / comms drafts'}
      </button>

      {shown && (
        <div className="mt-3 space-y-3">
          {([
            ['rollback', 'Rollback draft', shown.rollback],
            ['test', 'Test draft', shown.test],
            ['comms', 'Comms draft', shown.comms],
          ] as const).map(([key, label, value]) => (
            <div key={key}>
              <div className="text-xs font-semibold text-slate-600">{label} (editable)</div>
              <textarea
                className="input mt-1 font-mono text-xs"
                rows={5}
                value={value}
                onChange={(e) => setEdited({ ...shown, [key]: e.target.value })}
              />
            </div>
          ))}
          <button
            className="btn btn-primary"
            onClick={async () => {
              await api(`/api/changes/${changeId}/apply-drafts`, {
                method: 'POST',
                body: JSON.stringify({ rollback_plan: shown.rollback, test_plan: shown.test, comms_plan: shown.comms }),
              })
              onDone()
            }}
          >
            Review & apply all three
          </button>
        </div>
      )}
    </div>
  )
}
