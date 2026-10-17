import { useEffect, useMemo, useState } from 'react'
import { api, type ChangeT } from '../api'
import { BlastRadiusGraph } from '../components/Components'
import { useBoot } from '../App'
import { Network, ZoomIn, ZoomOut, Maximize2, Info } from 'lucide-react'
import { ReactFlowProvider, useReactFlow } from '@xyflow/react'

function GraphControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow()
  return (
    <div className="absolute bottom-4 left-4 z-10 flex items-center gap-1 bg-white p-1 rounded-lg shadow-sm border border-slate-200">
      <button className="p-2 text-slate-500 hover:text-brand-600 hover:bg-slate-50 rounded-md transition-colors" onClick={() => zoomIn({ duration: 300 })} title="Zoom In">
        <ZoomIn className="w-4 h-4" />
      </button>
      <button className="p-2 text-slate-500 hover:text-brand-600 hover:bg-slate-50 rounded-md transition-colors" onClick={() => zoomOut({ duration: 300 })} title="Zoom Out">
        <ZoomOut className="w-4 h-4" />
      </button>
      <button className="p-2 text-slate-500 hover:text-brand-600 hover:bg-slate-50 rounded-md transition-colors" onClick={() => fitView({ duration: 300 })} title="Fit View">
        <Maximize2 className="w-4 h-4" />
      </button>
    </div>
  )
}

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
    <div className="p-8 space-y-6 max-w-6xl mx-auto">
      <div>
        <div className="flex items-center gap-2 text-brand-600 mb-2">
          <Network className="w-5 h-5" />
          <div className="eyebrow !mb-0 !text-brand-600">Know Before You Go</div>
        </div>
        <h1 className="page-title">Blast Radius</h1>
        <p className="mt-2 text-[14px] text-slate-500 max-w-3xl leading-relaxed">
          The live dependency map. Pick an active change to visualize its impact. <strong className="font-semibold text-slate-700">Red borders</strong> indicate systems directly touched by the change, while <strong className="font-semibold text-amber-600">pulsing nodes</strong> highlight collisions with other active work.
        </p>
      </div>

      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-4 mb-4">
          <div className="flex-1 min-w-[300px]">
            <select className="input w-full shadow-sm bg-slate-50/50" value={selectedId ?? ''} onChange={(e) => setSelectedId(Number(e.target.value))}>
              <option value="" disabled>Choose an active change…</option>
              {changes.map((c) => (
                <option key={c.id} value={c.id}>
                  #{c.id} · {c.title} ({c.status})
                </option>
              ))}
            </select>
          </div>
          {selected && (
            <div className="flex items-center gap-3 px-4 py-2 bg-slate-50 rounded-lg border border-slate-200">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Score</span>
                <span className={`font-bold ${selected.risk_score && selected.risk_score > 50 ? 'text-red-600' : 'text-emerald-600'}`}>
                  {selected.risk_score ?? '—'}
                </span>
              </div>
              <div className="w-px h-4 bg-slate-300"></div>
              <div className="text-sm text-slate-600 truncate max-w-sm">
                <span className="font-medium text-slate-900">{selected.systems.length}</span> systems
              </div>
            </div>
          )}
        </div>

        <div className="relative">
          <ReactFlowProvider>
            <BlastRadiusGraph
              systems={boot.systems}
              edges={boot.edges}
              highlightedIds={highlighted}
              pulseIds={pulseIds}
              height={600}
            >
              <GraphControls />
              
              <div className="absolute top-4 right-4 z-10 bg-white/90 backdrop-blur p-3 rounded-lg shadow-sm border border-slate-200 text-xs text-slate-600 flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full border-2 border-slate-300 bg-white"></div>
                  <span>Standard System</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full border-2 border-amber-500 bg-white"></div>
                  <span>Critical System</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full border-2 border-red-600 bg-red-50"></div>
                  <span>Touched by Change</span>
                </div>
                <div className="flex items-center gap-2 mt-1 pt-2 border-t border-slate-100">
                  <div className="w-3 h-3 rounded-full border-2 border-red-600 bg-red-50 shadow-[0_0_0_3px_rgba(220,38,38,0.2)]"></div>
                  <span className="text-amber-700 font-medium">Collision detected</span>
                </div>
              </div>
            </BlastRadiusGraph>
          </ReactFlowProvider>
        </div>
      </div>

      {detail && (detail.collisions?.length || 0) > 0 && (
        <div className="flex items-start gap-3 card p-4 bg-amber-50/50 border-amber-200 shadow-sm">
          <Info className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
          <div className="text-[13.5px] text-amber-900 leading-relaxed">
            <strong className="font-semibold text-amber-950">Overlaps {detail.collisions!.length} other change{detail.collisions!.length > 1 ? 's' : ''}:</strong>{' '}
            {detail.collisions!.map((c) => `#${c.change_id} “${c.title}”`).join(', ')} — systems involved are pulsing on the map.
          </div>
        </div>
      )}
    </div>
  )
}
