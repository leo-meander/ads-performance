'use client'

import { useEffect, useState } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type BudgetItem = {
  plan_id: string; name: string; branch: string; channel: string
  total_budget: number; allocated: number; spent: number
  pace_status: string; days_remaining: number; projected_spend: number; currency: string
}

type YearlyBranch = {
  branch: string; currency: string; yearly_budget: number; yearly_spent: number
  months: { month: number; month_name: string; budget: number; spent: number }[]
}

const BRANCHES_ORDER = ['Saigon', 'Osaka', '1948', 'Taipei', 'Oani', 'Bread']
const CHANNELS = ['meta', 'google', 'tiktok']
const CURRENCY_TO_VND: Record<string, number> = { VND: 1, TWD: 824.83, JPY: 165.01 }

const fmt = (n: number) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(n)

const paceColor = (status: string) => {
  if (status === 'On Track') return 'bg-green-100 text-green-700'
  if (status === 'Over') return 'bg-red-100 text-red-700'
  return 'bg-yellow-100 text-yellow-700'
}

const paceBgColor = (status: string) => {
  if (status === 'Over') return 'bg-red-500'
  if (status === 'Under') return 'bg-yellow-500'
  return 'bg-green-500'
}

const pctBadge = (pct: number) => {
  const cls = pct > 110 ? 'bg-red-100 text-red-700' : pct < 80 ? 'bg-yellow-100 text-yellow-700' : 'bg-green-100 text-green-700'
  return <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>{pct.toFixed(1)}%</span>
}

function BudgetCard({ label, spent, budget, currency, projected, daysRemaining, paceStatus }: {
  label: string; spent: number; budget: number; currency: string
  projected?: number; daysRemaining?: number; paceStatus?: string
}) {
  const pct = budget > 0 ? Math.min(100, (spent / budget) * 100) : 0
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        {paceStatus
          ? <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${paceColor(paceStatus)}`}>{paceStatus}</span>
          : pctBadge(pct)
        }
      </div>
      <div>
        <div className="flex justify-between text-xs mb-1">
          <span className="text-gray-500">Spent</span>
          <span className="font-medium text-gray-700">{fmt(spent)} / {fmt(budget)} {currency}</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div className={`h-2 rounded-full ${paceStatus ? paceBgColor(paceStatus) : (pct > 110 ? 'bg-red-500' : pct < 80 ? 'bg-yellow-500' : 'bg-green-500')}`}
            style={{ width: `${Math.min(pct, 100)}%` }} />
        </div>
      </div>
      {(projected !== undefined || daysRemaining !== undefined) && (
        <div className="flex justify-between text-xs text-gray-400">
          {projected !== undefined && <span>Projected: {fmt(projected)}</span>}
          {daysRemaining !== undefined && <span>{daysRemaining}d remaining</span>}
        </div>
      )}
    </div>
  )
}

export default function BudgetDashboard() {
  const [tab, setTab] = useState<'monthly' | 'yearly'>('monthly')
  const [month, setMonth] = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  })
  const [year, setYear] = useState(() => new Date().getFullYear())

  // Monthly state
  const [items, setItems] = useState<BudgetItem[]>([])
  const [loading, setLoading] = useState(true)

  // Yearly state
  const [yearlyData, setYearlyData] = useState<YearlyBranch[]>([])
  const [totalsVnd, setTotalsVnd] = useState<{
    yearly_budget: number; yearly_spent: number
    months: { month: number; month_name: string; budget: number; spent: number }[]
  } | null>(null)
  const [yearlyLoading, setYearlyLoading] = useState(true)

  // Branch filter
  const [selectedBranch, setSelectedBranch] = useState<string>('all')

  // Create form
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ name: '', branch: BRANCHES_ORDER[0], channel: CHANNELS[0], total_budget: '', currency: 'VND', notes: '' })
  const [creating, setCreating] = useState(false)

  const loadMonthly = () => {
    setLoading(true)
    fetch(`${API_BASE}/api/budget/dashboard?month=${month}`).then(r => r.json())
      .then(res => { if (res.success) setItems(res.data.items); setLoading(false) })
      .catch(() => setLoading(false))
  }

  const loadYearly = () => {
    setYearlyLoading(true)
    fetch(`${API_BASE}/api/budget/yearly?year=${year}`).then(r => r.json())
      .then(res => {
        if (res.success) { setYearlyData(res.data.branches); setTotalsVnd(res.data.totals_vnd) }
        setYearlyLoading(false)
      })
      .catch(() => setYearlyLoading(false))
  }

  useEffect(() => { if (tab === 'monthly') loadMonthly() }, [month, tab])
  useEffect(() => { if (tab === 'yearly') loadYearly() }, [year, tab])

  const handleCreate = async () => {
    if (!form.name || !form.total_budget) return
    setCreating(true)
    await fetch(`${API_BASE}/api/budget/plans`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...form, month: `${month}-01`, total_budget: parseFloat(form.total_budget) }),
    })
    setCreating(false); setShowCreate(false)
    setForm({ name: '', branch: BRANCHES_ORDER[0], channel: CHANNELS[0], total_budget: '', currency: 'VND', notes: '' })
    loadMonthly()
  }

  // Monthly: filter + group by branch
  const filteredItems = selectedBranch === 'all' ? items : items.filter(i => i.branch === selectedBranch)
  const branchGroups: Record<string, BudgetItem[]> = {}
  for (const item of filteredItems) {
    if (!branchGroups[item.branch]) branchGroups[item.branch] = []
    branchGroups[item.branch].push(item)
  }
  const sortedBranches = BRANCHES_ORDER.filter(b => branchGroups[b])

  // Yearly: filter by branch
  const filteredYearlyData = selectedBranch === 'all' ? yearlyData : yearlyData.filter(b => b.branch === selectedBranch)

  return (
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h1 className="text-2xl font-bold text-blue-600">Budget Planner</h1>
        <div className="flex gap-3 items-center">
          <select value={selectedBranch} onChange={e => setSelectedBranch(e.target.value)}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white">
            <option value="all">All Branches</option>
            {BRANCHES_ORDER.map(b => <option key={b} value={b}>{b}</option>)}
          </select>
          {tab === 'monthly' && (
            <>
              <input type="month" value={month} onChange={e => setMonth(e.target.value)}
                className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <button onClick={() => setShowCreate(!showCreate)}
                className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700">+ New Plan</button>
            </>
          )}
          {tab === 'yearly' && (
            <select value={year} onChange={e => setYear(Number(e.target.value))}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {[2025, 2026, 2027].map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-100 rounded-lg p-1 w-fit">
        {(['monthly', 'yearly'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              tab === t ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t === 'monthly' ? 'Monthly' : 'Yearly'}
          </button>
        ))}
      </div>

      {/* Create Plan Form */}
      {showCreate && tab === 'monthly' && (
        <div className="bg-white border rounded-xl p-4 space-y-3 mb-6">
          <h3 className="font-semibold text-gray-900">Create Budget Plan</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <input placeholder="Plan name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
              className="border rounded-lg px-3 py-2 text-sm" />
            <select value={form.branch} onChange={e => setForm({ ...form, branch: e.target.value })}
              className="border rounded-lg px-3 py-2 text-sm bg-white">
              {BRANCHES_ORDER.map(b => <option key={b} value={b}>{b}</option>)}
            </select>
            <select value={form.channel} onChange={e => setForm({ ...form, channel: e.target.value })}
              className="border rounded-lg px-3 py-2 text-sm bg-white">
              {CHANNELS.map(c => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
            </select>
            <input type="number" placeholder="Total budget" value={form.total_budget}
              onChange={e => setForm({ ...form, total_budget: e.target.value })}
              className="border rounded-lg px-3 py-2 text-sm" />
            <select value={form.currency} onChange={e => setForm({ ...form, currency: e.target.value })}
              className="border rounded-lg px-3 py-2 text-sm bg-white">
              <option value="VND">VND</option><option value="USD">USD</option>
              <option value="JPY">JPY</option><option value="TWD">TWD</option>
            </select>
            <input placeholder="Notes (optional)" value={form.notes}
              onChange={e => setForm({ ...form, notes: e.target.value })}
              className="border rounded-lg px-3 py-2 text-sm" />
          </div>
          <div className="flex gap-2">
            <button onClick={handleCreate} disabled={creating}
              className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {creating ? 'Creating...' : 'Create Plan'}
            </button>
            <button onClick={() => setShowCreate(false)}
              className="border px-4 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50">Cancel</button>
          </div>
        </div>
      )}

      {/* ======================== MONTHLY TAB ======================== */}
      {tab === 'monthly' && (
        loading ? (
          <div className="flex items-center justify-center h-64"><div className="text-gray-500">Loading...</div></div>
        ) : (
          <div className="space-y-6">
            {/* All Branches Total (converted to VND) — only show when viewing all */}
            {selectedBranch === 'all' && filteredItems.length > 0 && (() => {
              const toVnd = (amount: number, cur: string) => amount * (CURRENCY_TO_VND[cur] || 1)
              const gBudget = filteredItems.reduce((s, i) => s + toVnd(i.total_budget, i.currency), 0)
              const gSpent = filteredItems.reduce((s, i) => s + toVnd(i.spent, i.currency), 0)
              const gProjected = filteredItems.reduce((s, i) => s + toVnd(i.projected_spend, i.currency), 0)
              const daysRem = filteredItems[0]?.days_remaining ?? 0
              return (
                <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                  <div className="px-6 py-4 border-b"><h2 className="text-sm font-semibold text-gray-900">All Branches</h2></div>
                  <div className="p-4">
                    <BudgetCard label="Total" spent={gSpent} budget={gBudget} currency="VND" projected={gProjected} daysRemaining={daysRem} />
                  </div>
                </div>
              )
            })()}

            {/* Per Branch */}
            {sortedBranches.map(branch => {
              const bi = branchGroups[branch]
              const tBudget = bi.reduce((s, i) => s + i.total_budget, 0)
              const tSpent = bi.reduce((s, i) => s + i.spent, 0)
              const tProjected = bi.reduce((s, i) => s + i.projected_spend, 0)
              const cur = bi[0]?.currency || 'VND'
              const dRem = bi[0]?.days_remaining ?? 0

              return (
                <div key={branch} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                  <div className="px-6 py-4 border-b"><h2 className="text-sm font-semibold text-gray-900">{branch}</h2></div>
                  <div className="px-4 pt-4 pb-2 border-b border-gray-100">
                    <BudgetCard label="Total" spent={tSpent} budget={tBudget} currency={cur} projected={tProjected} daysRemaining={dRem} />
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 divide-x divide-y divide-gray-100">
                    {bi.map(item => (
                      <div key={item.plan_id} className="p-4">
                        <BudgetCard label={item.channel.charAt(0).toUpperCase() + item.channel.slice(1)}
                          spent={item.spent} budget={item.total_budget} currency={item.currency}
                          projected={item.projected_spend} daysRemaining={item.days_remaining} paceStatus={item.pace_status} />
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}

            {filteredItems.length === 0 && (
              <div className="text-center py-12 text-gray-400">No budget plans for {month}{selectedBranch !== 'all' ? ` (${selectedBranch})` : ''}.</div>
            )}
          </div>
        )
      )}

      {/* ======================== YEARLY TAB ======================== */}
      {tab === 'yearly' && (
        yearlyLoading ? (
          <div className="flex items-center justify-center h-64"><div className="text-gray-500">Loading...</div></div>
        ) : (
          <div className="space-y-6">
            {/* Grand total in VND — only show when viewing all */}
            {selectedBranch === 'all' && totalsVnd && (() => {
              const pct = totalsVnd.yearly_budget > 0 ? (totalsVnd.yearly_spent / totalsVnd.yearly_budget * 100) : 0
              return (
                <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                  <div className="px-6 py-4 border-b flex items-center justify-between">
                    <div>
                      <h2 className="text-sm font-semibold text-gray-900">All Branches — {year}</h2>
                      <p className="text-xs text-gray-400 mt-0.5">{fmt(totalsVnd.yearly_spent)} / {fmt(totalsVnd.yearly_budget)} VND</p>
                    </div>
                    {pctBadge(pct)}
                  </div>
                  <div className="px-6 py-3 border-b border-gray-100">
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div className={`h-2 rounded-full ${pct > 110 ? 'bg-red-500' : pct < 80 ? 'bg-yellow-500' : 'bg-green-500'}`}
                        style={{ width: `${Math.min(pct, 100)}%` }} />
                    </div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-gray-100">
                          <th className="text-left py-2 px-4 text-gray-500 font-medium w-16">Month</th>
                          <th className="text-right py-2 px-4 text-gray-500 font-medium">Allocate (VND)</th>
                          <th className="text-right py-2 px-4 text-gray-500 font-medium">Actual Spend (VND)</th>
                          <th className="text-right py-2 px-4 text-gray-500 font-medium">Remaining</th>
                          <th className="text-right py-2 px-4 text-gray-500 font-medium w-20">%</th>
                          <th className="py-2 px-4 w-32"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {totalsVnd.months.map(m => {
                          const hasBudget = m.budget > 0
                          const mPct = m.budget > 0 ? (m.spent / m.budget * 100) : 0
                          const remaining = m.budget - m.spent
                          const isCurrent = m.month === new Date().getMonth() + 1 && year === new Date().getFullYear()
                          return (
                            <tr key={m.month} className={`border-b border-gray-50 ${isCurrent ? 'bg-blue-50' : 'hover:bg-gray-50'} ${!hasBudget && m.spent === 0 ? 'text-gray-300' : ''}`}>
                              <td className="py-2 px-4 font-medium">{m.month_name}</td>
                              <td className="py-2 px-4 text-right">{hasBudget ? fmt(m.budget) : '-'}</td>
                              <td className="py-2 px-4 text-right">{m.spent > 0 ? fmt(m.spent) : '-'}</td>
                              <td className={`py-2 px-4 text-right ${remaining < 0 ? 'text-red-600 font-medium' : ''}`}>{hasBudget ? fmt(remaining) : '-'}</td>
                              <td className="py-2 px-4 text-right">
                                {hasBudget ? <span className={`text-xs font-medium ${mPct > 100 ? 'text-red-600' : mPct > 80 ? 'text-yellow-600' : 'text-gray-500'}`}>{mPct.toFixed(1)}%</span> : '-'}
                              </td>
                              <td className="py-2 px-4">
                                {hasBudget && (
                                  <div className="w-full bg-gray-200 rounded-full h-1.5">
                                    <div className={`h-1.5 rounded-full ${mPct > 100 ? 'bg-red-500' : mPct > 80 ? 'bg-yellow-500' : 'bg-green-500'}`}
                                      style={{ width: `${Math.min(mPct, 100)}%` }} />
                                  </div>
                                )}
                              </td>
                            </tr>
                          )
                        })}
                        <tr className="bg-gray-50 font-medium">
                          <td className="py-2 px-4">Total</td>
                          <td className="py-2 px-4 text-right">{fmt(totalsVnd.yearly_budget)}</td>
                          <td className="py-2 px-4 text-right">{fmt(totalsVnd.yearly_spent)}</td>
                          <td className={`py-2 px-4 text-right ${totalsVnd.yearly_budget - totalsVnd.yearly_spent < 0 ? 'text-red-600' : ''}`}>
                            {fmt(totalsVnd.yearly_budget - totalsVnd.yearly_spent)}
                          </td>
                          <td className="py-2 px-4 text-right text-xs">{pct.toFixed(1)}%</td>
                          <td className="py-2 px-4"></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              )
            })()}

            {/* Per branch yearly table */}
            {filteredYearlyData.map(branch => {
              const pct = branch.yearly_budget > 0 ? (branch.yearly_spent / branch.yearly_budget * 100) : 0
              return (
                <div key={branch.branch} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                  <div className="px-6 py-4 border-b flex items-center justify-between">
                    <div>
                      <h2 className="text-sm font-semibold text-gray-900">{branch.branch}</h2>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {fmt(branch.yearly_spent)} / {fmt(branch.yearly_budget)} {branch.currency}
                      </p>
                    </div>
                    {pctBadge(pct)}
                  </div>
                  {/* Progress bar */}
                  <div className="px-6 py-3 border-b border-gray-100">
                    <div className="w-full bg-gray-200 rounded-full h-2">
                      <div className={`h-2 rounded-full ${pct > 110 ? 'bg-red-500' : pct < 80 ? 'bg-yellow-500' : 'bg-green-500'}`}
                        style={{ width: `${Math.min(pct, 100)}%` }} />
                    </div>
                  </div>
                  {/* Monthly table */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-gray-100">
                          <th className="text-left py-2 px-4 text-gray-500 font-medium w-16">Month</th>
                          <th className="text-right py-2 px-4 text-gray-500 font-medium">Allocate</th>
                          <th className="text-right py-2 px-4 text-gray-500 font-medium">Actual Spend</th>
                          <th className="text-right py-2 px-4 text-gray-500 font-medium">Remaining</th>
                          <th className="text-right py-2 px-4 text-gray-500 font-medium w-20">%</th>
                          <th className="py-2 px-4 w-32"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {branch.months.map(m => {
                          const hasBudget = m.budget > 0
                          const mPct = m.budget > 0 ? (m.spent / m.budget * 100) : 0
                          const remaining = m.budget - m.spent
                          const isCurrentMonth = m.month === new Date().getMonth() + 1 && year === new Date().getFullYear()
                          return (
                            <tr key={m.month} className={`border-b border-gray-50 ${isCurrentMonth ? 'bg-blue-50' : 'hover:bg-gray-50'} ${!hasBudget && m.spent === 0 ? 'text-gray-300' : ''}`}>
                              <td className="py-2 px-4 font-medium">{m.month_name}</td>
                              <td className="py-2 px-4 text-right">{hasBudget ? fmt(m.budget) : '-'}</td>
                              <td className="py-2 px-4 text-right">{m.spent > 0 ? fmt(m.spent) : '-'}</td>
                              <td className={`py-2 px-4 text-right ${remaining < 0 ? 'text-red-600 font-medium' : ''}`}>
                                {hasBudget ? fmt(remaining) : '-'}
                              </td>
                              <td className="py-2 px-4 text-right">
                                {hasBudget ? (
                                  <span className={`text-xs font-medium ${mPct > 100 ? 'text-red-600' : mPct > 80 ? 'text-yellow-600' : 'text-gray-500'}`}>
                                    {mPct.toFixed(1)}%
                                  </span>
                                ) : '-'}
                              </td>
                              <td className="py-2 px-4">
                                {hasBudget && (
                                  <div className="w-full bg-gray-200 rounded-full h-1.5">
                                    <div className={`h-1.5 rounded-full ${mPct > 100 ? 'bg-red-500' : mPct > 80 ? 'bg-yellow-500' : 'bg-green-500'}`}
                                      style={{ width: `${Math.min(mPct, 100)}%` }} />
                                  </div>
                                )}
                              </td>
                            </tr>
                          )
                        })}
                        {/* Yearly total row */}
                        <tr className="bg-gray-50 font-medium">
                          <td className="py-2 px-4">Total</td>
                          <td className="py-2 px-4 text-right">{fmt(branch.yearly_budget)}</td>
                          <td className="py-2 px-4 text-right">{fmt(branch.yearly_spent)}</td>
                          <td className={`py-2 px-4 text-right ${branch.yearly_budget - branch.yearly_spent < 0 ? 'text-red-600' : ''}`}>
                            {fmt(branch.yearly_budget - branch.yearly_spent)}
                          </td>
                          <td className="py-2 px-4 text-right text-xs">{pct.toFixed(1)}%</td>
                          <td className="py-2 px-4"></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              )
            })}

            {filteredYearlyData.length === 0 && (
              <div className="text-center py-12 text-gray-400">No budget data for {year}{selectedBranch !== 'all' ? ` (${selectedBranch})` : ''}.</div>
            )}
          </div>
        )
      )}
    </div>
  )
}
