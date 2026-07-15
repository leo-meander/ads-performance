'use client'

import { useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ReferenceDot, ReferenceLine,
} from 'recharts'
import { fmtMoney, fmtNum } from './dashboardUtils'

// Linear regression: returns [slope, intercept] for y = slope*x + intercept
function linearRegression(ys: number[]): [number, number] {
  const n = ys.length
  if (n < 2) return [0, ys[0] ?? 0]
  const xs = ys.map((_, i) => i)
  const sumX = xs.reduce((a, b) => a + b, 0)
  const sumY = ys.reduce((a, b) => a + b, 0)
  const sumXY = xs.reduce((a, x, i) => a + x * ys[i], 0)
  const sumX2 = xs.reduce((a, x) => a + x * x, 0)
  const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX)
  const intercept = (sumY - slope * sumX) / n
  return [slope, intercept]
}

// An activity marker overlaid on the trend at a given day.
export type TrendMarker = { day: string; count: number; color: string; firstId: string }

export type TrendRow = {
  date: string
  spend: number
  revenue: number
  roas: number
  ctr: number
  cpa: number
  cpc: number
  cr: number
  aov: number
  conversions: number
  // Funnel drop-off rates (% lost between consecutive stages)
  do_imp_click: number   // Impression → Click
  do_click_search: number // Click → Search
  do_search_cart: number  // Search → Add to Cart
  do_cart_checkout: number // Add to Cart → Checkout
  do_checkout_book: number // Checkout → Booking
}

type MetricKind = 'money' | 'x' | 'pct' | 'num'
type MetricKey = keyof Omit<TrendRow, 'date'>

type MetricDef = { key: MetricKey; label: string; color: string; kind: MetricKind; group?: string }

// Order mirrors the KPI cards above (Cost first), then ROAS decomposition,
// then funnel drop-off rates.
const METRICS: MetricDef[] = [
  { key: 'spend', label: 'Cost', color: '#ef4444', kind: 'money' },
  { key: 'revenue', label: 'Revenue', color: '#10b981', kind: 'money' },
  { key: 'roas', label: 'ROAS', color: '#3b82f6', kind: 'x' },
  { key: 'ctr', label: 'CTR', color: '#f59e0b', kind: 'pct' },
  { key: 'cpa', label: 'CPA', color: '#8b5cf6', kind: 'money' },
  { key: 'conversions', label: 'Conversions', color: '#0ea5e9', kind: 'num' },
  { key: 'cr', label: 'CR', color: '#14b8a6', kind: 'pct' },
  { key: 'aov', label: 'AOV', color: '#a68a64', kind: 'money' },
  { key: 'cpc', label: 'CPC', color: '#ec4899', kind: 'money' },
  // Funnel drop-off metrics — shown in a second row with a visual separator.
  { key: 'do_imp_click', label: 'Drop: Imp→Click', color: '#64748b', kind: 'pct', group: 'funnel' },
  { key: 'do_click_search', label: 'Drop: Click→Search', color: '#475569', kind: 'pct', group: 'funnel' },
  { key: 'do_search_cart', label: 'Drop: Search→Cart', color: '#94a3b8', kind: 'pct', group: 'funnel' },
  { key: 'do_cart_checkout', label: 'Drop: Cart→Checkout', color: '#f97316', kind: 'pct', group: 'funnel' },
  { key: 'do_checkout_book', label: 'Drop: Checkout→Book', color: '#dc2626', kind: 'pct', group: 'funnel' },
]

function formatValue(v: number, kind: MetricKind, currency: string): string {
  if (v === null || v === undefined) return '--'
  switch (kind) {
    case 'money': return fmtMoney(v, currency)
    case 'x': return `${v.toFixed(2)}x`
    case 'pct': return `${v.toFixed(2)}%`
    case 'num': return fmtNum(v)
  }
}

export default function MetricTrendChart({
  data, prevData, currency, markers = [], onMarkerClick, title = 'Metric Trends', headerRight, bare = false,
}: {
  data: TrendRow[]
  // Optional prior-period rows for comparison overlay (dashed lines).
  prevData?: TrendRow[]
  currency: string
  markers?: TrendMarker[]
  onMarkerClick?: (firstId: string) => void
  title?: string
  headerRight?: React.ReactNode
  bare?: boolean
}) {
  const [selected, setSelected] = useState<MetricKey[]>(['spend', 'roas'])
  const [indexed, setIndexed] = useState(true)
  const [showPrev, setShowPrev] = useState(false)
  const [showTrend, setShowTrend] = useState(false)

  const toggle = (key: MetricKey) => {
    setSelected(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key])
  }

  // Per-metric max over current period (used for indexed normalization).
  const maxes = useMemo(() => {
    const m: Record<string, number> = {}
    for (const def of METRICS) {
      m[def.key] = Math.max(0, ...data.map(d => Number(d[def.key]) || 0))
    }
    return m
  }, [data])

  // Per-metric averages (current + prev period).
  const averages = useMemo(() => {
    const a: Record<string, number> = {}
    for (const def of METRICS) {
      const ys = data.map(d => Number(d[def.key]) || 0).filter(v => v > 0)
      a[def.key] = ys.length > 0 ? ys.reduce((s, v) => s + v, 0) / ys.length : 0
    }
    return a
  }, [data])

  const prevAverages = useMemo(() => {
    if (!prevData || prevData.length === 0) return {} as Record<string, number>
    const a: Record<string, number> = {}
    for (const def of METRICS) {
      const ys = prevData.map(d => Number(d[def.key]) || 0).filter(v => v > 0)
      a[def.key] = ys.length > 0 ? ys.reduce((s, v) => s + v, 0) / ys.length : 0
    }
    return a
  }, [prevData])

  // Pre-compute regression coefficients once per metric (not per row).
  const regressions = useMemo(() => {
    const r: Record<string, [number, number]> = {}
    for (const def of METRICS) {
      const ys = data.map(d => Number(d[def.key]) || 0)
      r[def.key] = linearRegression(ys)
    }
    return r
  }, [data])

  // Prev-period regression — same number of points as prevData.
  const prevRegressions = useMemo(() => {
    if (!prevData || prevData.length === 0) return {} as Record<string, [number, number]>
    const r: Record<string, [number, number]> = {}
    for (const def of METRICS) {
      const ys = prevData.map(d => Number(d[def.key]) || 0)
      r[def.key] = linearRegression(ys)
    }
    return r
  }, [prevData])

  // Prev-period indexed relative to CURRENT period max so both lines share the
  // same scale and are directly comparable.
  const chartData = useMemo(() => data.map((row, i) => {
    const out: Record<string, number | string> = { date: row.date }
    for (const def of METRICS) {
      const raw = Number(row[def.key]) || 0
      out[def.key] = raw
      const max = maxes[def.key]
      out[`${def.key}__idx`] = max > 0 ? (raw / max) * 100 : 0

      const [slope, intercept] = regressions[def.key]
      const trendRaw = slope * i + intercept
      out[`${def.key}__trend`] = trendRaw
      out[`${def.key}__trend_idx`] = max > 0 ? (trendRaw / max) * 100 : 0

      if (prevData && prevData[i]) {
        const prevRaw = Number(prevData[i][def.key]) || 0
        out[`${def.key}__prev`] = prevRaw
        out[`${def.key}__prev_idx`] = max > 0 ? (prevRaw / max) * 100 : 0

        // Prev trendline — regression over prev series, indexed vs current max
        if (prevRegressions[def.key]) {
          const [ps, pi] = prevRegressions[def.key]
          const prevTrendRaw = ps * i + pi
          out[`${def.key}__prev_trend`] = prevTrendRaw
          out[`${def.key}__prev_trend_idx`] = max > 0 ? (prevTrendRaw / max) * 100 : 0
        }
      }
    }
    return out
  }), [data, prevData, maxes, regressions, prevRegressions])

  const selectedDefs = METRICS.filter(d => selected.includes(d.key))

  // Anchor activity markers onto the first selected metric's line so they sit
  // on the curve (matching the indexed/raw mode currently shown).
  const anchorDef = selectedDefs[0]
  const anchorKey = anchorDef ? (indexed ? `${anchorDef.key}__idx` : anchorDef.key) : null
  const valueByDay = useMemo(() => {
    const m: Record<string, number> = {}
    if (anchorKey) for (const row of chartData) m[row.date as string] = Number(row[anchorKey]) || 0
    return m
  }, [chartData, anchorKey])

  return (
    <div className={bare ? '' : 'bg-white rounded-xl border border-gray-200 p-6'}>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-sm font-semibold text-gray-700">{title}</h2>
        <div className="flex items-center gap-3 flex-wrap">
          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={indexed}
              onChange={() => setIndexed(v => !v)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Indexed (100 = period max)
          </label>
          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={showTrend}
              onChange={() => setShowTrend(v => !v)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Trendline
          </label>
          {prevData && prevData.length > 0 && (
            <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showPrev}
                onChange={() => setShowPrev(v => !v)}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              vs last period
            </label>
          )}
          {headerRight}
        </div>
      </div>

      {/* Metric toggles — split into two rows: performance metrics and funnel drop-offs. */}
      <div className="flex flex-wrap gap-2 mb-1">
        {METRICS.filter(d => !d.group).map(def => {
          const on = selected.includes(def.key)
          return (
            <button
              key={def.key}
              onClick={() => toggle(def.key)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                on ? 'border-gray-300 bg-gray-50 text-gray-800' : 'border-gray-200 text-gray-400 hover:text-gray-600'
              }`}
            >
              <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: on ? def.color : '#d1d5db' }} />
              {def.label}
            </button>
          )
        })}
      </div>
      <div className="flex flex-wrap gap-2 mb-4 pt-1.5 border-t border-gray-100">
        <span className="self-center text-[10px] text-gray-400 font-medium uppercase tracking-wide mr-1">Funnel drop-off</span>
        {METRICS.filter(d => d.group === 'funnel').map(def => {
          const on = selected.includes(def.key)
          return (
            <button
              key={def.key}
              onClick={() => toggle(def.key)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                on ? 'border-gray-300 bg-gray-50 text-gray-800' : 'border-gray-200 text-gray-400 hover:text-gray-600'
              }`}
            >
              <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: on ? def.color : '#d1d5db' }} />
              {def.label}
            </button>
          )
        })}
      </div>

      {selectedDefs.length === 0 ? (
        <p className="text-gray-400 text-sm text-center py-20">Select at least one metric.</p>
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => String(v).slice(5)} />
            <YAxis
              tick={{ fontSize: 11 }}
              tickFormatter={(v) => indexed ? `${Math.round(v)}` : fmtNum(v)}
              domain={indexed ? [0, 100] : ['auto', 'auto']}
            />
            <Tooltip
              labelFormatter={(l) => `Date: ${l}`}
              content={({ active, payload, label }) => {
                if (!active || !payload || payload.length === 0) return null
                const row = payload[0].payload as Record<string, number>
                return (
                  <div className="bg-white border border-gray-200 rounded-lg shadow-sm px-3 py-2 text-xs">
                    <p className="text-gray-500 mb-1">Date: {label}</p>
                    {selectedDefs.map(def => {
                      const cur = Number(row[def.key]) || 0
                      const prev = Number(row[`${def.key}__prev`]) || 0
                      const hasPrev = showPrev && prevData && prevData.length > 0
                      const pctDiff = hasPrev && prev !== 0 ? ((cur - prev) / Math.abs(prev)) * 100 : null
                      return (
                        <div key={def.key} className="flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: def.color }} />
                          <span className="text-gray-600">{def.label}:</span>
                          <span className="font-medium text-gray-900">
                            {formatValue(cur, def.kind, currency)}
                            {indexed && (
                              <span className="text-gray-400 font-normal ml-1">
                                ({Math.round(Number(row[`${def.key}__idx`]) || 0)})
                              </span>
                            )}
                          </span>
                          {hasPrev && (
                            <span className={`text-xs font-medium ${pctDiff === null ? 'text-gray-400' : pctDiff >= 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                              {pctDiff !== null ? `${pctDiff >= 0 ? '+' : ''}${pctDiff.toFixed(1)}%` : '—'}
                            </span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )
              }}
            />
            <Legend />
            {!showTrend && selectedDefs.map(def => (
              <Line
                key={def.key}
                type="monotone"
                dataKey={indexed ? `${def.key}__idx` : def.key}
                name={def.label}
                stroke={def.color}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
              />
            ))}
            {!showTrend && showPrev && selectedDefs.map(def => (
              <Line
                key={`${def.key}__prev`}
                type="monotone"
                dataKey={indexed ? `${def.key}__prev_idx` : `${def.key}__prev`}
                name={`${def.label} (prev)`}
                stroke={def.color}
                strokeWidth={1.5}
                strokeDasharray="4 3"
                strokeOpacity={0.5}
                dot={false}
                activeDot={false}
                legendType="none"
              />
            ))}
            {showTrend && selectedDefs.map(def => {
              const avg = averages[def.key] || 0
              const avgIdx = maxes[def.key] > 0 ? (avg / maxes[def.key]) * 100 : 0
              const avgVal = indexed ? avgIdx : avg
              const prevAvg = prevAverages[def.key] || 0
              const prevAvgIdx = maxes[def.key] > 0 ? (prevAvg / maxes[def.key]) * 100 : 0
              const prevAvgVal = indexed ? prevAvgIdx : prevAvg
              return [
                // Current trendline — thick, solid
                <Line
                  key={`${def.key}__trend`}
                  type="linear"
                  dataKey={indexed ? `${def.key}__trend_idx` : `${def.key}__trend`}
                  stroke={def.color}
                  strokeWidth={3}
                  strokeOpacity={1}
                  dot={false}
                  activeDot={false}
                  legendType="none"
                />,
                // Prev trendline — same thickness, muted
                ...(showPrev ? [<Line
                  key={`${def.key}__prev_trend`}
                  type="linear"
                  dataKey={indexed ? `${def.key}__prev_trend_idx` : `${def.key}__prev_trend`}
                  stroke={def.color}
                  strokeWidth={3}
                  strokeOpacity={0.35}
                  dot={false}
                  activeDot={false}
                  legendType="none"
                />] : []),
                // Current period average — thin horizontal line
                <ReferenceLine
                  key={`${def.key}__avg`}
                  y={avgVal}
                  stroke={def.color}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  strokeOpacity={0.6}
                  label={{ value: `avg ${formatValue(avg, def.kind, currency)}`, fill: def.color, fontSize: 10, position: 'insideTopRight' }}
                />,
                // Prev average — same but muted
                ...(showPrev && prevAvg > 0 ? [<ReferenceLine
                  key={`${def.key}__prev_avg`}
                  y={prevAvgVal}
                  stroke={def.color}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  strokeOpacity={0.3}
                  label={{ value: `prev avg ${formatValue(prevAvg, def.kind, currency)}`, fill: def.color, fontSize: 10, position: 'insideBottomRight' }}
                />] : []),
              ]
            })}
            {anchorKey && markers.map(m => (
              <ReferenceDot
                key={m.day}
                x={m.day}
                y={valueByDay[m.day] ?? 0}
                r={m.count > 5 ? 7 : 5}
                fill={m.color}
                stroke="#fff"
                strokeWidth={2}
                ifOverflow="visible"
                onClick={() => onMarkerClick?.(m.firstId)}
                style={{ cursor: onMarkerClick ? 'pointer' : 'default' }}
                label={m.count > 1 ? {
                  value: m.count, fill: '#fff', fontSize: 9, fontWeight: 700, position: 'center',
                } : undefined}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
