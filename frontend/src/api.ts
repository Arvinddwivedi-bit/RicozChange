export interface SystemNodeT {
  id: number
  key: string
  name: string
  environment: string
  criticality: string
  owner_team: string
}

export interface Factor {
  label: string
  points: number
}

export interface ApprovalT {
  id: number
  approver: { id: number; name: string } | null
  decision: string
  comment: string
  source: string
  decided_at: string | null
}

export interface CollisionT {
  change_id: number
  title: string
  status: string
  risk_type: string
  window_start: string | null
  window_end: string | null
  shared_systems: { id: number; key: string; name: string }[]
}

export interface FreezeT {
  id: number
  name: string
  reason: string
  starts_at: string
  ends_at: string
}

export interface AuditEntry {
  id: number
  action: string
  actor: string
  detail: string
  created_at: string
}

export interface ChangeT {
  id: number
  title: string
  description: string
  risk_type: string
  status: string
  owner: { id: number; name: string } | null
  template_id: number | null
  cab_meeting_id: number | null
  window_start: string | null
  window_end: string | null
  risk_score: number | null
  systems: { id: number; key: string; name: string }[]
  rollback_plan: string
  test_plan: string
  comms_plan: string
  post_change_result: string | null
  post_change_notes: string
  created_at: string
  updated_at: string
  factors?: Factor[]
  ai_rollback_draft?: string
  ai_test_draft?: string
  ai_comms_draft?: string
  approvals?: ApprovalT[]
  collisions?: CollisionT[]
  freeze_overlaps?: FreezeT[]
  audit?: AuditEntry[]
  transitions?: string[]
}

export interface SimResult {
  score: number
  factors: Factor[]
  collisions: CollisionT[]
  freeze_overlaps: FreezeT[]
}

export interface WindowSuggestion {
  start: string
  end: string
  weekend: boolean
  why: string
}

export interface NotificationT {
  id: number
  kind: string
  channel: string
  change_id: number | null
  approval_id: number | null
  message: {
    text: string
    blocks: {
      type: string
      text?: string
      fields?: Record<string, string | number>
      items?: Factor[]
      actions?: { action: string; label: string }[]
    }[]
  }
  acted: boolean
  acted_action: string | null
  created_at: string
}

export interface Actor {
  id: number
  name: string
  email: string
  role: string
}

export interface Bootstrap {
  actor: Actor
  users: { id: number; name: string; email: string; role: string }[]
  systems: SystemNodeT[]
  edges: { source: number; target: number; kind: string }[]
  templates: {
    id: number
    name: string
    icon: string
    description: string
    default_duration_minutes: number
    checklist: string[]
    rollback_plan: string
  }[]
}

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

export async function api<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body))
  }
  return res.json() as Promise<T>
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function scoreColor(score: number | null | undefined): string {
  if (score == null) return 'bg-slate-200 text-slate-600'
  if (score >= 70) return 'bg-red-100 text-red-700 ring-1 ring-red-200'
  if (score >= 40) return 'bg-amber-100 text-amber-700 ring-1 ring-amber-200'
  return 'bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200'
}

export function statusColor(status: string): string {
  switch (status) {
    case 'draft':
      return 'bg-slate-200 text-slate-700'
    case 'submitted':
      return 'bg-sky-100 text-sky-700'
    case 'approved':
      return 'bg-indigo-100 text-indigo-700'
    case 'implementing':
      return 'bg-amber-100 text-amber-700'
    case 'completed':
      return 'bg-emerald-100 text-emerald-700'
    case 'failed':
      return 'bg-red-100 text-red-700'
    case 'rejected':
      return 'bg-rose-100 text-rose-700'
    case 'cancelled':
      return 'bg-slate-100 text-slate-500'
    default:
      return 'bg-slate-100 text-slate-600'
  }
}
