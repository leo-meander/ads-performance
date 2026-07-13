'use client'

import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'

export type BranchBreakdownRow = {
  branch: string
  currency: string
  spend_vnd: number
  conversions: number
  leads: number
  revenue_vnd: number
}

const PIE_COLORS = ['#a68a64', '#b8a7d9', '#a3c982', '#7dc4c2', '#eb7373', '#f4b971']

export default function BranchPie({
  title, rows, valueKey, selectedBranches, onToggle, valueFormatter,
}: {
  title: string
  rows: BranchBreakdownRow[]
  valueKey: 'spend_vnd' | 'conversions'
  selectedBranches: string[]
  onToggle: (name: string) => void
  valueFormatter: (v: number) => string
}) {
  const data = rows
    .map((r) => ({ name: r.branch, value: Number(r[valueKey]) || 0 }))
    .filter((d) => d.value > 0)
  const hasFilter = selectedBranches.length > 0
  const total = data.reduce((s, d) => s + d.value, 0)

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <h2 className="text-sm font-semibold text-gray-700 mb-4">{title}</h2>
      {data.length === 0 ? (
        <p className="text-gray-400 text-sm text-center py-16">No data</p>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="40%"
              cy="50%"
              outerRadius={80}
              label={({ percent }) => `${((percent || 0) * 100).toFixed(1)}%`}
              labelLine={false}
              onClick={(d) => onToggle((d as { name: string }).name)}
              cursor="pointer"
            >
              {data.map((entry, i) => {
                const dim = hasFilter && !selectedBranches.includes(entry.name)
                return (
                  <Cell
                    key={entry.name}
                    fill={PIE_COLORS[i % PIE_COLORS.length]}
                    fillOpacity={dim ? 0.3 : 1}
                    stroke={selectedBranches.includes(entry.name) ? '#111827' : '#fff'}
                    strokeWidth={selectedBranches.includes(entry.name) ? 2 : 1}
                  />
                )
              })}
            </Pie>
            <Tooltip
              formatter={(v: number) => [
                `${valueFormatter(v)} (${total > 0 ? ((v / total) * 100).toFixed(1) : '0'}%)`,
                '',
              ]}
            />
            <Legend
              layout="vertical"
              verticalAlign="middle"
              align="right"
              iconType="circle"
              wrapperStyle={{ fontSize: 12, cursor: 'pointer' }}
              onClick={(e) => onToggle((e as { value: string }).value)}
            />
          </PieChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
