'use client'

import { useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, ReferenceDot,
} from 'recharts'
import { fmtMoney, fmtNum } from './dashboardUtils'

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
}

type MetricKind = 'money' | 'x' | 'pct' | 'num'
type MetricKey = keyof Omit<TrendRow, 'date'>

type MetricDef = { key: MetricKey; label: string; color: string; kind: MetricKind }

// Order mirrors the KPI cards above (Cost first), then ROAS decomposition.
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
  data, currency, markers = [], onMarkerClick, title = 'Metric Trends', headerRight, bare = false,
}: {
  data: TrendRow[]
  currency: string
  markers?: TrendMarker[]
  onMarkerClick?: (firstId: string) => void
  title?: string
  headerRight?: React.ReactNode
  // When true, render without the card chrome so it can be embedded in another card.
  bare?: boolean
}) {
  // Default to the two headline metrics most people watch.
  const [selected, setSelected] = useState<MetricKey[]>(['spend', 'roas'])
  // Indexed mode lets metrics on wildly different scales (Cost in millions vs
  // ROAS ~4x) share one axis by plotting each as % of its own period max.
  const [indexed, setIndexed] = useState(true)

  const toggle = (key: MetricKey) => {
    setSelected(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key])
  }

  // Per-metric max over the period, used to normalize when indexed.
  const maxes = useMemo(() => {
    const m: Record<string, number> = {}
    for (const def of METRICS) {
      m[def.key] = Math.max(0, ...data.map(d => Number(d[def.key]) || 0))
    }
    return m
  }, [data])

  // Build rows carrying both raw values (for the tooltip) and indexed values
  // (`${key}__idx`, what the lines plot when indexed mode is on).
  const chartData = useMemo(() => data.map(row => {
    const out: Record<string, number | string> = { date: row.date }
    for (const def of METRICS) {
      const raw = Number(row[def.key]) || 0
      out[def.key] = raw
      const max = maxes[def.key]
      out[`${def.key}__idx`] = max > 0 ? (raw / max) * 100 : 0
    }
    return out
  }), [data, maxes])

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
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={indexed}
              onChange={() => setIndexed(v => !v)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            Indexed (100 = period max)
          </label>
          {headerRight}
        </div>
      </div>

      {/* Metric toggles — tick any combination to overlay their trend lines. */}
      <div className="flex flex-wrap gap-2 mb-4">
        {METRICS.map(def => {
          const on = selected.includes(def.key)
          return (
            <button
              key={def.key}
              onClick={() => toggle(def.key)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                on ? 'border-gray-300 bg-gray-50 text-gray-800' : 'border-gray-200 text-gray-400 hover:text-gray-600'
              }`}
            >
              <span
                className="w-2.5 h-2.5 rounded-full"
                style={{ backgroundColor: on ? def.color : '#d1d5db' }}
              />
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
                    {selectedDefs.map(def => (
                      <div key={def.key} className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: def.color }} />
                        <span className="text-gray-600">{def.label}:</span>
                        <span className="font-medium text-gray-900">
                          {formatValue(Number(row[def.key]) || 0, def.kind, currency)}
                          {indexed && (
                            <span className="text-gray-400 font-normal ml-1">
                              ({Math.round(Number(row[`${def.key}__idx`]) || 0)})
                            </span>
                          )}
                        </span>
                      </div>
                    ))}
                  </div>
                )
              }}
            />
            <Legend />
            {selectedDefs.map(def => (
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
