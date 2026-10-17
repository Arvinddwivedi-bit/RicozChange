import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type ChangeT } from '../api'
import { Search, Upload, Plus, FileX } from 'lucide-react'
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
    const token = await (window as any).__RC_AUTH__?.getToken?.()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(API_BASE + '/api/changes/import-csv', { method: 'POST', headers, body: form })
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
          <div className="eyebrow">Change Register</div>
          <h1 className="page-title">Changes</h1>
          <p className="mt-1 text-[13.5px] text-slate-500">Every request, its risk score and where it stands</p>
        </div>
        <div className="flex items-center gap-2">
          <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={onImport} />
          <button className="btn btn-ghost" onClick={() => fileRef.current?.click()}>
            <Upload className="w-4 h-4 mr-2" />
            Import CSV
          </button>
          <Link to="/changes/new" className="btn btn-primary">
            <Plus className="w-4 h-4 mr-2" />
            New Change
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
            className={`rounded-full px-3 py-1.5 text-xs font-semibold capitalize transition-colors ${
              status === s ? 'bg-brand-600 text-white shadow-sm ring-1 ring-brand-600' : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50 hover:text-slate-900'
            }`}
          >
            {s}
          </button>
        ))}
        <div className="relative ml-auto w-full max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input className="input w-full pl-9" placeholder="Search title or system…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      <div className="card divide-y divide-slate-100">
        {changes === null ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="p-4 flex flex-col gap-3">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 w-1/2">
                  <div className="w-10 h-6 skeleton rounded-full" />
                  <div className="h-5 skeleton rounded-md w-3/4" />
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-16 h-6 skeleton rounded-full" />
                  <div className="w-20 h-6 skeleton rounded-full" />
                </div>
              </div>
              <div className="h-4 skeleton rounded-md w-1/3 mt-2" />
            </div>
          ))
        ) : filtered.length === 0 ? (
          <div className="p-12 flex flex-col items-center justify-center text-center">
            <div className="w-12 h-12 rounded-full bg-slate-50 flex items-center justify-center mb-4">
              <FileX className="w-6 h-6 text-slate-400" />
            </div>
            <h3 className="text-sm font-semibold text-slate-900">No changes found</h3>
            <p className="mt-1 text-sm text-slate-500 max-w-sm">We couldn't find any changes matching your search or filters.</p>
            {q !== '' || status !== 'all' ? (
              <button onClick={() => { setQ(''); setStatus('all'); }} className="mt-4 text-sm font-medium text-brand-600 hover:text-brand-700">Clear filters</button>
            ) : (
              <Link to="/changes/new" className="mt-4 btn btn-ghost text-sm">Create your first change</Link>
            )}
          </div>
        ) : (
          filtered.map((c) => (
            <Link key={c.id} to={`/changes/${c.id}`} className="block p-4 hover:bg-slate-50 transition-colors">
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
          ))
        )}
      </div>
    </div>
  )
}
