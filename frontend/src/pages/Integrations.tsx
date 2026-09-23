import { useEffect, useState } from 'react'
import { api } from '../api'

interface SlackStatus {
  connected: boolean
  install_url?: string
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

  useEffect(() => {
    api<SlackStatus>('/api/integrations/slack/status').then(setSlack).catch(() => setSlack({ connected: false }))
    api<{ auth_mode: string }>('/api/auth/me').then((r) => setAuthMode(r.auth_mode)).catch(() => setAuthMode('unknown'))
  }, [])

  return (
    <div className="p-8 max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Integrations</h1>
        <p className="text-sm text-slate-500">Live connections that carry RicozChange into your team's daily tools.</p>
      </div>

      <div className="card p-5 flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-navy text-white flex items-center justify-center font-bold text-lg">#</div>
          <div>
            <div className="font-bold">Slack</div>
            <p className="text-sm text-slate-500 mt-0.5 max-w-md">
              Approval requests land as direct messages with the risk score and its reasoning inline. Approvers decide with one
              click — no login needed. Configure with <code className="text-xs bg-slate-100 rounded px-1">SLACK_CLIENT_ID</code> /
              <code className="text-xs bg-slate-100 rounded px-1">SLACK_CLIENT_SECRET</code>, then install via OAuth.
            </p>
          </div>
        </div>
        <div className="text-right shrink-0 space-y-2">
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

      <div className="card p-5 flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-brand-600 text-white flex items-center justify-center font-bold text-lg">R</div>
          <div>
            <div className="font-bold">Clerk sign-in</div>
            <p className="text-sm text-slate-500 mt-0.5 max-w-md">
              Real authentication: session tokens verified against Clerk's signing keys, roles enforced server-side, every
              action attributable. Admins are auto-provisioned from the <code className="text-xs bg-slate-100 rounded px-1">ADMIN_EMAILS</code> allowlist
              on first sign-in.
            </p>
          </div>
        </div>
        <div className="text-right shrink-0">
          <Toggle on={authMode === 'clerk'} />
          <div className="mt-1 text-[11px] text-slate-400">
            mode: {authMode ?? '…'}
          </div>
        </div>
      </div>

      <div className="card p-5 opacity-70">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-lg bg-slate-100 text-slate-400 flex items-center justify-center font-bold text-lg">✉</div>
          <div>
            <div className="font-bold text-slate-500">Email-to-change</div>
            <p className="text-sm text-slate-500 mt-0.5">
              File a change by emailing a mailbox — parsed, scored and routed automatically. Next on the roadmap
              (<code className="text-xs bg-slate-100 rounded px-1">docs/ROADMAP.md</code>, v0.2 week 3).
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
