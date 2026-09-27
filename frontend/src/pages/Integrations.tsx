import { useEffect, useState } from 'react'
import { api } from '../api'

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

function Toggle({ on }: { on: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ${
        on ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${on ? 'bg-emerald-500' : 'bg-slate-400'}`} />
      {on ? 'Connected' : 'Not configured'}
    </span>
  )
}

export default function Integrations() {
  const [slack, setSlack] = useState<SlackStatus | null>(null)
  const [authMode, setAuthMode] = useState<string | null>(null)
  const [email, setEmail] = useState<EmailStatus | null>(null)
  const [inbound, setInbound] = useState<InboundRow[]>([])
  const [simFrom, setSimFrom] = useState('dev@rico.dev')
  const [simSubject, setSimSubject] = useState('')
  const [simBody, setSimBody] = useState('')
  const [simBusy, setSimBusy] = useState(false)
  const [simResult, setSimResult] = useState<{ status: string; reply: string } | null>(null)
  const [simError, setSimError] = useState<string | null>(null)
  const [sweepBusy, setSweepBusy] = useState(false)
  const [sweepInfo, setSweepInfo] = useState<{ post_change_prompts: number; digests: number; slack_fallbacks: number } | null>(null)

  useEffect(() => {
    api<SlackStatus>('/api/integrations/slack/status').then(setSlack).catch(() => setSlack({ connected: false }))
    api<{ auth_mode: string }>('/api/auth/me').then((r) => setAuthMode(r.auth_mode)).catch(() => setAuthMode('unknown'))
    api<EmailStatus>('/api/integrations/email/status').then(setEmail).catch(() => setEmail(null))
    api<{ items: InboundRow[] }>('/api/integrations/email/inbound').then((r) => setInbound(r.items)).catch(() => setInbound([]))
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
      setSweepInfo(r)
    } finally {
      setSweepBusy(false)
    }
  }

  const emailMode = email !== null

  return (
    <div className="p-8 max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Integrations</h1>
        <p className="text-sm text-slate-500">Live connections that carry RicozChange into your team's daily tools.</p>
      </div>

      <div className="card p-5 flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <div className="w-10 h-10 shrink-0 rounded-lg bg-navy text-white flex items-center justify-center font-bold text-lg">#</div>
          <div>
            <div className="font-bold">Slack</div>
            <p className="text-sm text-slate-500 mt-0.5 max-w-md">
              Approval requests land as direct messages with the risk score and its reasoning inline. Approvers decide with one
              click — no login needed. Configure with <code className="text-xs bg-slate-100 rounded px-1">SLACK_CLIENT_ID</code> /
              <code className="text-xs bg-slate-100 rounded px-1">SLACK_CLIENT_SECRET</code>, then install via OAuth.
            </p>
          </div>
        </div>
        <div className="text-left sm:text-right shrink-0 space-y-2">
          <Toggle on={Boolean(slack?.connected)} />
          {slack?.connected === false && slack?.install_url && (
            <div>
              <a href={slack.install_url} className="btn btn-primary">
                Connect workspace
              </a>
            </div>
          )}
        </div>
      </div>

      <div className="card p-5 flex flex-col sm:flex-row sm:items-start justify-between gap-4">
        <div className="flex items-start gap-3 min-w-0">
          <div className="w-10 h-10 shrink-0 rounded-lg bg-brand-600 text-white flex items-center justify-center font-bold text-lg">R</div>
          <div>
            <div className="font-bold">Clerk sign-in</div>
            <p className="text-sm text-slate-500 mt-0.5 max-w-md">
              Real authentication: session tokens verified against Clerk's signing keys, roles enforced server-side, every
              action attributable. Admins are auto-provisioned from the <code className="text-xs bg-slate-100 rounded px-1">ADMIN_EMAILS</code> allowlist
              on first sign-in.
            </p>
          </div>
        </div>
        <div className="text-left sm:text-right shrink-0">
          <Toggle on={authMode === 'clerk'} />
          <div className="mt-1 text-[11px] text-slate-400">
            mode: {authMode ?? '…'}
          </div>
        </div>
      </div>

      <div className="card p-5">
        <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
          <div className="flex items-start gap-3 min-w-0">
            <div className="w-10 h-10 shrink-0 rounded-lg bg-navy text-white flex items-center justify-center font-bold text-lg">@</div>
            <div className="min-w-0">
              <div className="font-bold">Email-to-change</div>
              <p className="text-sm text-slate-500 mt-0.5 max-w-md">
                File a change by emailing the mailbox — parsed, scored and routed automatically.
                Email can only file a <b>draft</b>; humans submit. Replies always include the risk score and its reasoning.
              </p>
            </div>
          </div>
          <Toggle on={emailMode} />
        </div>

        {emailMode && (
          <div className="mt-4 grid gap-3 text-[12.5px] text-slate-600 sm:grid-cols-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <div className="text-[10.5px] font-bold uppercase tracking-wider text-slate-400">Mailbox (from)</div>
              <div className="mt-1 truncate font-medium text-navy">{email?.mailbox}</div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <div className="text-[10.5px] font-bold uppercase tracking-wider text-slate-400">Allowed domains</div>
              <div className="mt-1 truncate font-medium text-navy">{email?.allowed_domains.join(', ')}</div>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <div className="text-[10.5px] font-bold uppercase tracking-wider text-slate-400">Signature check</div>
              <div className="mt-1 font-medium text-navy">{email?.signature_check ? 'On (webhook key set)' : 'Off (demo)'}</div>
            </div>
          </div>
        )}

        <div className="mt-4 rounded-lg border border-slate-200 p-4">
          <div className="text-[13px] font-bold text-navy">Try it — simulate an inbound email</div>
          <p className="mt-0.5 text-[12px] text-slate-500">
            Runs the exact pipeline the webhook runs. Body keywords: <code className="rounded bg-slate-100 px-1">systems:</code>{' '}
            <code className="rounded bg-slate-100 px-1">window: 2026-10-01 22:00 - 23:30</code>{' '}
            <code className="rounded bg-slate-100 px-1">type:</code>{' '}
            <code className="rounded bg-slate-100 px-1">rollback:</code>
          </p>
          <div className="mt-3 grid gap-2">
            <div className="grid gap-2 sm:grid-cols-2">
              <input className="input text-[13px]" placeholder="From address (e.g. dev@rico.dev)" value={simFrom} onChange={(e) => setSimFrom(e.target.value)} />
              <input className="input text-[13px]" placeholder="Subject = change title" value={simSubject} onChange={(e) => setSimSubject(e.target.value)} />
            </div>
            <textarea
              className="input min-h-[92px] font-mono text-[12px]"
              placeholder={'Renew the API certificate.\nsystems: edge-proxy\nwindow: 2026-10-01 22:00 - 23:30\ntype: standard\nrollback: revert to the previous certificate'}
              value={simBody}
              onChange={(e) => setSimBody(e.target.value)}
            />
            <div className="flex flex-wrap items-center gap-2">
              <button className="btn btn-primary" disabled={simBusy || !simSubject.trim() || !simBody.trim()} onClick={runSimulate}>
                {simBusy ? 'Filing…' : 'File by email'}
              </button>
              {simError && <span className="text-[12px] font-medium text-red-600">{simError}</span>}
            </div>
          </div>
          {simResult && (
            <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-[11.5px] text-slate-700">{simResult.reply || `Status: ${simResult.status}`}</pre>
          )}
        </div>

        {inbound.length > 0 && (
          <div className="mt-4">
            <div className="flex items-center justify-between">
              <div className="text-[13px] font-bold text-navy">Recent inbound</div>
              <button className="btn btn-ghost !py-1 !px-2.5 text-[12px]" disabled={sweepBusy} onClick={runSweep}>
                {sweepBusy ? 'Running…' : 'Run sweep'}
              </button>
            </div>
            <div className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">
              {inbound.map((r) => (
                <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-[12.5px]">
                  <div className="min-w-0">
                    <span className="font-medium text-navy">{r.subject || '(no subject)'}</span>
                    <span className="ml-2 text-slate-400">{r.from_addr}</span>
                    {r.status === 'rejected' && <span className="ml-2 text-red-600">{r.error_detail}</span>}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className={`pill ${r.status === 'created' ? 'pill-green' : r.status === 'rejected' ? 'pill-red' : 'pill-amber'}`}>{r.status}</span>
                    {r.parsed_change_id && (
                      <a className="font-medium text-brand-700 hover:underline" href={`/changes/${r.parsed_change_id}`}>#{r.parsed_change_id}</a>
                    )}
                  </div>
                </div>
              ))}
            </div>
            {sweepInfo && <div className="mt-2 text-[12px] text-slate-500">Last sweep: {sweepInfo.post_change_prompts} post-change prompts · {sweepInfo.digests} digests · {sweepInfo.slack_fallbacks} Slack fallbacks</div>}
          </div>
        )}
      </div>
    </div>
  )
}
