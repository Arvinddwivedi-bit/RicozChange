import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react'
import { fmtDate, scoreColor, type ChangeT, type Factor } from '../api'

export function ScoreBadge({ score }: { score: number | null | undefined }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold ${scoreColor(score)}`}>
      {score == null ? '—' : score}
    </span>
  )
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold bg-slate-100 text-slate-700">
      {status}
    </span>
  )
}

export function TypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    standard: 'bg-emerald-50 text-emerald-700',
    normal: 'bg-slate-100 text-slate-700',
    major: 'bg-orange-100 text-orange-700',
    emergency: 'bg-red-100 text-red-700',
  }
  return (
    <span className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${colors[type] ?? 'bg-slate-100'}`}>
      {type}
    </span>
  )
}

export function RiskWhy({ factors, compact = false }: { factors: Factor[]; compact?: boolean }) {
  const positive = factors.filter((f) => f.points >= 0)
  const mitigations = factors.filter((f) => f.points < 0)
  const rows = (list: Factor[], tone: 'bad' | 'good') =>
    list.map((f, i) => (
      <div key={`${tone}-${i}`} className={`flex items-start gap-2 py-1 ${compact ? 'text-xs' : 'text-sm'}`}>
        <span
          className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 font-mono text-xs font-bold ${
            tone === 'bad' ? 'bg-red-50 text-red-600' : 'bg-emerald-50 text-emerald-600'
          }`}
          title={tone === 'bad' ? 'increases risk' : 'reduces risk'}
        >
          {f.points > 0 ? `+${f.points}` : f.points}
        </span>
        <span className="text-slate-700">{f.label}</span>
      </div>
    ))
  return (
    <div className="divide-y divide-slate-100">
      {rows(positive, 'bad')}
      {rows(mitigations, 'good')}
    </div>
  )
}

interface GraphSystem {
  id: number
  key: string
  name: string
  environment: string
  criticality: string
}

export function BlastRadiusGraph({
  systems,
  edges,
  highlightedIds,
  pulseIds = [],
  height = 480,
}: {
  systems: GraphSystem[]
  edges: { source: number; target: number }[]
  highlightedIds: number[]
  pulseIds?: number[]
  height?: number
}) {
  const nodes: Node[] = useMemo(
    () =>
      systems.map((s, i) => {
        const col = i % 3
        const row = Math.floor(i / 3)
        const isHot = highlightedIds.includes(s.id)
        return {
          id: String(s.id),
          position: { x: 60 + col * 220, y: 40 + row * 120 },
          data: { label: `${s.name}\n${s.key}` },
          style: {
            borderRadius: 10,
            border: `2px solid ${isHot ? '#dc2626' : s.criticality === 'critical' ? '#f59e0b' : '#cbd5e1'}`,
            background: isHot ? '#fef2f2' : '#ffffff',
            color: '#0f172a',
            fontSize: 12,
            padding: 10,
            width: 180,
            whiteSpace: 'pre-line',
            boxShadow: pulseIds.includes(s.id) ? '0 0 0 4px rgba(220,38,38,0.25)' : undefined,
          },
        }
      }),
    [systems, highlightedIds, pulseIds],
  )

  const rfEdges: Edge[] = useMemo(
    () =>
      edges.map((e) => {
        const hot = highlightedIds.includes(e.source) && highlightedIds.includes(e.target)
        return {
          id: `${e.source}-${e.target}`,
          source: String(e.source),
          target: String(e.target),
          animated: hot,
          style: { stroke: hot ? '#dc2626' : '#cbd5e1', strokeWidth: hot ? 2.5 : 1.5 },
          markerEnd: { type: MarkerType.ArrowClosed, color: hot ? '#dc2626' : '#94a3b8' },
        }
      }),
    [edges, highlightedIds],
  )

  return (
    <div style={{ height }} className="rounded-lg border border-slate-200 bg-white">
      <ReactFlow nodes={nodes} edges={rfEdges} fitView>
        <Background color="#f1f5f9" gap={18} />
      </ReactFlow>
    </div>
  )
}

export function ChangeRowMeta({ change }: { change: ChangeT }) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
      <span>{change.systems.map((s) => s.name).join(', ') || 'no systems'}</span>
      <span>·</span>
      <span>
        {fmtDate(change.window_start)} → {change.window_end ? fmtDate(change.window_end).split(', ').pop() : '—'}
      </span>
      {change.owner && (
        <>
          <span>·</span>
          <span>{change.owner.name}</span>
        </>
      )}
    </div>
  )
}

export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}
