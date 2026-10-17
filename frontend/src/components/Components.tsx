import { useEffect, useMemo, useState } from 'react'
import {
  Background,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react'
import { fmtDate, scoreColor, statusColor, type ChangeT, type Factor } from '../api'
import { Shield, CheckCircle2, TrendingUp, TrendingDown, Activity } from 'lucide-react'
import clsx from 'clsx'

export function ScoreBadge({ score }: { score: number | null | undefined }) {
  const isHigh = score != null && score > 60;
  const isLow = score != null && score < 40;
  return (
    <span className={clsx(`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-bold border`, scoreColor(score))}>
      {isHigh ? <Shield className="w-3 h-3" /> : isLow ? <CheckCircle2 className="w-3 h-3" /> : <Activity className="w-3 h-3" />}
      {score == null ? '—' : score}
    </span>
  )
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={clsx(`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize border`, statusColor(status))}>
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-75" />
      {status}
    </span>
  )
}

export function TypeBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    standard: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    normal: 'bg-slate-50 text-slate-700 border-slate-200',
    major: 'bg-orange-50 text-orange-700 border-orange-200',
    emergency: 'bg-red-50 text-red-700 border-red-200',
  }
  return (
    <span className={clsx(`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium border`, colors[type] ?? 'bg-slate-100 border-slate-200')}>
      {type}
    </span>
  )
}

export function RiskWhy({ factors, compact = false }: { factors: Factor[]; compact?: boolean }) {
  const positive = factors.filter((f) => f.points >= 0)
  const mitigations = factors.filter((f) => f.points < 0)
  const rows = (list: Factor[], tone: 'bad' | 'good') =>
    list.map((f, i) => (
      <div key={`${tone}-${i}`} className={clsx(`flex items-start gap-2.5 py-1.5`, compact ? 'text-xs' : 'text-sm')}>
        <span
          className={clsx(
            `mt-0.5 flex shrink-0 items-center justify-center gap-1 rounded px-1.5 py-0.5 font-mono text-xs font-bold border`,
            tone === 'bad' ? 'bg-red-50 text-red-700 border-red-200' : 'bg-emerald-50 text-emerald-700 border-emerald-200'
          )}
          title={tone === 'bad' ? 'increases risk' : 'reduces risk'}
        >
          {tone === 'bad' ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
          {f.points > 0 ? `+${f.points}` : f.points}
        </span>
        <span className="text-slate-700 leading-snug">{f.label}</span>
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
  children,
}: {
  systems: GraphSystem[]
  edges: { source: number; target: number }[]
  highlightedIds: number[]
  pulseIds?: number[]
  height?: number
  children?: React.ReactNode
}) {
  const nodes: Node[] = useMemo(
    () =>
      systems.map((s, i) => {
        const col = i % 3
        const row = Math.floor(i / 3)
        const isHot = highlightedIds.includes(s.id)
        const isPulse = pulseIds.includes(s.id)
        return {
          id: String(s.id),
          position: { x: 60 + col * 240, y: 40 + row * 140 },
          data: { label: `${s.name}\n${s.key}` },
          style: {
            borderRadius: 12,
            border: `2px solid ${isHot ? '#dc2626' : s.criticality === 'critical' ? '#f59e0b' : '#cbd5e1'}`,
            background: isHot ? '#fef2f2' : '#ffffff',
            color: '#0f172a',
            fontSize: 13,
            fontWeight: 500,
            padding: 12,
            width: 190,
            whiteSpace: 'pre-line',
            boxShadow: isPulse ? '0 0 0 4px rgba(220,38,38,0.25), 0 4px 6px -1px rgba(0,0,0,0.1)' : '0 4px 6px -1px rgba(0,0,0,0.1)',
            transition: 'all 0.2s ease',
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
          style: { stroke: hot ? '#dc2626' : '#cbd5e1', strokeWidth: hot ? 3 : 1.5 },
          markerEnd: { type: MarkerType.ArrowClosed, color: hot ? '#dc2626' : '#94a3b8' },
        }
      }),
    [edges, highlightedIds],
  )

  return (
    <div style={{ height }} className="rounded-xl border border-slate-200 bg-slate-50/50 shadow-inner overflow-hidden relative">
      <ReactFlow nodes={nodes} edges={rfEdges} fitView attributionPosition="bottom-right">
        <Background color="#cbd5e1" gap={20} size={2} />
        {children}
      </ReactFlow>
    </div>
  )
}

export function ChangeRowMeta({ change }: { change: ChangeT }) {
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-slate-500 font-medium">
      <span className="flex items-center gap-1.5">
        <Activity className="w-3.5 h-3.5 opacity-70" />
        {change.systems.map((s) => s.name).join(', ') || 'no systems'}
      </span>
      <span className="text-slate-300">•</span>
      <span>
        {fmtDate(change.window_start)} → {change.window_end ? fmtDate(change.window_end).split(', ').pop() : '—'}
      </span>
      {change.owner && (
        <>
          <span className="text-slate-300">•</span>
          <span className="flex items-center gap-1.5">
            <span className="w-4 h-4 rounded-full bg-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-600">
              {change.owner.name.charAt(0)}
            </span>
            {change.owner.name}
          </span>
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
