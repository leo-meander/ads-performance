'use client'

import { useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts'

// Daily metric row shared by the Google PMax + Search detail pages. ctr/cpa
// only exist on Search; they're optional so the same chart serves both.
export interface GoogleMetricRow {
  date: string
  spend: number
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  roas: number
  ctr?: number
  cpa?: number | null
}

type MetricKind = 'money' | 'x' | 'pct' | 'num'
type MetricKey = 'spend' | 'revenue' | 'roas' | 'clicks' | 'impressions' | 'conversions' | 'ctr' | 'cpa'
type MetricDef = { key: MetricKey; label: string; color: string; kind: MetricKind }

const BASE_METRICS: MetricDef[] = [
  { key: 'spend', label: 'Spend', color: '#ef4444', kind: 'money' },
  { key: 'revenue', label: 'Revenue', color: '#10b981', kind: 'money' },
  { key: 'roas', label: 'ROAS', color: '#3b82f6', kind: 'x' },
  { key: 'clicks', label: 'Clicks', color: '#f59e0b', kind: 'num' },
  { key: 'impressions', label: 'Impressions', color: '#8b5cf6', kind: 'num' },
  { key: 'conversions', label: 'Conv.', color: '#0ea5e9', kind: 'num' },
]
const CTR_METRIC: MetricDef = { key: 'ctr', label: 'CTR', color: '#14b8a6', kind: 'pct' }
const CPA_METRIC: MetricDef = { key: 'cpa', label: 'CPA', color: '#ec4899', kind: 'money' }

const fmtNum = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })

function formatValue(v: number, kind: MetricKind): string {
  if (v === null || v === undefined) return '--'
  switch (kind) {
    case 'money': return `$${fmtNum(v)}`
    case 'x': return `${v.toFixed(2)}x`
    case 'pct': return `${v.toFixed(2)}%`
    case 'num': return fmtNum(v)
  }
}

export default function GoogleDailyChart({ metrics }: { metrics: GoogleMetricRow[] }) {
  // Search rows carry ctr/cpa; PMax rows don't — only offer those toggles when present.
  const hasCtr = metrics.some(m => m.ctr !== undefined && m.ctr !== null)
  const hasCpa = metrics.some(m => m.cpa !== undefined && m.cpa !== null)
  const METRICS = useMemo(() => {
    const list = [...BASE_METRICS]
    if (hasCtr) list.push(CTR_METRIC)
    if (hasCpa) list.push(CPA_METRIC)
    return list
  }, [hasCtr, hasCpa])

  const [view, setView] = useState<'chart' | 'table'>('chart')
  // Default to the two headline metrics most people watch.
  const [selected, setSelected] = useState<MetricKey[]>(['spend', 'roas'])
  // Indexed mode lets metrics on wildly different scales (Spend in thousands vs
  // ROAS ~6x) share one axis by plotting each as % of its own period max.
  const [indexed, setIndexed] = useState(true)

  const toggle = (key: MetricKey) => {
    setSelected(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key])
  }

  // Per-metric max over the period, used to normalize when indexed.
  const maxes = useMemo(() => {
    const m: Record<string, number> = {}
    for (const def of METRICS) {
      m[def.key] = Math.max(0, ...metrics.map(d => Number(d[def.key]) || 0))
    }
    return m
  }, [metrics, METRICS])

  // Build rows carrying both raw values (for the tooltip) and indexed values
  // (`${key}__idx`, what the lines plot when indexed mode is on).
  const chartData = useMemo(() => metrics.map(row => {
    const out: Record<string, number | string> = { date: row.date }
    for (const def of METRICS) {
      const raw = Number(row[def.key]) || 0
      out[def.key] = raw
      const max = maxes[def.key]
      out[`${def.key}__idx`] = max > 0 ? (raw / max) * 100 : 0
    }
    return out
  }), [metrics, maxes, METRICS])

  const selectedDefs = METRICS.filter(d => selected.includes(d.key))

  return (
    <div className="bg-white rounded-xl border border-gray-200">
      <div className="p-5 border-b border-gray-100 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold text-gray-900">Daily Metrics</h2>
        <div className="flex items-center gap-3">
          {view === 'chart' && (
            <label className="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={indexed}
                onChange={() => setIndexed(v => !v)}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              Indexed (100 = period max)
            </label>
          )}
          {/* Chart / Table view switch — keep the exact numbers one click away. */}
          <div className="inline-flex rounded-lg border border-gray-200 p-0.5">
            {(['chart', 'table'] as const).map(v => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-2.5 py-1 text-xs font-medium rounded-md capitalize transition-colors ${
                  view === v ? 'bg-gray-900 text-white' : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {v}
              </button>
            ))}
          </div>
        </div>
      </div>

      {view === 'chart' ? (
        <div className="p-5">
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
                              {formatValue(Number(row[def.key]) || 0, def.kind)}
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
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-5 py-3 text-gray-500 font-medium">Date</th>
                <th className="text-right px-5 py-3 text-gray-500 font-medium">Spend</th>
                <th className="text-right px-5 py-3 text-gray-500 font-medium">Imp.</th>
                <th className="text-right px-5 py-3 text-gray-500 font-medium">Clicks</th>
                {hasCtr && <th className="text-right px-5 py-3 text-gray-500 font-medium">CTR</th>}
                <th className="text-right px-5 py-3 text-gray-500 font-medium">Conv.</th>
                <th className="text-right px-5 py-3 text-gray-500 font-medium">Revenue</th>
                <th className="text-right px-5 py-3 text-gray-500 font-medium">ROAS</th>
                {hasCpa && <th className="text-right px-5 py-3 text-gray-500 font-medium">CPA</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {metrics.map(m => (
                <tr key={m.date} className="hover:bg-gray-50">
                  <td className="px-5 py-3 text-gray-700">{m.date}</td>
                  <td className="px-5 py-3 text-right">${fmtNum(m.spend)}</td>
                  <td className="px-5 py-3 text-right">{fmtNum(m.impressions)}</td>
                  <td className="px-5 py-3 text-right">{fmtNum(m.clicks)}</td>
                  {hasCtr && <td className="px-5 py-3 text-right">{(m.ctr ?? 0).toFixed(2)}%</td>}
                  <td className="px-5 py-3 text-right">{m.conversions}</td>
                  <td className="px-5 py-3 text-right">${fmtNum(m.revenue)}</td>
                  <td className="px-5 py-3 text-right font-medium">{m.roas.toFixed(2)}x</td>
                  {hasCpa && <td className="px-5 py-3 text-right">{m.cpa ? `$${fmtNum(m.cpa)}` : '-'}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
