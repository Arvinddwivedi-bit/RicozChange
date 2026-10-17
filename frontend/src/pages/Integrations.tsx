import { useEffect, useState } from 'react'
import { api } from '../api'
import { 
  Plug, MessageSquare, GitBranch, Mail, Calendar, Globe, 
  Settings, ChevronRight, CheckCircle2, XCircle, Send, 
  RefreshCw, Webhook, ShieldCheck, Activity, Hash
} from 'lucide-react'
import clsx from 'clsx'

interface SlackStatus {
  connected: boolean
  install_url?: string
}

interface EmailStatus {
  webhook_url: string
  signature_check: boolean
  mailbox: string
  allowed_domains: string[]
}

interface InboundRow {
  id: number
  message_id: string
  from_addr: string
  subject: string
  status: 'created' | 'rejected' | 'error'
  error_detail: string
  parsed_change_id: number | null
  received_at: string
}

interface GitHubConn {
  id: number
  repo: string
  label: string
  default_system_keys: string[]
  auto_submit: boolean
  has_own_secret: boolean
}

interface GitHubStatus {
  configured: boolean
  webhook_url: string
  global_secret_set: boolean
  connections: GitHubConn[]
}

interface GHDeliveryRow {
  id: number
  delivery_id: string
  event: string
  repo: string
  action: string
  status: 'processed' | 'ignored' | 'duplicate' | 'rejected' | 'error'
  detail: string
  change_id: number | null
  received_at: string
}

interface CalStatus {
  enabled: boolean
  url: string | null
  note: string
}

interface GoogleCalStatus {
  connected: boolean
  client_configured: boolean
  connect_url?: string
  calendar_id?: string
  connected_at?: string
}

interface TeamsStatus {
  connected: boolean
  client_configured: boolean
  setup: string
}

function Toggle({ on }: { on: boolean }) {
  return (
    <span
      className={clsx(
        `inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold border transition-colors`,
        on ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-slate-50 text-slate-500 border-slate-200'
      )}
    >
      {on ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <XCircle className="w-3.5 h-3.5 text-slate-400" />}
      {on ? 'Connected' : 'Not configured'}
    </span>
  )
}

export default function Integrations() {
  const [slack, setSlack] = useState<SlackStatus | null>(null)
  const [authMode, setAuthMode] = useState<string | null>(null)
  const [email, setEmail] = useState<EmailStatus | null>(null)
  const [inbound, setInbound] = useState<InboundRow[]>([])
  const [simFrom, _setSimFrom] = useState('dev@rico.dev')
  const [simSubject, setSimSubject] = useState('')
  const [simBody, setSimBody] = useState('')
  const [simBusy, setSimBusy] = useState(false)
  const [simResult, setSimResult] = useState<{ status: string; reply: string } | null>(null)
  const [simError, setSimError] = useState<string | null>(null)
  const [sweepBusy, setSweepBusy] = useState(false)
  const [_sweepInfo, _setSweepInfo] = useState<{ post_change_prompts: number; digests: number; slack_fallbacks: number } | null>(null)
  const [gh, setGh] = useState<GitHubStatus | null>(null)
  const [ghDeliveries, setGhDeliveries] = useState<GHDeliveryRow[]>([])
  const [ghRepo, setGhRepo] = useState('')
  const [ghSystems, setGhSystems] = useState('staging-web')
  const [ghAutoSubmit, setGhAutoSubmit] = useState(false)
  const [ghBusy, setGhBusy] = useState(false)
  const [ghError, setGhError] = useState<string | null>(null)
  const [sim2Repo, setSim2Repo] = useState('acme/checkout')
  const [sim2Wf, setSim2Wf] = useState('deploy production')
  const [sim2Conclusion, setSim2Conclusion] = useState<'success' | 'failure'>('success')
  const [sim2Login, setSim2Login] = useState('')
  const [sim2Busy, setSim2Busy] = useState(false)
  const [sim2Result, setSim2Result] = useState<{ change_id?: number; status: string; detail?: string } | null>(null)
  const [cal, setCal] = useState<CalStatus | null>(null)
  const [calBusy, setCalBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const [gcal, setGcal] = useState<GoogleCalStatus | null>(null)
  const [gcalBusy, setGcalBusy] = useState(false)
  const [gcalMsg, setGcalMsg] = useState<string | null>(null)
  const [teams, setTeams] = useState<TeamsStatus | null>(null)
  const [teamsBusy, setTeamsBusy] = useState(false)
  const [teamsMsg, setTeamsMsg] = useState<string | null>(null)

  useEffect(() => {
    api<SlackStatus>('/api/integrations/slack/status').then(setSlack).catch(() => setSlack({ connected: false }))
    api<{ auth_mode: string }>('/api/auth/me').then((r) => setAuthMode(r.auth_mode)).catch(() => setAuthMode('unknown'))
    api<EmailStatus>('/api/integrations/email/status').then(setEmail).catch(() => setEmail(null))
    api<{ items: InboundRow[] }>('/api/integrations/email/inbound').then((r) => setInbound(r.items)).catch(() => setInbound([]))
    api<GitHubStatus>('/api/integrations/github/status').then(setGh).catch(() => setGh(null))
    api<{ items: GHDeliveryRow[] }>('/api/integrations/github/deliveries').then((r) => setGhDeliveries(r.items)).catch(() => setGhDeliveries([]))
    api<CalStatus>('/api/integrations/calendar/status').then(setCal).catch(() => setCal(null))
    api<GoogleCalStatus>('/api/integrations/google/status').then(setGcal).catch(() => setGcal(null))
    api<TeamsStatus>('/api/integrations/teams/status').then(setTeams).catch(() => setTeams(null))
  }, [])

  async function runSimulate() {
    setSimBusy(true); setSimError(null); setSimResult(null)
    try {
      const r = await api<{ status: string; reply: string; inbound_id: number }>('/api/integrations/email/simulate', {
        method: 'POST',
        body: JSON.stringify({ from_addr: simFrom, subject: simSubject, body: simBody }),
      })
      setSimResult(r)
      api<{ items: InboundRow[] }>('/api/integrations/email/inbound').then((x) => setInbound(x.items)).catch(() => {})
    } catch (e) {
      setSimError(String(e).replace('Error: ', ''))
    } finally {
      setSimBusy(false)
    }
  }

  async function runSweep() {
    setSweepBusy(true)
    try {
      const r = await api<{ post_change_prompts: number; digests: number; slack_fallbacks: number }>('/api/integrations/email/sweep', { method: 'POST' })
      _setSweepInfo(r)
    } finally {
      setSweepBusy(false)
    }
  }

  const emailMode = email !== null

  async function loadGh() {
    api<GitHubStatus>('/api/integrations/github/status').then(setGh).catch(() => {})
    api<{ items: GHDeliveryRow[] }>('/api/integrations/github/deliveries').then((r) => setGhDeliveries(r.items)).catch(() => {})
  }

  async function connectRepo() {
    setGhBusy(true); setGhError(null)
    try {
      await api('/api/integrations/github/connections', {
        method: 'POST',
        body: JSON.stringify({
          repo: ghRepo.trim(),
          default_system_keys: ghSystems.split(',').map((s) => s.trim()).filter(Boolean),
          auto_submit: ghAutoSubmit,
        }),
      })
      setGhRepo('')
      await loadGh()
    } catch (e) {
      setGhError(String(e).replace('Error: ', ''))
    } finally {
      setGhBusy(false)
    }
  }

  async function removeConn(id: number) {
    await api(`/api/integrations/github/connections/${id}`, { method: 'DELETE' }).catch(() => {})
    await loadGh()
  }

  async function rotateCalendar() {
    setCalBusy(true)
    try {
      const r = await api<CalStatus>('/api/integrations/calendar/rotate', { method: 'POST' })
      setCal(r)
      setCopied(false)
    } finally {
      setCalBusy(false)
    }
  }

  async function copyCalUrl() {
    if (!cal?.url) return
    try {
      await navigator.clipboard.writeText(cal.url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* clipboard unavailable */ }
  }

  async function loadGoogle() {
    api<GoogleCalStatus>('/api/integrations/google/status').then(setGcal).catch(() => {})
  }

  function connectGoogle() {
    if (gcal?.connect_url) window.location.href = gcal.connect_url
  }

  async function disconnectGoogle() {
    setGcalBusy(true); setGcalMsg(null)
    try {
      await api('/api/integrations/google/disconnect', { method: 'POST' })
      await loadGoogle()
    } catch (e) {
      setGcalMsg(String(e).replace('Error: ', ''))
    } finally {
      setGcalBusy(false)
    }
  }

  async function syncGoogleNow() {
    setGcalBusy(true); setGcalMsg(null)
    try {
      const r = await api<{ status: string; synced: number; failed: number }>('/api/integrations/google/sync', { method: 'POST' })
      setGcalMsg(
        r.status === 'skipped'
          ? 'Connect Google Calendar first.'
          : `Synced ${r.synced} item${r.synced === 1 ? '' : 's'}${r.failed ? ` · ${r.failed} failed` : ''}`
      )
    } catch (e) {
      setGcalMsg(String(e).replace('Error: ', ''))
    } finally {
      setGcalBusy(false)
    }
  }

  async function syncTeamsNow() {
    setTeamsBusy(true); setTeamsMsg(null)
    try {
      const r = await api<{ teams_delivered: number; teams_fallbacks: number }>('/api/integrations/teams/sweep', { method: 'POST' })
      setTeamsMsg(`Delivered ${r.teams_delivered} card${r.teams_delivered === 1 ? '' : 's'}${r.teams_fallbacks ? ` · ${r.teams_fallbacks} email fallback${r.teams_fallbacks === 1 ? '' : 's'}` : ''}`)
    } catch (e) {
      setTeamsMsg(String(e).replace('Error: ', ''))
    } finally {
      setTeamsBusy(false)
    }
  }

  async function simulateDeploy() {
    setSim2Busy(true); setSim2Result(null)
    try {
      const r = await api<{ status: string; change_id?: number; detail?: string }>('/api/integrations/github/simulate', {
        method: 'POST',
        body: JSON.stringify({
          repo: sim2Repo.trim(), workflow_name: sim2Wf.trim(), conclusion: sim2Conclusion,
          login: sim2Login.trim(), auto_submit: true, system_keys: ['staging-web'],
        }),
      })
      setSim2Result(r)
      await loadGh()
    } finally {
      setSim2Busy(false)
    }
  }

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-brand-600 mb-2">
            <Plug className="w-5 h-5" />
            <div className="eyebrow !mb-0 !text-brand-600">One Connected Platform</div>
          </div>
          <h1 className="page-title">Integrations</h1>
          <p className="mt-2 text-[14.5px] text-slate-500 max-w-2xl leading-relaxed">
            Live connections that carry RicozChange into your team's daily tools. 
            Configure webhooks, messaging, and authentication.
          </p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        {/* Left Column - Main Integrations */}
        <div className="lg:col-span-8 space-y-6">
          
          {/* GitHub Integration */}
          <div className="card overflow-hidden">
            <div className="p-6 border-b border-slate-100 bg-slate-50/50">
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                <div className="flex items-start gap-4 min-w-0">
                  <div className="w-12 h-12 shrink-0 rounded-xl bg-slate-900 text-white flex items-center justify-center shadow-sm">
                    <GitBranch className="w-6 h-6" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-lg font-bold text-slate-900">GitHub Deploys</div>
                    <p className="text-[13.5px] text-slate-500 mt-1 max-w-xl leading-relaxed">
                      A production deploy on a connected repo <b>becomes</b> a scored, collision-checked change. Point the repo's webhook at
                      <code className="ml-1 text-[11px] bg-slate-100 border border-slate-200 rounded px-1.5 py-0.5">/api/integrations/github/webhook</code> with
                      <code className="ml-1 text-[11px] bg-slate-100 border border-slate-200 rounded px-1.5 py-0.5">GITHUB_WEBHOOK_SECRET</code>.
                    </p>
                  </div>
                </div>
                <div className="shrink-0 pt-1">
                  <Toggle on={Boolean(gh?.configured)} />
                </div>
              </div>
            </div>

            <div className="p-6 grid gap-6">
              {/* Connected Repos */}
              <div>
                <div className="flex items-center gap-2 text-[13px] font-bold text-navy mb-3">
                  <Settings className="w-4 h-4 text-slate-400" />
                  Connected Repositories
                </div>
                <div className="space-y-3">
                  {(gh?.connections ?? []).length === 0 && (
                    <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center text-[13px] text-slate-500 bg-slate-50/50">
                      No repositories connected yet.
                    </div>
                  )}
                  {(gh?.connections ?? []).map((c) => (
                    <div key={c.id} className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 p-3.5 bg-white shadow-sm hover:border-slate-300 transition-colors">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate text-[14px] font-semibold text-navy">{c.repo}</span>
                          {c.auto_submit && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-800">Auto-Submit</span>}
                        </div>
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11.5px] text-slate-500">
                          {c.default_system_keys.map((k) => <span key={k} className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono border border-slate-200">{k}</span>)}
                        </div>
                      </div>
                      <button className="btn btn-ghost !px-3 !py-1.5 text-[12px] text-red-600 hover:bg-red-50" onClick={() => removeConn(c.id)}>Remove</button>
                    </div>
                  ))}
                </div>

                <div className="mt-4 p-4 rounded-xl border border-slate-200 bg-slate-50/50">
                  <div className="grid gap-3 sm:grid-cols-2 mb-3">
                    <input className="input text-[13px] bg-white" placeholder="owner/repo" value={ghRepo} onChange={(e) => setGhRepo(e.target.value)} />
                    <input className="input text-[13px] bg-white" placeholder="systems: staging-web, orders-api" value={ghSystems} onChange={(e) => setGhSystems(e.target.value)} />
                  </div>
                  <label className="flex cursor-pointer select-none items-center gap-2.5 text-[13px] text-slate-600 mb-4">
                    <input type="checkbox" className="w-4 h-4 rounded border-slate-300 text-brand-600 focus:ring-brand-600/20" checked={ghAutoSubmit} onChange={(e) => setGhAutoSubmit(e.target.checked)} />
                    Auto-submit deploys for approval
                  </label>
                  <div className="flex items-center gap-3">
                    <button className="btn btn-primary !py-2 text-[13px] font-medium" disabled={ghBusy || !ghRepo.trim()} onClick={connectRepo}>
                      {ghBusy ? <RefreshCw className="w-4 h-4 animate-spin mr-1.5" /> : null}
                      {ghBusy ? 'Connecting…' : 'Connect Repository'}
                    </button>
                    {ghError && <span className="text-[12px] font-medium text-red-600 flex items-center gap-1"><XCircle className="w-3.5 h-3.5" />{ghError}</span>}
                  </div>
                </div>
              </div>

              {/* Delivery logs */}
              {ghDeliveries.length > 0 && (
                <div className="pt-4 border-t border-slate-100">
                  <div className="flex items-center gap-2 text-[13px] font-bold text-navy mb-3">
                    <Activity className="w-4 h-4 text-slate-400" />
                    Recent Webhook Deliveries
                  </div>
                  <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 overflow-hidden bg-white shadow-sm">
                    {ghDeliveries.slice(0, 5).map((d) => (
                      <div key={d.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-[12.5px] hover:bg-slate-50 transition-colors">
                        <div className="min-w-0">
                          <div className="font-medium text-navy">{d.repo}</div>
                          <div className="mt-0.5 text-slate-500 flex items-center gap-1.5">
                            <span className="font-mono text-[11px] bg-slate-100 px-1 rounded text-slate-600">{d.event}</span>
                            <span>•</span>
                            <span>{d.action}</span>
                            {d.detail && <span>• <span className="truncate">{d.detail}</span></span>}
                          </div>
                        </div>
                        <div className="flex shrink-0 items-center gap-3">
                          <span className={clsx(`pill text-[11px] px-2 py-0.5`, 
                            d.status === 'processed' ? 'pill-green' : 
                            d.status === 'ignored' ? 'pill-neutral' : 
                            d.status === 'duplicate' ? 'pill-blue' : 'pill-red'
                          )}>{d.status}</span>
                          {d.change_id && <a className="font-medium text-brand-700 hover:text-brand-800 hover:underline flex items-center gap-1" href={`/changes/${d.change_id}`}>#{d.change_id} <ChevronRight className="w-3 h-3" /></a>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Email Integration */}
          <div className="card overflow-hidden">
            <div className="p-6 border-b border-slate-100 bg-slate-50/50">
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                <div className="flex items-start gap-4 min-w-0">
                  <div className="w-12 h-12 shrink-0 rounded-xl bg-[#0EA5E9] text-white flex items-center justify-center shadow-sm">
                    <Mail className="w-6 h-6" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-lg font-bold text-slate-900">Email-To-Change</div>
                    <p className="text-[13.5px] text-slate-500 mt-1 max-w-xl leading-relaxed">
                      File a change by emailing the mailbox. Replies always include the risk score and its reasoning.
                    </p>
                  </div>
                </div>
                <div className="shrink-0 pt-1">
                  <Toggle on={emailMode} />
                </div>
              </div>
            </div>

            {emailMode && (
              <div className="p-6">
                <div className="grid gap-4 sm:grid-cols-3 mb-6">
                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-1.5 flex items-center gap-1.5"><Mail className="w-3.5 h-3.5" /> Mailbox</div>
                    <div className="truncate font-semibold text-navy text-[13px]">{email?.mailbox}</div>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-1.5 flex items-center gap-1.5"><Globe className="w-3.5 h-3.5" /> Allowed domains</div>
                    <div className="truncate font-semibold text-navy text-[13px]">{email?.allowed_domains.join(', ')}</div>
                  </div>
                  <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-1.5 flex items-center gap-1.5"><ShieldCheck className="w-3.5 h-3.5" /> Signature</div>
                    <div className="font-semibold text-navy text-[13px]">{email?.signature_check ? 'Active' : 'Off (Demo)'}</div>
                  </div>
                </div>

                {inbound.length > 0 && (
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2 text-[13px] font-bold text-navy">
                        <Activity className="w-4 h-4 text-slate-400" />
                        Recent Inbound
                      </div>
                      <button className="btn btn-ghost !py-1.5 !px-3 text-[12px] flex items-center gap-1.5" disabled={sweepBusy} onClick={runSweep}>
                        <RefreshCw className={clsx("w-3.5 h-3.5", sweepBusy && "animate-spin")} />
                        Sweep
                      </button>
                    </div>
                    <div className="divide-y divide-slate-100 rounded-xl border border-slate-200 overflow-hidden bg-white shadow-sm">
                      {inbound.slice(0, 5).map((r) => (
                        <div key={r.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-[12.5px] hover:bg-slate-50 transition-colors">
                          <div className="min-w-0">
                            <div className="font-medium text-navy truncate">{r.subject || '(no subject)'}</div>
                            <div className="mt-0.5 text-slate-500 text-[11.5px]">{r.from_addr}</div>
                            {r.status === 'rejected' && <div className="mt-1 text-red-600 text-[11.5px] font-medium">{r.error_detail}</div>}
                          </div>
                          <div className="flex shrink-0 items-center gap-3">
                            <span className={clsx(`pill text-[11px] px-2 py-0.5`, 
                              r.status === 'created' ? 'pill-green' : 
                              r.status === 'rejected' ? 'pill-red' : 'pill-amber'
                            )}>{r.status}</span>
                            {r.parsed_change_id && (
                              <a className="font-medium text-brand-700 hover:text-brand-800 hover:underline flex items-center gap-1" href={`/changes/${r.parsed_change_id}`}>#{r.parsed_change_id} <ChevronRight className="w-3 h-3" /></a>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Auth Integration */}
          <div className="card overflow-hidden">
            <div className="p-6">
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                <div className="flex items-start gap-4 min-w-0">
                  <div className="w-12 h-12 shrink-0 rounded-xl bg-brand-600 text-white flex items-center justify-center shadow-sm">
                    <ShieldCheck className="w-6 h-6" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-lg font-bold text-slate-900">Clerk Sign-In</div>
                    <p className="text-[13.5px] text-slate-500 mt-1 max-w-xl leading-relaxed">
                      Real authentication with roles enforced server-side. Admins are auto-provisioned from the <code className="text-[11px] bg-slate-100 border border-slate-200 rounded px-1.5 py-0.5">ADMIN_EMAILS</code> allowlist.
                    </p>
                  </div>
                </div>
                <div className="shrink-0 pt-1 text-right">
                  <Toggle on={authMode === 'clerk'} />
                  <div className="mt-2 text-[11px] font-medium text-slate-400 uppercase tracking-wider">
                    mode: {authMode ?? '…'}
                  </div>
                </div>
              </div>
            </div>
          </div>

        </div>

        {/* Right Column - Sidebar tools */}
        <div className="lg:col-span-4 space-y-6">

          {/* Chat / Approvals */}
          <div className="card p-6">
            <div className="flex items-center gap-2 text-[14px] font-bold text-navy mb-5 border-b border-slate-100 pb-3">
              <MessageSquare className="w-4 h-4 text-brand-600" /> Chat Approvals
            </div>
            
            <div className="space-y-6">
              {/* Slack */}
              <div>
                <div className="flex items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2 font-semibold text-[13.5px] text-slate-800">
                    <Hash className="w-4 h-4 text-slate-400" /> Slack
                  </div>
                  <Toggle on={Boolean(slack?.connected)} />
                </div>
                <p className="text-[12px] text-slate-500 mb-3 leading-relaxed">
                  Approval requests as direct messages. Configure <code className="text-[10px] bg-slate-100 border border-slate-200 rounded px-1">SLACK_CLIENT_ID</code> to install.
                </p>
                {slack?.connected === false && slack?.install_url && (
                  <a href={slack.install_url} className="btn btn-primary w-full justify-center !py-2 text-[13px]">
                    Connect Workspace
                  </a>
                )}
              </div>
              
              <div className="h-px bg-slate-100"></div>

              {/* Teams */}
              <div>
                <div className="flex items-center justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2 font-semibold text-[13.5px] text-slate-800">
                    <MessageSquare className="w-4 h-4 text-[#464EB8]" /> Teams
                  </div>
                  <Toggle on={Boolean(teams?.connected)} />
                </div>
                <p className="text-[12px] text-slate-500 mb-3 leading-relaxed">
                  Approval cards inline. Register an Azure bot and set <code className="text-[10px] bg-slate-100 border border-slate-200 rounded px-1">TEAMS_APP_ID</code>.
                </p>
                <div className="flex flex-col gap-2">
                  {teams?.connected && (
                    <button className="btn btn-ghost w-full justify-center !py-2 text-[12px] border border-slate-200" disabled={teamsBusy} onClick={syncTeamsNow}>
                      {teamsBusy ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1.5" /> : null}
                      {teamsBusy ? 'Syncing…' : 'Sync Deliveries'}
                    </button>
                  )}
                  {teamsMsg && <div className="text-[11.5px] font-medium text-slate-600 bg-slate-50 p-2 rounded border border-slate-100 text-center">{teamsMsg}</div>}
                  {teams?.connected === false && teams?.client_configured === false && (
                    <div className="text-[11px] text-slate-400 bg-slate-50 p-2 rounded border border-slate-100">{teams?.setup}</div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Calendar */}
          <div className="card p-6">
            <div className="flex items-center gap-2 text-[14px] font-bold text-navy mb-5 border-b border-slate-100 pb-3">
              <Calendar className="w-4 h-4 text-brand-600" /> Calendars
            </div>
            
            <div className="space-y-6">
              {/* Writeback */}
              <div>
                <div className="flex items-center justify-between gap-2 mb-2">
                  <div className="font-semibold text-[13.5px] text-slate-800">Google Sync</div>
                  <Toggle on={Boolean(gcal?.connected)} />
                </div>
                <p className="text-[12px] text-slate-500 mb-3 leading-relaxed">
                  {gcal?.connected ? `Syncing to ${gcal.calendar_id ?? 'calendar'}` : 'Write back changes and freezes to Google Calendar.'}
                </p>
                <div className="flex flex-col gap-2">
                  {gcal?.connected ? (
                    <div className="flex gap-2">
                      <button className="btn btn-ghost flex-1 !py-1.5 text-[12px] border border-slate-200" disabled={gcalBusy} onClick={syncGoogleNow}>
                        {gcalBusy ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1.5" /> : null} Sync
                      </button>
                      <button className="btn btn-ghost flex-1 !py-1.5 text-[12px] text-red-600 border border-red-100 hover:bg-red-50" disabled={gcalBusy} onClick={disconnectGoogle}>
                        Disconnect
                      </button>
                    </div>
                  ) : (
                    <button className="btn btn-primary w-full justify-center !py-2 text-[13px]" disabled={gcalBusy || !gcal?.client_configured} onClick={connectGoogle}>
                      Connect Google
                    </button>
                  )}
                  {gcalMsg && <div className="text-[11.5px] font-medium text-slate-600 bg-slate-50 p-2 rounded border border-slate-100 text-center">{gcalMsg}</div>}
                </div>
              </div>

              <div className="h-px bg-slate-100"></div>

              {/* Feed */}
              <div>
                <div className="flex items-center justify-between gap-2 mb-2">
                  <div className="font-semibold text-[13.5px] text-slate-800">iCal Feed</div>
                  <Toggle on={Boolean(cal?.enabled)} />
                </div>
                {cal?.enabled && cal.url && (
                  <div className="mt-2 mb-3">
                    <input readOnly className="input w-full !py-1.5 font-mono text-[11px] text-slate-600 bg-slate-50 shadow-inner" value={cal.url} onFocus={(e) => e.currentTarget.select()} />
                  </div>
                )}
                <div className="flex items-center gap-2">
                  <button className="btn btn-ghost w-full justify-center !py-2 text-[12px] border border-slate-200" disabled={calBusy} onClick={rotateCalendar}>
                    {calBusy ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1.5" /> : null}
                    {cal?.enabled ? 'Rotate URL' : 'Enable Feed'}
                  </button>
                  {cal?.enabled && cal.url && (
                    <button className="btn btn-primary !py-2 px-3 text-[12px]" onClick={copyCalUrl}>
                      {copied ? <CheckCircle2 className="w-4 h-4" /> : 'Copy'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Tools - Simulation */}
          <div className="card p-6 bg-slate-50/50">
            <div className="flex items-center gap-2 text-[14px] font-bold text-navy mb-5 border-b border-slate-200 pb-3">
              <Webhook className="w-4 h-4 text-brand-600" /> Simulators
            </div>
            
            <div className="space-y-4">
              <div>
                <div className="font-semibold text-[13px] text-slate-800 mb-2">Deploy Webhook</div>
                <div className="grid gap-2">
                  <input className="input text-[12px] bg-white" placeholder="owner/repo" value={sim2Repo} onChange={(e) => setSim2Repo(e.target.value)} />
                  <input className="input text-[12px] bg-white" placeholder="workflow name" value={sim2Wf} onChange={(e) => setSim2Wf(e.target.value)} />
                  <div className="grid gap-2 grid-cols-2">
                    <select className="input text-[12px] bg-white" value={sim2Conclusion} onChange={(e) => setSim2Conclusion(e.target.value as 'success' | 'failure')}>
                      <option value="success">Deploy succeeds</option>
                      <option value="failure">Deploy fails</option>
                    </select>
                    <input className="input text-[12px] bg-white" placeholder="deployer GitHub login" value={sim2Login} onChange={(e) => setSim2Login(e.target.value)} />
                  </div>
                  <button className="btn btn-primary w-full justify-center !py-1.5 text-[12px]" disabled={sim2Busy || !sim2Repo.trim()} onClick={simulateDeploy}>
                    {sim2Busy ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <Send className="w-3.5 h-3.5 mr-1.5" />}
                    Simulate Deploy
                  </button>
                </div>
                {sim2Result && (
                  <div className="mt-2 rounded-lg border border-emerald-200 bg-emerald-50 p-2.5 text-[11.5px] text-emerald-800 shadow-sm">
                    {sim2Conclusion} → {sim2Result.change_id ? <a className="font-bold underline" href={`/changes/${sim2Result.change_id}`}>#{sim2Result.change_id}</a> : sim2Result.status}
                  </div>
                )}
              </div>
              
              <div className="h-px bg-slate-200"></div>
              
              <div>
                <div className="font-semibold text-[13px] text-slate-800 mb-2">Inbound Email</div>
                <div className="grid gap-2">
                  <input className="input text-[12px] bg-white" placeholder="Subject" value={simSubject} onChange={(e) => setSimSubject(e.target.value)} />
                  <textarea className="input min-h-[60px] font-mono text-[11px] bg-white" placeholder="Email body..." value={simBody} onChange={(e) => setSimBody(e.target.value)} />
                  <button className="btn btn-primary w-full justify-center !py-1.5 text-[12px]" disabled={simBusy || !simSubject.trim()} onClick={runSimulate}>
                    {simBusy ? <RefreshCw className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <Send className="w-3.5 h-3.5 mr-1.5" />}
                    Simulate Email
                  </button>
                  {simError && <span className="text-[11.5px] font-medium text-red-600 flex items-center gap-1 mt-1"><XCircle className="w-3.5 h-3.5" />{simError}</span>}
                </div>
                {simResult && (
                  <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-emerald-200 bg-emerald-50 p-2.5 font-mono text-[11px] text-emerald-800 shadow-sm">{simResult.reply || `Status: ${simResult.status}`}</pre>
                )}
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
