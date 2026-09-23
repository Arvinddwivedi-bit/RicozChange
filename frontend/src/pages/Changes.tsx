import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type ChangeT } from '../api'
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
import { ChangeRowMeta, ScoreBadge, StatusBadge, TypeBadge } from '../components/Components'

const STATUSES = ['all', 'draft', 'submitted', 'approved', 'implementing', 'completed', 'failed', 'rejected', 'cancelled']

export default function Changes() {
  const [changes, setChanges] = useState<ChangeT[] | null>(null)
  const [status, setStatus] = useState('all')
  const [q, setQ] = useState('')
  const [params] = useSearchParams()
  const [importMsg, setImportMsg] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  function load(statusValue = status) {
    const query = statusValue !== 'all' ? `?status=${statusValue}` : ''
    api<ChangeT[]>(`/api/changes${query}`).then(setChanges)
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status])

  async function onImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(API_BASE + '/api/changes/import-csv', { method: 'POST', body: form })
    const data = await res.json()
    if (res.ok) {
      setImportMsg(`Imported ${data.created} change(s)` + (data.errors.length ? ` · ${data.errors.length} row(s) skipped: ${data.errors[0]}` : ''))
      load()
    } else {
      setImportMsg(`Import failed: ${data.detail ?? res.statusText}`)
    }
    if (fileRef.current) fileRef.current.value = ''
  }

  const filtered = (changes ?? []).filter((c) =>
    q ? c.title.toLowerCase().includes(q.toLowerCase()) || c.systems.some((s) => s.name.toLowerCase().includes(q.toLowerCase())) : true,
  )

  return (
    <div className="p-8 space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight">Changes</h1>
          <p className="text-sm text-slate-500">Every request, its risk score and where it stands</p>
        </div>
        <div className="flex items-center gap-2">
          <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={onImport} />
          <button className="btn btn-ghost" onClick={() => fileRef.current?.click()}>
            Import CSV
          </button>
          <Link to="/changes/new" className="btn btn-primary">
            New change
          </Link>
        </div>
      </div>

      {params.get('new') && (
        <Link to="/changes/new" className="block card p-4 border-brand-300 bg-brand-50 text-sm text-brand-800 font-medium">
          Ready to create one? Start here →
        </Link>
      )}
      {importMsg && <div className="card p-3 text-sm text-slate-700">{importMsg}</div>}

      <div className="flex flex-wrap items-center gap-2">
        {STATUSES.map((s) => (
          <button
            key={s}
            onClick={() => setStatus(s)}
            className={`rounded-full px-3 py-1 text-xs font-semibold capitalize ${
              status === s ? 'bg-brand-600 text-white' : 'bg-white text-slate-600 border border-slate-200 hover:bg-slate-50'
            }`}
          >
            {s}
          </button>
        ))}
        <input className="input ml-auto max-w-xs" placeholder="Search title or system…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      <div className="card divide-y divide-slate-100">
        {filtered.length === 0 && <div className="p-6 text-sm text-slate-500">No changes match.</div>}
        {filtered.map((c) => (
          <Link key={c.id} to={`/changes/${c.id}`} className="block p-4 hover:bg-slate-50">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                <ScoreBadge score={c.risk_score} />
                <span className="font-semibold truncate">#{c.id} · {c.title}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <TypeBadge type={c.risk_type} />
                <StatusBadge status={c.status} />
              </div>
            </div>
            <ChangeRowMeta change={c} />
            {c.post_change_result && (
              <div className="mt-1 text-xs font-medium text-slate-600">
                Post-change check: <span className={c.post_change_result === 'success' ? 'text-emerald-600' : 'text-red-600'}>{c.post_change_result}</span>
              </div>
            )}
          </Link>
        ))}
      </div>
    </div>
  )
}
