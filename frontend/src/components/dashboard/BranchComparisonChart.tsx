'use client'

import { useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell, LabelList,
} from 'recharts'
import type { BranchBreakdownRow, BranchPrevSnapshot } from './BranchPie'
import { fmtMoney, fmtNum } from './dashboardUtils'

type CmpMetric = 'roas' | 'cpa' | 'cpl' | 'ctr'

const SALE_METRICS: CmpMetric[] = ['roas', 'cpa', 'ctr']
const LEAD_METRICS: CmpMetric[] = ['roas', 'cpl', 'ctr']

const METRIC_DEFS: Record<CmpMetric, { label: string; kind: 'x' | 'money' | 'pct' | 'num'; inverse: boolean }> = {
  roas: { label: 'ROAS', kind: 'x', inverse: false },
  cpa:  { label: 'CPA',  kind: 'money', inverse: true },
  cpl:  { label: 'CPL',  kind: 'money', inverse: true },
  ctr:  { label: 'CTR',  kind: 'pct', inverse: false },
}

// Moves smaller than this are noise, not a trend — they stay neutral grey.
const FLAT_BAND = 0.05

const TREND_COLORS = { down: '#eb7373', up: '#7fae5a', flat: '#c7c9cf' }

function fmt(v: number, kind: 'x' | 'money' | 'pct' | 'num'): string {
  switch (kind) {
    case 'x':     return `${v.toFixed(2)}x`
    case 'money': return fmtMoney(v, 'VND')
    case 'pct':   return `${v.toFixed(2)}%`
    case 'num':   return fmtNum(v)
  }
}

function fmtDelta(d: number): string {
  const pct = d * 100
  return `${pct > 0 ? '+' : ''}${Math.abs(pct) >= 10 ? pct.toFixed(0) : pct.toFixed(1)}%`
}

type Row = BranchBreakdownRow & { roas: number; cpa: number; ctr: number }

type Point = {
  branch: string
  value: number
  prevValue: number | null
  /** Period-over-period move, null when there is nothing to compare against. */
  delta: number | null
  /** 'down' = the branch got WORSE on this metric (direction-aware). */
  trend: 'down' | 'up' | 'flat'
}

export default function BranchComparisonChart({ rows, campaignType, prevPeriodLabel }: {
  rows: Row[]
  campaignType?: string
  prevPeriodLabel?: string
}) {
  const isLead = campaignType === 'lead'
  const availableMetrics = isLead ? LEAD_METRICS : SALE_METRICS
  const [metric, setMetric] = useState<CmpMetric>('roas')

  // Reset to roas if current metric not available in this mode
  const activeMetric = availableMetrics.includes(metric) ? metric : 'roas'
  const def = METRIC_DEFS[activeMetric]

  // Works on either the live row or its previous-period snapshot — CPL has no
  // server-side column, so it is derived from spend/leads on both sides alike.
  const getValue = (r: Row | BranchPrevSnapshot): number => {
    if (activeMetric === 'cpl') {
      const leads = r.leads || 0
      return leads > 0 ? (r.spend_vnd || 0) / leads : 0
    }
    return Number((r as Record<string, unknown>)[activeMetric]) || 0
  }

  const data: Point[] = rows
    .map((r) => {
      const value = getValue(r)
      const prevValue = r.prev ? getValue(r.prev) : null
      const delta = prevValue && prevValue > 0 ? (value - prevValue) / prevValue : null
      let trend: Point['trend'] = 'flat'
      if (delta !== null && Math.abs(delta) >= FLAT_BAND) {
        const worse = def.inverse ? delta > 0 : delta < 0
        trend = worse ? 'down' : 'up'
      }
      return { branch: r.branch, value, prevValue, delta, trend }
    })
    // A cost metric at 0 means "no conversions", not "cheapest" — charting it
    // would read as the best bar. ROAS/CTR at 0 after a real previous period is
    // a genuine collapse, so that one stays in.
    .filter(d => d.value > 0 || (!def.inverse && (d.prevValue ?? 0) > 0))
    .sort((a, b) => def.inverse ? a.value - b.value : b.value - a.value)

  const declining = data
    .filter(d => d.trend === 'down')
    .sort((a, b) => Math.abs(b.delta ?? 0) - Math.abs(a.delta ?? 0))
  const comparable = data.some(d => d.delta !== null)

  const renderDelta = (props: unknown) => {
    const { x, y, width, index } = props as { x: number; y: number; width: number; index: number }
    const point = data[index]
    if (!point || point.delta === null || point.trend === 'flat') return null
    return (
      <text
        x={x + width / 2}
        y={y - 6}
        textAnchor="middle"
        fontSize={11}
        fontWeight={600}
        fill={TREND_COLORS[point.trend]}
      >
        {point.delta < 0 ? '▼' : '▲'} {fmtDelta(point.delta)}
      </text>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
        <h2 className="text-sm font-semibold text-gray-700">
          Branch Comparison
          {def.kind === 'money' && <span className="text-gray-400 font-normal ml-1">(VND)</span>}
        </h2>
        <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5">
          {availableMetrics.map(m => (
            <button
              key={m}
              onClick={() => setMetric(m)}
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                activeMetric === m ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {METRIC_DEFS[m].label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mb-3 text-[11px] text-gray-400">
        <span>Bar colour = {def.label} vs previous period{prevPeriodLabel ? ` (${prevPeriodLabel})` : ''}</span>
        <span className="inline-flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm" style={{ background: TREND_COLORS.down }} /> declining
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm" style={{ background: TREND_COLORS.up }} /> improving
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm" style={{ background: TREND_COLORS.flat }} /> flat (±5%) / no history
        </span>
      </div>

      {declining.length > 0 ? (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
          <span className="text-xs font-semibold text-red-700">
            {declining.length} branch{declining.length > 1 ? 'es' : ''} declining on {def.label}:
          </span>
          {declining.map(d => (
            <span key={d.branch} className="rounded bg-white px-1.5 py-0.5 text-xs font-medium text-red-600">
              {d.branch} {d.delta !== null && fmtDelta(d.delta)}
              <span className="text-gray-400 font-normal">
                {' '}({fmt(d.prevValue ?? 0, def.kind)} → {fmt(d.value, def.kind)})
              </span>
            </span>
          ))}
        </div>
      ) : comparable ? (
        <div className="mb-4 rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-xs font-medium text-green-700">
          No branch is declining on {def.label} vs the previous period.
        </div>
      ) : (
        <div className="mb-4 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-500">
          No previous-period data in range — trend comparison unavailable.
        </div>
      )}

      {data.length === 0 ? (
        <p className="text-gray-400 text-sm text-center py-20">No data</p>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data} margin={{ top: 24, right: 8, left: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
            <XAxis dataKey="branch" tick={{ fontSize: 11 }} interval={0} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v, def.kind)} width={70} />
            <Tooltip
              cursor={{ fill: '#f9fafb' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null
                const p = payload[0].payload as Point
                return (
                  <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs shadow-sm">
                    <p className="font-semibold text-gray-800 mb-1">{p.branch}</p>
                    <p className="text-gray-600">
                      {def.label}: <span className="font-medium text-gray-900">{fmt(p.value, def.kind)}</span>
                    </p>
                    {p.prevValue !== null && (
                      <p className="text-gray-600">Previous: {fmt(p.prevValue, def.kind)}</p>
                    )}
                    {p.delta !== null ? (
                      <p className="font-medium mt-0.5" style={{ color: TREND_COLORS[p.trend] }}>
                        {p.delta < 0 ? '▼' : '▲'} {fmtDelta(p.delta)}
                        {p.trend === 'down' ? ' — declining' : p.trend === 'up' ? ' — improving' : ' — flat'}
                      </p>
                    ) : (
                      <p className="text-gray-400 mt-0.5">No previous-period data</p>
                    )}
                  </div>
                )
              }}
            />
            <Bar dataKey="value" name={def.label} radius={[4, 4, 0, 0]}>
              {data.map((entry) => (
                <Cell key={entry.branch} fill={TREND_COLORS[entry.trend]} />
              ))}
              <LabelList dataKey="value" content={renderDelta} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
