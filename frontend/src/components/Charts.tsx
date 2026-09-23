/** Hand-rolled SVG charts — no chart library, exact brand control. */

export interface WeekVolume {
  standard: number
  normal: number
  major: number
  emergency: number
  [k: string]: number
}

export interface WeekCfr {
  success: number
  failed: number
  partial: number
  [k: string]: number
}

export interface Trends {
  weeks: string[]
  volume: WeekVolume[]
  cfr: WeekCfr[]
  type_mix: Record<string, number>
  system_heat: [string, number][]
}

const TYPE_COLORS: Record<string, string> = {
  standard: '#10b981',
  normal: '#94a3b8',
  major: '#f59e0b',
  emergency: '#d4222c',
}

/** Stacked weekly volume bars with a legend. */
export function VolumeBars({ weeks, volume }: { weeks: string[]; volume: WeekVolume[] }) {
  const H = 120
  const max = Math.max(1, ...volume.map((w) => Object.values(w).reduce((a, b) => a + b, 0)))
  const types = ['standard', 'normal', 'major', 'emergency']

  return (
    <div>
      <div className="flex items-end gap-2" style={{ height: H + 22 }}>
        {volume.map((week, i) => {
          const total = Object.values(week).reduce((a, b) => a + b, 0)
          return (
            <div key={i} className="group relative flex flex-1 flex-col items-center justify-end" style={{ height: '100%' }}>
              {/* stacked bars — column-reverse anchors the first segment to the bottom baseline */}
              <div className="flex w-full max-w-[34px] flex-col-reverse items-stretch gap-[2px]" style={{ height: H }}>
                {types.map((t) => {
                  const v = week[t] ?? 0
                  if (!v) return null
                  return (
                    <div
                      key={t}
                      className="w-full shrink-0 rounded-[3px] transition-opacity group-hover:opacity-100"
                      style={{ height: `${(v / max) * (H - 18)}px`, background: TYPE_COLORS[t], opacity: 0.9 }}
                      title={`${t}: ${v}`}
                    />
                  )
                })}
              </div>
              <span className="mt-1 text-[10px] font-medium text-slate-400">{weeks[i]}</span>
              {total > 0 && (
                <span className="pointer-events-none absolute -top-1 rounded-md bg-navy px-1.5 py-0.5 text-[10px] font-semibold text-white opacity-0 transition-opacity group-hover:opacity-100">
                  {total} change{total > 1 ? 's' : ''}
                </span>
              )}
            </div>
          )
        })}
      </div>
      <div className="mt-2 flex flex-wrap gap-3">
        {types.map((t) => (
          <span key={t} className="flex items-center gap-1.5 text-[11px] text-slate-500">
            <span className="h-2 w-2 rounded-sm" style={{ background: TYPE_COLORS[t] }} />
            {t}
          </span>
        ))}
      </div>
    </div>
  )
}

/** CFR line: % failed-or-partial per week, 0-100 scale with gridlines. */
export function CfrLine({ weeks, cfr }: { weeks: string[]; cfr: WeekCfr[] }) {
  const W = 100 // viewBox width units
  const H = 100
  const pts = cfr.map((w, i) => {
    const total = w.success + w.failed + w.partial
    const pct = total ? (w.failed + w.partial) / total : 0
    return { x: (i / Math.max(1, cfr.length - 1)) * W, y: H - pct * H, pct: Math.round(pct * 100), total }
  })
  const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const area = `${path} L${W},${H} L0,${H} Z`
  const maxTotal = Math.max(0, ...pts.map((p) => p.total))

  return (
    <div>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-[120px] w-full">
          {/* gridlines at 25/50/75% */}
          {[0.25, 0.5, 0.75].map((g) => (
            <line key={g} x1="0" x2={W} y1={H * g} y2={H * g} stroke="#eef1f5" strokeWidth="0.8" />
          ))}
          <path d={area} fill="rgba(212,34,44,0.07)" />
          <path d={path} fill="none" stroke="#d4222c" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" strokeLinecap="round" />
        </svg>
        {/* dots as HTML overlays — SVG circles would stretch into ellipses under non-uniform scaling */}
        {pts.map((p, i) => (
          <span
            key={i}
            className="absolute -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-white"
            style={{
              left: `${p.x}%`,
              top: `${p.y}%`,
              width: p.total ? 9 : 6,
              height: p.total ? 9 : 6,
              background: p.total ? '#d4222c' : '#cbd5e1',
            }}
            title={`week of ${weeks[i]}: ${p.pct}% failure (${p.total} outcome${p.total === 1 ? '' : 's'})`}
          />
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] font-medium text-slate-400">
        <span>{weeks[0]}</span>
        <span>{weeks[weeks.length - 1]}</span>
      </div>
      <p className="mt-1 text-[11px] text-slate-400">
        Per-week failure rate (failed + partial outcomes). {maxTotal > 0 ? `Busiest week: ${maxTotal} outcomes.` : 'No outcomes yet.'}
      </p>
    </div>
  )
}

/** Donut of change classes with center total. */
export function TypeDonut({ mix }: { mix: Record<string, number> }) {
  const entries = Object.entries(mix)
  const total = entries.reduce((a, [, v]) => a + v, 0)
  let acc = 0
  const R = 15.9155 // radius so circumference = 100

  return (
    <div className="flex items-center gap-5">
      <div className="relative h-[116px] w-[116px] shrink-0">
        <svg viewBox="0 0 42 42" className="h-full w-full -rotate-90">
          <circle cx="21" cy="21" r={R} fill="none" stroke="#f1f3f7" strokeWidth="6" />
          {entries.map(([k, v]) => {
            const frac = total ? (v / total) * 100 : 0
            const el = (
              <circle
                key={k}
                cx="21"
                cy="21"
                r={R}
                fill="none"
                stroke={TYPE_COLORS[k] ?? '#94a3b8'}
                strokeWidth="6"
                strokeDasharray={`${frac} ${100 - frac}`}
                strokeDashoffset={-acc}
                className="transition-all duration-500"
              />
            )
            acc += frac
            return el
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xl font-bold text-navy">{total}</span>
          <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400">changes</span>
        </div>
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        {entries.map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 text-[12.5px]">
            <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: TYPE_COLORS[k] ?? '#94a3b8' }} />
            <span className="flex-1 capitalize text-slate-600">{k}</span>
            <span className="font-semibold text-navy">{v}</span>
            <span className="w-9 text-right text-slate-400">{total ? Math.round((v / total) * 100) : 0}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Small donut for arbitrary key→count data (e.g. CAB decisions). */
export function MiniDonut({
  data,
  colors,
  centerLabel,
}: {
  data: Record<string, number>
  colors: Record<string, string>
  centerLabel?: string
}) {
  const entries = Object.entries(data).filter(([, v]) => v > 0)
  const total = entries.reduce((a, [, v]) => a + v, 0)
  let acc = 0
  const R = 15.9155

  if (!total) {
    return <p className="text-sm text-slate-400">Nothing to chart yet.</p>
  }

  return (
    <div className="flex items-center gap-5">
      <div className="relative h-[104px] w-[104px] shrink-0">
        <svg viewBox="0 0 42 42" className="h-full w-full -rotate-90">
          <circle cx="21" cy="21" r={R} fill="none" stroke="#f1f3f7" strokeWidth="6" />
          {entries.map(([k, v]) => {
            const frac = (v / total) * 100
            const el = (
              <circle
                key={k}
                cx="21"
                cy="21"
                r={R}
                fill="none"
                stroke={colors[k] ?? '#94a3b8'}
                strokeWidth="6"
                strokeDasharray={`${frac} ${100 - frac}`}
                strokeDashoffset={-acc}
                className="transition-all duration-500"
              />
            )
            acc += frac
            return el
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-bold text-navy">{total}</span>
          {centerLabel && <span className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{centerLabel}</span>}
        </div>
      </div>
      <div className="min-w-0 flex-1 space-y-1.5">
        {entries.map(([k, v]) => (
          <div key={k} className="flex items-center gap-2 text-[12.5px]">
            <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: colors[k] ?? '#94a3b8' }} />
            <span className="flex-1 capitalize text-slate-600">{k.replace(/_/g, ' ')}</span>
            <span className="font-semibold text-navy">{v}</span>
            <span className="w-9 text-right text-slate-400">{Math.round((v / total) * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Tiny bars of events per day, last N days — for the audit page. */
export function ActivitySpark({ rows, days = 14 }: { rows: { created_at: string }[]; days?: number }) {
  const counts = new Array<number>(days).fill(0)
  const today = new Date()
  today.setHours(23, 59, 59, 999)
  for (const r of rows) {
    const d = new Date(r.created_at)
    const back = Math.floor((today.getTime() - d.getTime()) / 86_400_000)
    if (back >= 0 && back < days) counts[days - 1 - back] += 1
  }
  const max = Math.max(1, ...counts)
  const labels: string[] = []
  for (let i = days - 1; i >= 0; i--) {
    labels.push(new Date(Date.now() - i * 86_400_000).toLocaleDateString(undefined, { day: '2-digit', month: 'short' }))
  }
  const busiest = Math.max(...counts)

  return (
    <div>
      <div className="flex items-end gap-[3px]" style={{ height: 56 }}>
        {counts.map((v, i) => (
          <div key={i} className="group relative flex-1">
            <div
              className="w-full rounded-[3px] transition-all duration-300"
              style={{
                height: `${Math.max(v ? 4 : 2, (v / max) * 56)}px`,
                background: v ? (v === busiest ? '#d4222c' : 'rgba(212,34,44,0.45)') : '#eef1f5',
              }}
              title={`${labels[i]}: ${v} ${v === 1 ? 'event' : 'events'}`}
            />
          </div>
        ))}
      </div>
      <div className="mt-1 flex justify-between text-[10px] font-medium text-slate-400">
        <span>{labels[0]}</span>
        <span>{labels[labels.length - 1]}</span>
      </div>
      <p className="mt-1 text-[11px] text-slate-400">Events per day, last {days} days. Peak day: {busiest}.</p>
    </div>
  )
}

/** Horizontal "heat" bars: most-changed systems. */
export function SystemHeat({ rows }: { rows: [string, number][] }) {
  const max = Math.max(1, ...rows.map(([, v]) => v))
  if (!rows.length) return <p className="text-sm text-slate-400">No system activity yet.</p>
  return (
    <div className="space-y-2.5">
      {rows.map(([name, v]) => (
        <div key={name} className="flex items-center gap-3">
          <span className="w-32 shrink-0 truncate text-[12.5px] font-medium text-slate-600" title={name}>
            {name}
          </span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{ width: `${(v / max) * 100}%`, background: 'linear-gradient(90deg, #e96b77, #d4222c)' }}
            />
          </div>
          <span className="w-6 text-right text-[12px] font-semibold text-navy">{v}</span>
        </div>
      ))}
    </div>
  )
}
