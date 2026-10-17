import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, fmtDate, type ChangeT, type WindowSuggestion } from '../api'
import { BlastRadiusGraph, RiskWhy, ScoreBadge, StatusBadge, TypeBadge } from '../components/Components'
import { useBoot } from '../App'
import { FileText, Shield, AlertTriangle, CheckCircle2, XCircle, Clock, Users, GitBranch, Sparkles, ChevronRight, ExternalLink, MessageSquare, ArrowLeft, Calendar, User, LayoutDashboard, Activity } from 'lucide-react'
import clsx from 'clsx'

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

  if (err) return <div className="p-8 text-red-600 max-w-7xl mx-auto flex items-center gap-2"><AlertTriangle className="w-5 h-5" />{err}</div>
  
  if (!change) {
    return (
      <div className="p-8 space-y-6 max-w-7xl mx-auto animate-pulse">
        <div className="flex gap-4 items-center">
          <div className="w-8 h-8 bg-slate-200 rounded-full" />
          <div className="w-64 h-8 bg-slate-200 rounded" />
        </div>
        <div className="grid xl:grid-cols-2 gap-6">
          <div className="space-y-6">
            <div className="h-64 bg-slate-100 rounded-xl" />
            <div className="h-96 bg-slate-100 rounded-xl" />
          </div>
          <div className="space-y-6">
            <div className="h-48 bg-slate-100 rounded-xl" />
            <div className="h-80 bg-slate-100 rounded-xl" />
          </div>
        </div>
      </div>
    )
  }

  async function act(fn: () => Promise<unknown>, okMsg: string, needsConfirm = false) {
    if (needsConfirm && !window.confirm(`Are you sure you want to perform this action?`)) {
      return
    }
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
    <div className="p-4 md:p-8 space-y-8 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
        <div>
          <Link to="/changes" className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 hover:text-slate-800 transition-colors">
            <ArrowLeft className="w-4 h-4" /> Back to Changes
          </Link>
          <h1 className="mt-4 text-3xl font-bold tracking-tight text-slate-900 flex items-center gap-3">
            <span className="text-slate-400">#{change.id}</span>
            <span className="break-words">{change.title}</span>
          </h1>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <StatusBadge status={change.status} />
            <ScoreBadge score={change.risk_score} />
            <TypeBadge type={change.risk_type} />
          </div>
        </div>
        
        <div className="flex flex-wrap gap-2">
          {change.transitions?.map((t) => {
            const isDanger = t === 'rejected' || t === 'cancelled' || t === 'failed';
            const isSuccess = t === 'completed';
            const Icon = isDanger ? XCircle : isSuccess ? CheckCircle2 : ChevronRight;
            
            return (
              <button
                key={t}
                className={clsx(
                  "btn flex items-center gap-2", 
                  isDanger ? 'btn-danger' : isSuccess ? 'btn-success' : 'btn-primary'
                )}
                onClick={() => act(
                  () => api(`/api/changes/${change.id}/status`, { method: 'POST', body: JSON.stringify({ status: t }) }), 
                  `Status → ${t}`,
                  isDanger
                )}
              >
                <Icon className="w-4 h-4" />
                {t === 'implementing' ? 'Start implementation' : t === 'completed' ? 'Mark completed' : t === 'failed' ? 'Mark failed' : t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            )
          })}
        </div>
      </div>

      {msg && <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-4 text-sm text-emerald-800 flex items-center gap-2"><CheckCircle2 className="w-5 h-5 text-emerald-500" />{msg}</div>}
      {err && <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-sm text-red-800 flex items-center gap-2"><AlertTriangle className="w-5 h-5 text-red-500" />{err}</div>}

      <div className="grid lg:grid-cols-2 gap-8 items-start">
        <div className="space-y-8">
          
          {/* Overview Section */}
          <section className="card p-6 shadow-sm border-slate-200">
            <h2 className="section-title flex items-center gap-2 mb-6">
              <LayoutDashboard className="w-5 h-5 text-slate-400" /> Overview
            </h2>
            
            <div className="space-y-6">
              {change.description && (
                <div>
                  <div className="eyebrow mb-2">Description</div>
                  <div className="text-slate-700 text-sm whitespace-pre-wrap leading-relaxed">{change.description}</div>
                </div>
              )}
              
              <div className="grid sm:grid-cols-2 gap-6">
                <div>
                  <div className="eyebrow mb-2 flex items-center gap-1.5"><Calendar className="w-4 h-4" /> Schedule</div>
                  <div className="text-sm font-medium text-slate-700">
                    {fmtDate(change.window_start)}
                    <br />
                    <span className="text-slate-400">to</span> {fmtDate(change.window_end)}
                  </div>
                </div>
                <div>
                  <div className="eyebrow mb-2 flex items-center gap-1.5"><User className="w-4 h-4" /> Owner</div>
                  <div className="text-sm font-medium text-slate-700">{change.owner?.name ?? '—'}</div>
                </div>
              </div>

              <div>
                <div className="eyebrow mb-2 flex items-center gap-1.5"><Activity className="w-4 h-4" /> Systems Affected</div>
                {change.systems && change.systems.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {change.systems.map(s => (
                      <span key={s.id} className="pill bg-slate-100 text-slate-700 border-slate-200">
                        {s.name}
                      </span>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-slate-500 italic">No systems specified</div>
                )}
              </div>
            </div>
          </section>

          {/* Risk Assessment Section */}
          <section className="card p-6 shadow-sm border-slate-200">
            <h2 className="section-title flex items-center gap-2 mb-2">
              <Shield className="w-5 h-5 text-slate-400" /> Risk Assessment
            </h2>
            <p className="text-sm text-slate-500 mb-6">Detailed breakdown of the {change.risk_score} risk score.</p>
            
            {change.collisions && change.collisions.length > 0 && (
              <div className="mb-6 rounded-lg bg-amber-50 border border-amber-200 p-4">
                <div className="font-semibold text-amber-900 text-sm flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4" /> Collision Warning
                </div>
                <div className="mt-1 text-sm text-amber-800">
                  {change.collisions.length} overlapping change(s) detected.
                </div>
                <ul className="mt-3 text-sm text-amber-800 space-y-2">
                  {change.collisions.map((c) => (
                    <li key={c.change_id} className="flex flex-col sm:flex-row sm:items-center gap-2 bg-white/50 p-2 rounded border border-amber-100">
                      <Link to={`/changes/${c.change_id}`} className="font-medium hover:underline flex items-center gap-1">
                        #{c.change_id} {c.title} <ExternalLink className="w-3 h-3" />
                      </Link>
                      <span className="hidden sm:inline text-amber-300">•</span>
                      <span className="text-xs uppercase font-semibold">{c.status}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {change.freeze_overlaps && change.freeze_overlaps.length > 0 && (
              <div className="mb-6 rounded-lg bg-rose-50 border border-rose-200 p-4">
                 <div className="font-semibold text-rose-900 text-sm flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4" /> Freeze Period Overlap
                </div>
                <div className="mt-1 text-sm text-rose-800">
                  Overlaps with: {change.freeze_overlaps.map((f) => f.name).join(', ')}
                </div>
              </div>
            )}

            <RiskWhy factors={change.factors ?? []} />
          </section>

          {/* Plans Section */}
          <section className="card p-6 shadow-sm border-slate-200">
            <h2 className="section-title flex items-center gap-2 mb-6">
              <FileText className="w-5 h-5 text-slate-400" /> Execution Plans
            </h2>
            <div className="space-y-6">
              <PlanBlock label="Rollback Plan" value={change.rollback_plan} icon={<GitBranch className="w-4 h-4" />} />
              <PlanBlock label="Test Plan" value={change.test_plan} icon={<CheckCircle2 className="w-4 h-4" />} />
              <PlanBlock label="Communications Plan" value={change.comms_plan} icon={<MessageSquare className="w-4 h-4" />} />
            </div>
            
            <AiDrafts changeId={change.id} change={change} onDone={() => { load(); refresh() }} />
          </section>

        </div>

        <div className="space-y-8">
          
          {/* Approvals Section */}
          <section className="card p-6 shadow-sm border-slate-200">
            <h2 className="section-title flex items-center gap-2 mb-2">
              <Users className="w-5 h-5 text-slate-400" /> Approvals
            </h2>
            
            {change.status === 'submitted' ? (
              <>
                {change.approvals && change.approvals.length > 0 ? (
                  <div className="mt-4 space-y-3">
                    {change.approvals.map((a) => (
                      <div key={a.id} className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50/50 p-3 text-sm">
                        <span className="font-medium text-slate-700 flex items-center gap-2">
                          <div className="w-6 h-6 rounded-full bg-slate-200 flex items-center justify-center text-xs font-bold text-slate-600">
                            {a.approver?.name?.[0] ?? '?'}
                          </div>
                          {a.approver?.name}
                        </span>
                        <span className={clsx(
                          "font-semibold flex items-center gap-1.5",
                          a.decision === 'approved' ? 'text-emerald-600' : 
                          a.decision === 'rejected' ? 'text-red-600' : 'text-slate-400'
                        )}>
                          {a.decision === 'approved' && <CheckCircle2 className="w-4 h-4" />}
                          {a.decision === 'rejected' && <XCircle className="w-4 h-4" />}
                          {a.decision === 'pending' && <Clock className="w-4 h-4" />}
                          <span className="capitalize">{a.decision}</span>
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="mt-4 text-sm text-slate-500 italic p-4 border border-dashed border-slate-200 rounded-lg text-center">
                    No approvals required.
                  </div>
                )}
                
                <div className="mt-4 text-xs text-slate-500 flex items-start gap-2 bg-slate-50 p-3 rounded-lg">
                  <MessageSquare className="w-4 h-4 shrink-0 text-slate-400" />
                  <p>Approvers received this in their <Link to="/approvals" className="font-medium text-brand-600 hover:underline">inbox</Link>. Any single approval (with no rejection) resolves it.</p>
                </div>
              </>
            ) : (
              <div className="mt-4 text-sm text-slate-500 italic p-6 border border-dashed border-slate-200 rounded-lg text-center">
                Approvals are not active for this status.
              </div>
            )}

            {change.status === 'submitted' && pendingMine.length > 0 && (
              <div className="mt-6 pt-6 border-t border-slate-100">
                <h3 className="text-sm font-semibold text-slate-800 mb-3">Your decision is required</h3>
                <div className="flex flex-wrap gap-3">
                  <button className="btn btn-approve flex items-center gap-2" onClick={() => act(() => api(`/api/changes/${change.id}/approvals`, { method: 'POST', body: JSON.stringify({ decision: 'approved' }) }), 'Approved')}>
                    <CheckCircle2 className="w-4 h-4" /> Approve Change
                  </button>
                  <button className="btn btn-reject flex items-center gap-2" onClick={() => act(() => api(`/api/changes/${change.id}/approvals`, { method: 'POST', body: JSON.stringify({ decision: 'rejected' }) }), 'Rejected', true)}>
                    <XCircle className="w-4 h-4" /> Reject
                  </button>
                </div>
              </div>
            )}
          </section>

          {/* Blast Radius Section */}
          <section className="card p-6 shadow-sm border-slate-200">
            <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
              <h2 className="section-title flex items-center gap-2 mb-0">
                <Activity className="w-5 h-5 text-slate-400" /> Blast Radius
              </h2>
              {suggestions.length > 0 && (
                <button className="text-xs font-semibold text-brand-600 hover:text-brand-700 bg-brand-50 px-3 py-1.5 rounded-full transition-colors flex items-center gap-1.5" onClick={() => setShowSuggestions((v) => !v)}>
                  <Sparkles className="w-3.5 h-3.5" />
                  {showSuggestions ? 'Hide suggestions' : 'Suggest safer windows'}
                </button>
              )}
            </div>
            
            <div className="border border-slate-100 rounded-xl overflow-hidden bg-slate-50">
              <BlastRadiusGraph systems={boot.systems} edges={boot.edges} highlightedIds={highlighted} height={340} />
            </div>
            
            {showSuggestions && (
              <div className="mt-4 rounded-xl border border-brand-200 bg-brand-50 p-4 space-y-3">
                <div className="flex items-center gap-2 text-sm font-semibold text-brand-800 mb-2">
                  <Calendar className="w-4 h-4" /> AI Suggested Windows
                </div>
                {suggestions.map((s) => (
                  <div key={s.start} className="text-sm bg-white p-3 rounded-lg shadow-sm border border-brand-100 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                    <span className="font-semibold text-slate-800">
                      {new Date(s.start).toLocaleString(undefined, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                    </span>
                    <span className="text-xs text-slate-500 bg-slate-50 px-2 py-1 rounded">{s.why}</span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {(change.status === 'completed' || change.status === 'failed') && !change.post_change_result && (
            <section className="card p-6 shadow-sm border-brand-200 bg-brand-50/30">
              <h2 className="section-title flex items-center gap-2 mb-2">
                <CheckCircle2 className="w-5 h-5 text-brand-500" /> Post-change check
              </h2>
              <p className="text-sm text-slate-600 mb-4">Did it work? This feeds the failure-rate dashboard and future risk scores.</p>
              <textarea className="input w-full bg-white" rows={3} placeholder="What happened? Add any post-mortem notes here." value={notes} onChange={(e) => setNotes(e.target.value)} />
              <div className="mt-4 flex flex-wrap gap-3">
                {(['success', 'partial', 'failed'] as const).map((r) => {
                  const isSuccess = r === 'success';
                  const isFailed = r === 'failed';
                  return (
                    <button
                      key={r}
                      className={clsx(
                        "btn capitalize flex items-center gap-2", 
                        isSuccess ? 'btn-success' : isFailed ? 'btn-danger' : 'btn-ghost bg-white border-slate-300'
                      )}
                      onClick={() => act(() => api(`/api/changes/${change.id}/post-change`, { method: 'POST', body: JSON.stringify({ result: r, notes }) }), 'Outcome recorded', isFailed)}
                    >
                      {r}
                    </button>
                  )
                })}
              </div>
            </section>
          )}

          {/* Audit Trail Section */}
          <section className="card p-6 shadow-sm border-slate-200">
            <h2 className="section-title flex items-center gap-2 mb-2">
              <Clock className="w-5 h-5 text-slate-400" /> Audit Trail
            </h2>
            <p className="text-xs text-slate-500 mb-6">Append-only log. Every action, actor, and timestamp.</p>
            
            {change.audit && change.audit.length > 0 ? (
              <div className="relative pl-4 border-l-2 border-slate-100 space-y-6">
                {change.audit.map((e) => (
                  <div key={e.id} className="relative">
                    <div className="absolute -left-[21px] top-1 w-2.5 h-2.5 rounded-full bg-slate-300 ring-4 ring-white" />
                    <div className="text-xs font-mono text-slate-400 mb-1">{new Date(e.created_at).toLocaleString()}</div>
                    <div className="text-sm text-slate-700">
                      <span className="font-semibold text-slate-900">{e.actor}</span>
                      <span className="mx-2 text-slate-300">•</span>
                      <span className="capitalize">{e.action}</span>
                      {e.detail && <span className="text-slate-500"> — {e.detail}</span>}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-sm text-slate-500 italic text-center p-4">No audit events yet.</div>
            )}
          </section>

        </div>
      </div>
    </div>
  )
}

function PlanBlock({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div>
      <div className="eyebrow mb-2 flex items-center gap-1.5">
        {icon}
        {label}
      </div>
      {value ? (
        <pre className="whitespace-pre-wrap rounded-lg bg-slate-50/50 border border-slate-200 p-4 text-sm text-slate-700 font-sans leading-relaxed">{value}</pre>
      ) : (
        <div className="text-sm text-slate-400 italic p-4 border border-dashed border-slate-200 rounded-lg bg-slate-50/30">Not specified</div>
      )}
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
    <div className="mt-8 rounded-xl border border-brand-200 bg-gradient-to-br from-brand-50 to-white p-5 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-bold text-brand-900 flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-brand-600" /> AI Assistant
        </span>
        {engine && <span className="text-[10px] uppercase font-bold tracking-wider text-brand-500 bg-brand-100 px-2 py-0.5 rounded-full">{engine}</span>}
      </div>
      <p className="text-sm text-slate-600 mb-4">Let AI draft these plans based on similar successful changes. You can review and edit before applying.</p>
      
      {!shown && (
        <button className="btn btn-primary flex items-center gap-2 shadow-sm" disabled={busy} onClick={generate}>
          {busy ? <Clock className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
          {busy ? 'Drafting plans...' : 'Generate drafts'}
        </button>
      )}

      {shown && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <button className="text-sm text-brand-600 hover:text-brand-800 font-medium flex items-center gap-1.5" disabled={busy} onClick={generate}>
              {busy ? <Clock className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
              {busy ? 'Regenerating...' : 'Regenerate drafts'}
            </button>
          </div>
          
          <div className="space-y-4">
            {([
              ['rollback', 'Rollback draft', shown.rollback],
              ['test', 'Test draft', shown.test],
              ['comms', 'Comms draft', shown.comms],
            ] as const).map(([key, label, value]) => (
              <div key={key} className="bg-white p-4 rounded-lg border border-slate-200 shadow-sm">
                <div className="text-xs font-semibold text-slate-700 uppercase tracking-wider mb-2 flex justify-between">
                  {label}
                  <span className="text-slate-400 font-normal lowercase tracking-normal">editable</span>
                </div>
                <textarea
                  className="input w-full font-mono text-sm border-0 bg-slate-50 p-3 focus:ring-1 focus:ring-brand-500"
                  rows={4}
                  value={value}
                  onChange={(e) => setEdited({ ...shown, [key]: e.target.value })}
                />
              </div>
            ))}
          </div>
          
          <div className="pt-2">
            <button
              className="btn btn-primary w-full flex items-center justify-center gap-2 shadow-sm"
              onClick={async () => {
                await api(`/api/changes/${changeId}/apply-drafts`, {
                  method: 'POST',
                  body: JSON.stringify({ rollback_plan: shown.rollback, test_plan: shown.test, comms_plan: shown.comms }),
                })
                onDone()
              }}
            >
              <CheckCircle2 className="w-4 h-4" /> Review & apply all drafts
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

