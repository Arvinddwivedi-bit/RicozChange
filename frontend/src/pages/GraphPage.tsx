import { useEffect, useMemo, useState } from 'react'
import { api, type ChangeT } from '../api'
import { BlastRadiusGraph } from '../components/Components'
import { useBoot } from '../App'

export default function GraphPage() {
  const { boot } = useBoot()
  const [changes, setChanges] = useState<ChangeT[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<ChangeT | null>(null)

  useEffect(() => {
    api<ChangeT[]>('/api/changes').then((rows) => {
      const active = rows.filter((c) => ['submitted', 'approved', 'implementing'].includes(c.status))
      setChanges(active)
      if (active.length) setSelectedId(active[0].id)
    })
  }, [])

  useEffect(() => {
    if (selectedId) api<ChangeT>(`/api/changes/${selectedId}`).then(setDetail)
    else setDetail(null)
  }, [selectedId])

  const highlighted = useMemo(() => (detail ? detail.systems.map((s) => s.id) : []), [detail])
  const pulseIds = useMemo(() => {
    if (!detail) return []
    const ids = new Set<number>()
    detail.collisions?.forEach((c) => c.shared_systems.forEach((s) => ids.add(s.id)))
    return [...ids].filter((id) => highlighted.includes(id))
  }, [detail, highlighted])

  const selected = changes.find((c) => c.id === selectedId)

  return (
    <div className="p-8 space-y-5">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight">Blast radius</h1>
        <p className="text-sm text-slate-500">
          The live dependency map. Pick an active change: red = what it touches, pulsing = where it collides with someone else's work.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <select className="input max-w-md" value={selectedId ?? ''} onChange={(e) => setSelectedId(Number(e.target.value))}>
          <option value="" disabled>Choose an active change…</option>
          {changes.map((c) => (
            <option key={c.id} value={c.id}>
              #{c.id} · {c.title} ({c.status})
            </option>
          ))}
        </select>
        {selected && (
          <span className="text-sm text-slate-500">
            score {selected.risk_score ?? '—'} · {selected.systems.map((s) => s.name).join(', ')}
          </span>
        )}
      </div>

      <BlastRadiusGraph
        systems={boot.systems}
        edges={boot.edges}
        highlightedIds={highlighted}
        pulseIds={pulseIds}
        height={540}
      />

      {detail && (detail.collisions?.length || 0) > 0 && (
        <div className="card p-4 text-sm text-amber-800 bg-amber-50 border-amber-200">
          ⚠ Overlaps {detail.collisions!.length} other change(s){' '}
          {detail.collisions!.map((c) => `#${c.change_id} “${c.title}”`).join(', ')} — systems involved are pulsing on the map.
        </div>
      )}
    </div>
  )
}
