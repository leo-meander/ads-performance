'use client'

import { useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import type { BranchBreakdownRow } from './BranchPie'
import { fmtMoney } from './dashboardUtils'

// Same palette as BranchPie so a branch keeps its colour across the dashboard.
const BRANCH_COLORS = ['#a68a64', '#b8a7d9', '#a3c982', '#7dc4c2', '#eb7373', '#f4b971']

type CmpMetric = 'roas' | 'cpa' | 'ctr'

const METRIC_DEFS: Record<CmpMetric, { label: string; kind: 'x' | 'money' | 'pct'; inverse: boolean }> = {
  // CPA is derived from VND-converted spend, so it's comparable across branches.
  roas: { label: 'ROAS', kind: 'x', inverse: false },
  cpa: { label: 'CPA', kind: 'money', inverse: true },
  ctr: { label: 'CTR', kind: 'pct', inverse: false },
}

function fmt(v: number, kind: 'x' | 'money' | 'pct'): string {
  switch (kind) {
    case 'x': return `${v.toFixed(2)}x`
    case 'money': return fmtMoney(v, 'VND')
    case 'pct': return `${v.toFixed(2)}%`
  }
}

type Row = BranchBreakdownRow & { roas: number; cpa: number; ctr: number }

export default function BranchComparisonChart({ rows }: { rows: Row[] }) {
  const [metric, setMetric] = useState<CmpMetric>('roas')
  const def = METRIC_DEFS[metric]

  // Sort best-first for the active metric (low CPA is best; high ROAS/CTR best).
  const data = rows
    .map(r => ({ branch: r.branch, value: Number(r[metric]) || 0 }))
    .filter(d => d.value > 0)
    .sort((a, b) => def.inverse ? a.value - b.value : b.value - a.value)

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-sm font-semibold text-gray-700">
          Branch Comparison
          {def.kind === 'money' && <span className="text-gray-400 font-normal ml-1">(VND)</span>}
        </h2>
        <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5">
          {(Object.keys(METRIC_DEFS) as CmpMetric[]).map(m => (
            <button
              key={m}
              onClick={() => setMetric(m)}
              className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                metric === m ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {METRIC_DEFS[m].label}
            </button>
          ))}
        </div>
      </div>

      {data.length === 0 ? (
        <p className="text-gray-400 text-sm text-center py-20">No data</p>
      ) : (
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
            <XAxis dataKey="branch" tick={{ fontSize: 11 }} interval={0} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmt(v, def.kind)} width={70} />
            <Tooltip
              cursor={{ fill: '#f9fafb' }}
              formatter={(v: number) => [fmt(v, def.kind), def.label]}
            />
            <Bar dataKey="value" name={def.label} radius={[4, 4, 0, 0]}>
              {data.map((entry, i) => (
                <Cell key={entry.branch} fill={BRANCH_COLORS[i % BRANCH_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
