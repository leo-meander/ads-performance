'use client'

import { useEffect, useState } from 'react'
import { useAuth } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type BudgetItem = {
  plan_id: string; name: string; branch: string; channel: string
  total_budget: number; allocated: number; spent: number
  pace_status: string; days_remaining: number; projected_spend: number; currency: string
  notes?: string | null
}

type MonthNote = { channel: string; text: string }

type YearlyBranch = {
  branch: string; currency: string; yearly_budget: number; yearly_spent: number
  months: { month: number; month_name: string; budget: number; spent: number; notes?: MonthNote[] }[]
}

type SplitMonth = {
  branch: string; year: number; month: number
  total_vnd: number; total_native: number; currency: string
  channel_pct: Record<string, number>
  overflow_note: string | null
  pct_sum: number
  updated_at?: string | null
}

type YearlyPlan = {
  branch: string; year: number; currency: string
  yearly_total_vnd: number; yearly_total_native: number
  month_pct: Record<string, number>
  months: { month: number; month_name: string; pct: number; budget_vnd: number; budget_native: number }[]
  pct_sum: number
  updated_at?: string | null
}

const BRANCHES_ORDER = ['Saigon', 'Osaka', '1948', 'Taipei', 'Oani', 'Bread']
const CHANNELS = ['meta', 'google', 'tiktok']
const MONTH_NAMES = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
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

function ChannelNoteEditor({
  planId, initialNote, isOver, editable, overspend, currency, onSaved, channelLabel,
}: {
  planId: string; initialNote: string | null; isOver: boolean; editable: boolean
  overspend: number; currency: string; onSaved: (note: string | null) => void
  channelLabel?: string
}) {
  const [note, setNote] = useState(initialNote || '')
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<'ok' | 'err' | null>(null)
  useEffect(() => { setNote(initialNote || '') }, [initialNote])
  useEffect(() => { setStatus(null) }, [note])

  const dirty = note !== (initialNote || '')

  const save = async () => {
    setSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/budget/plans/${planId}/notes`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ notes: note || null }),
      }).then(r => r.json())
      if (res.success) {
        setStatus('ok')
        onSaved(note || null)
      } else {
        setStatus('err')
      }
    } catch {
      setStatus('err')
    } finally {
      setSaving(false)
    }
  }

  if (!isOver && !initialNote) return null

  return (
    <div className="border-t border-gray-100 pt-2 mt-2 space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className={`font-medium ${isOver ? 'text-red-600' : 'text-gray-500'}`}>
          {isOver
            ? `${channelLabel ? `${channelLabel}: ` : ''}Over ${fmt(overspend)} ${currency} — offset from?`
            : `${channelLabel ? `${channelLabel} note` : 'Note'}`}
        </span>
        {dirty && editable && (
          <button onClick={save} disabled={saving}
            className={`text-xs px-2 py-0.5 rounded font-medium ${
              status === 'err'
                ? 'bg-red-100 text-red-700'
                : 'bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50'
            }`}>
            {saving ? '...' : status === 'err' ? 'Retry' : 'Save'}
          </button>
        )}
        {!dirty && status === 'ok' && (
          <span className="text-xs text-green-600">Saved</span>
        )}
      </div>
      <input type="text" value={note} disabled={!editable}
        onChange={e => setNote(e.target.value)}
        placeholder={isOver ? 'e.g. KOL budget, offline event…' : ''}
        className="w-full border rounded px-2 py-1 text-xs disabled:bg-gray-50 disabled:text-gray-400" />
    </div>
  )
}

export default function BudgetDashboard() {
  const { branchesForSection } = useAuth()
  const viewableBranches = branchesForSection('budget')
  const editableBranches = branchesForSection('budget', 'edit')
  const filterBranches = BRANCHES_ORDER.filter(b => viewableBranches.includes(b))
  // Yearly is the entry point (input) — Splits divides each month — Monthly is status
  const [tab, setTab] = useState<'yearly' | 'splits' | 'monthly'>('yearly')
  const [month, setMonth] = useState(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
  })
  const [year, setYear] = useState(() => new Date().getFullYear())

  // Monthly state
  const [items, setItems] = useState<BudgetItem[]>([])
  const [loading, setLoading] = useState(true)

  // Yearly state — read-only summary
  const [yearlyData, setYearlyData] = useState<YearlyBranch[]>([])
  const [totalsVnd, setTotalsVnd] = useState<{
    yearly_budget: number; yearly_spent: number
    months: { month: number; month_name: string; budget: number; spent: number }[]
  } | null>(null)
  const [yearlyLoading, setYearlyLoading] = useState(true)

  // Yearly editor state — yearly_total_vnd + 12 month %
  const [yearlyEditBranch, setYearlyEditBranch] = useState<string>(BRANCHES_ORDER[0])
  const [yearlyPlan, setYearlyPlan] = useState<YearlyPlan | null>(null)
  const [yearlyPlanLoading, setYearlyPlanLoading] = useState(false)
  const [yearlySaving, setYearlySaving] = useState(false)
  const [yearlySaveStatus, setYearlySaveStatus] = useState<'ok' | 'err' | null>(null)
  const yearlyEditable = editableBranches.includes(yearlyEditBranch)

  // Branch filter (summary view)
  const [selectedBranch, setSelectedBranch] = useState<string>('all')

  // Splits state — per-(branch, month) channel %
  const [splitBranch, setSplitBranch] = useState<string>(BRANCHES_ORDER[0])
  const [splitRows, setSplitRows] = useState<SplitMonth[]>([])
  const [splitsLoading, setSplitsLoading] = useState(false)
  const [savingMonth, setSavingMonth] = useState<number | null>(null)
  const [saveStatus, setSaveStatus] = useState<Record<number, 'ok' | 'err' | null>>({})
  const splitEditable = editableBranches.includes(splitBranch)

  const loadMonthly = () => {
    setLoading(true)
    fetch(`${API_BASE}/api/budget/dashboard?month=${month}`, { credentials: 'include' }).then(r => r.json())
      .then(res => { if (res.success) setItems(res.data.items); setLoading(false) })
      .catch(() => setLoading(false))
  }

  const loadYearly = () => {
    setYearlyLoading(true)
    fetch(`${API_BASE}/api/budget/yearly?year=${year}`, { credentials: 'include' }).then(r => r.json())
      .then(res => {
        if (res.success) { setYearlyData(res.data.branches); setTotalsVnd(res.data.totals_vnd) }
        setYearlyLoading(false)
      })
      .catch(() => setYearlyLoading(false))
  }

  const loadYearlyPlan = () => {
    if (!yearlyEditBranch) return
    setYearlyPlanLoading(true)
    setYearlySaveStatus(null)
    fetch(`${API_BASE}/api/budget/yearly-plan?branch=${encodeURIComponent(yearlyEditBranch)}&year=${year}`,
      { credentials: 'include' }).then(r => r.json())
      .then(res => {
        if (res.success) setYearlyPlan(res.data)
        setYearlyPlanLoading(false)
      })
      .catch(() => setYearlyPlanLoading(false))
  }

  const loadSplits = () => {
    if (!splitBranch) return
    setSplitsLoading(true)
    setSaveStatus({})
    fetch(`${API_BASE}/api/budget/monthly-splits?branch=${encodeURIComponent(splitBranch)}&year=${year}`, { credentials: 'include' })
      .then(r => r.json())
      .then(res => {
        if (res.success) setSplitRows(res.data.months)
        setSplitsLoading(false)
      })
      .catch(() => setSplitsLoading(false))
  }

  useEffect(() => { if (tab === 'monthly') loadMonthly() }, [month, tab])
  useEffect(() => {
    if (tab === 'yearly') { loadYearly(); loadYearlyPlan() }
  }, [year, tab, yearlyEditBranch])
  useEffect(() => { if (tab === 'splits') loadSplits() }, [splitBranch, year, tab])

  // Default sub-pickers to first viewable branch
  useEffect(() => {
    if (filterBranches.length > 0 && !filterBranches.includes(splitBranch)) {
      setSplitBranch(filterBranches[0])
    }
    if (filterBranches.length > 0 && !filterBranches.includes(yearlyEditBranch)) {
      setYearlyEditBranch(filterBranches[0])
    }
  }, [filterBranches.join(','), splitBranch, yearlyEditBranch])

  // ----- Yearly editor handlers -----
  const updateYearlyTotal = (val: string) => {
    const num = val === '' ? 0 : parseFloat(val)
    const safe = Number.isFinite(num) && num >= 0 ? num : 0
    setYearlyPlan(prev => {
      if (!prev) return prev
      const rate = CURRENCY_TO_VND[prev.currency] || 1
      const months = prev.months.map(m => ({
        ...m,
        budget_vnd: Math.round(safe * m.pct / 100 * 100) / 100,
        budget_native: rate > 0 ? Math.round((safe * m.pct / 100 / rate) * 100) / 100 : 0,
      }))
      return {
        ...prev,
        yearly_total_vnd: safe,
        yearly_total_native: rate > 0 ? Math.round((safe / rate) * 100) / 100 : 0,
        months,
      }
    })
    setYearlySaveStatus(null)
  }

  const updateMonthPct = (monthIdx: number, val: string) => {
    const num = val === '' ? 0 : parseFloat(val)
    const safe = Number.isFinite(num) && num >= 0 ? num : 0
    setYearlyPlan(prev => {
      if (!prev) return prev
      const rate = CURRENCY_TO_VND[prev.currency] || 1
      const months = prev.months.map(m => {
        if (m.month !== monthIdx) return m
        return {
          ...m,
          pct: safe,
          budget_vnd: Math.round(prev.yearly_total_vnd * safe / 100 * 100) / 100,
          budget_native: rate > 0 ? Math.round((prev.yearly_total_vnd * safe / 100 / rate) * 100) / 100 : 0,
        }
      })
      const month_pct = { ...prev.month_pct, [String(monthIdx)]: safe }
      const pct_sum = Math.round(months.reduce((s, m) => s + (m.pct || 0), 0) * 100) / 100
      return { ...prev, months, month_pct, pct_sum }
    })
    setYearlySaveStatus(null)
  }

  const distributeEvenly = () => {
    setYearlyPlan(prev => {
      if (!prev) return prev
      const each = Math.round((100 / 12) * 100) / 100
      const rate = CURRENCY_TO_VND[prev.currency] || 1
      const months = prev.months.map(m => ({
        ...m,
        pct: each,
        budget_vnd: Math.round(prev.yearly_total_vnd * each / 100 * 100) / 100,
        budget_native: rate > 0 ? Math.round((prev.yearly_total_vnd * each / 100 / rate) * 100) / 100 : 0,
      }))
      const month_pct: Record<string, number> = {}
      for (let i = 1; i <= 12; i++) month_pct[String(i)] = each
      return { ...prev, months, month_pct, pct_sum: Math.round(each * 12 * 100) / 100 }
    })
    setYearlySaveStatus(null)
  }

  const saveYearlyPlan = async () => {
    if (!yearlyPlan) return
    setYearlySaving(true)
    setYearlySaveStatus(null)
    try {
      const res = await fetch(`${API_BASE}/api/budget/yearly-plan`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          branch: yearlyPlan.branch,
          year: yearlyPlan.year,
          yearly_total_vnd: yearlyPlan.yearly_total_vnd,
          month_pct: yearlyPlan.month_pct,
        }),
      }).then(r => r.json())
      if (res.success) {
        setYearlyPlan(res.data)
        setYearlySaveStatus('ok')
        // Reload summary so the new derived monthly totals appear
        loadYearly()
      } else {
        setYearlySaveStatus('err')
      }
    } catch {
      setYearlySaveStatus('err')
    } finally {
      setYearlySaving(false)
    }
  }

  // ----- Splits handlers -----
  const setChannelPct = (monthIdx: number, ch: string, val: string) => {
    const num = val === '' ? 0 : parseFloat(val)
    const safe = Number.isFinite(num) && num >= 0 ? num : 0
    setSplitRows(prev => prev.map(r => {
      if (r.month !== monthIdx) return r
      const channel_pct = { ...r.channel_pct, [ch]: safe }
      const sum = Object.values(channel_pct).reduce((s, v) => s + (Number(v) || 0), 0)
      return { ...r, channel_pct, pct_sum: Math.round(sum * 100) / 100 }
    }))
    setSaveStatus(prev => ({ ...prev, [monthIdx]: null }))
  }

  const saveSplitRow = async (row: SplitMonth) => {
    setSavingMonth(row.month)
    try {
      const res = await fetch(`${API_BASE}/api/budget/monthly-splits`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          branch: row.branch,
          year: row.year,
          month: row.month,
          total_vnd: row.total_vnd,
          channel_pct: row.channel_pct,
        }),
      }).then(r => r.json())
      setSaveStatus(prev => ({ ...prev, [row.month]: res.success ? 'ok' : 'err' }))
    } catch {
      setSaveStatus(prev => ({ ...prev, [row.month]: 'err' }))
    } finally {
      setSavingMonth(null)
    }
  }

  const applyChannelToAll = (ch: string, val: number) => {
    setSplitRows(prev => prev.map(r => {
      const channel_pct = { ...r.channel_pct, [ch]: val }
      const sum = Object.values(channel_pct).reduce((s, v) => s + (Number(v) || 0), 0)
      return { ...r, channel_pct, pct_sum: Math.round(sum * 100) / 100 }
    }))
    setSaveStatus({})
  }

  // Monthly: filter + group by branch
  const filteredItems = selectedBranch === 'all' ? items : items.filter(i => i.branch === selectedBranch)
  const branchGroups: Record<string, BudgetItem[]> = {}
  for (const item of filteredItems) {
    if (!branchGroups[item.branch]) branchGroups[item.branch] = []
    branchGroups[item.branch].push(item)
  }
  const sortedBranches = BRANCHES_ORDER.filter(b => branchGroups[b])

  // Yearly summary: filter by branch
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
            {filterBranches.map(b => <option key={b} value={b}>{b}</option>)}
          </select>
          {tab === 'monthly' && (
            <input type="month" value={month} onChange={e => setMonth(e.target.value)}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          )}
          {(tab === 'yearly' || tab === 'splits') && (
            <select value={year} onChange={e => setYear(Number(e.target.value))}
              className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {[2025, 2026, 2027].map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          )}
        </div>
      </div>

      {/* Tabs — Yearly first (input), then Channel Splits, then Monthly (status) */}
      <div className="flex gap-1 mb-6 bg-gray-100 rounded-lg p-1 w-fit">
        {(['yearly', 'splits', 'monthly'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              tab === t ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}>
            {t === 'yearly' ? 'Yearly' : t === 'splits' ? 'Channel Splits' : 'Monthly'}
          </button>
        ))}
      </div>

      {/* ======================== YEARLY TAB ======================== */}
      {tab === 'yearly' && (
        <div className="space-y-6">
          {/* ---- Yearly editor ---- */}
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-6 py-4 border-b">
              <h2 className="text-sm font-semibold text-gray-900">Yearly plan editor</h2>
              <p className="text-xs text-gray-400 mt-0.5">
                Enter the yearly total in VND, then allocate % across the 12 months.
                Each month's derived budget cascades to Channel Splits.
              </p>
            </div>

            {/* Branch sub-picker */}
            <div className="px-6 py-3 border-b border-gray-100 flex flex-wrap items-center gap-2">
              <span className="text-sm text-gray-500">Branch:</span>
              {filterBranches.map(b => (
                <button key={b} onClick={() => setYearlyEditBranch(b)}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium border ${
                    yearlyEditBranch === b ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                  }`}>
                  {b}
                </button>
              ))}
            </div>

            {!yearlyEditable && (
              <div className="px-6 py-2 bg-yellow-50 border-b border-yellow-200 text-sm text-yellow-800">
                View-only — you don't have edit access to <strong>{yearlyEditBranch}</strong>.
              </div>
            )}

            {yearlyPlanLoading || !yearlyPlan ? (
              <div className="flex items-center justify-center h-48"><div className="text-gray-500">Loading...</div></div>
            ) : (
              <>
                {/* Yearly total + actions */}
                <div className="px-6 py-4 border-b border-gray-100 flex flex-wrap items-end gap-4">
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">Yearly total (VND)</label>
                    <input type="number" disabled={!yearlyEditable}
                      value={yearlyPlan.yearly_total_vnd || ''}
                      onChange={e => updateYearlyTotal(e.target.value)}
                      className="w-56 border rounded-lg px-3 py-2 text-sm disabled:bg-gray-50 disabled:text-gray-400" />
                  </div>
                  <div className="text-xs text-gray-500">
                    <div className="mb-1">Native ({yearlyPlan.currency})</div>
                    <div className="font-medium text-gray-700">{fmt(yearlyPlan.yearly_total_native)}</div>
                  </div>
                  <div className="text-xs text-gray-500">
                    <div className="mb-1">% sum</div>
                    <div className={`font-medium ${
                      yearlyPlan.pct_sum > 100 ? 'text-red-600' : yearlyPlan.pct_sum === 100 ? 'text-green-600' : 'text-yellow-600'
                    }`}>
                      {yearlyPlan.pct_sum.toFixed(1)}%
                    </div>
                  </div>
                  {yearlyEditable && (
                    <>
                      <button onClick={distributeEvenly}
                        className="text-xs px-3 py-1.5 rounded border border-gray-200 hover:bg-gray-50 text-gray-700">
                        Distribute evenly (8.33% each)
                      </button>
                      <button onClick={saveYearlyPlan} disabled={yearlySaving}
                        className={`ml-auto text-sm px-4 py-2 rounded-lg font-medium ${
                          yearlySaveStatus === 'ok' ? 'bg-green-100 text-green-700' :
                          yearlySaveStatus === 'err' ? 'bg-red-100 text-red-700' :
                          'bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50'
                        }`}>
                        {yearlySaving ? 'Saving...' :
                          yearlySaveStatus === 'ok' ? 'Saved' :
                          yearlySaveStatus === 'err' ? 'Retry' : 'Save yearly plan'}
                      </button>
                    </>
                  )}
                </div>

                {/* 12-month grid */}
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-gray-100 bg-gray-50">
                        <th className="text-left py-2 px-3 text-gray-500 font-medium w-16">Month</th>
                        <th className="text-right py-2 px-3 text-gray-500 font-medium w-32">% of year</th>
                        <th className="text-right py-2 px-3 text-gray-500 font-medium">Budget (VND)</th>
                        <th className="text-right py-2 px-3 text-gray-500 font-medium">Native ({yearlyPlan.currency})</th>
                      </tr>
                    </thead>
                    <tbody>
                      {yearlyPlan.months.map(m => {
                        const isCurrent = m.month === new Date().getMonth() + 1 && year === new Date().getFullYear()
                        return (
                          <tr key={m.month} className={`border-b border-gray-50 ${isCurrent ? 'bg-blue-50' : 'hover:bg-gray-50'}`}>
                            <td className="py-2 px-3 font-medium text-gray-700">{MONTH_NAMES[m.month]}</td>
                            <td className="py-2 px-3 text-right">
                              <div className="inline-flex items-center gap-1">
                                <input type="number" min={0} max={200} step={0.01} disabled={!yearlyEditable}
                                  value={m.pct || ''}
                                  onChange={e => updateMonthPct(m.month, e.target.value)}
                                  className="w-20 border rounded px-2 py-1 text-right text-xs disabled:bg-gray-50 disabled:text-gray-400" />
                                <span className="text-gray-400 text-xs">%</span>
                              </div>
                            </td>
                            <td className="py-2 px-3 text-right text-gray-700">{m.budget_vnd > 0 ? fmt(m.budget_vnd) : '-'}</td>
                            <td className="py-2 px-3 text-right text-gray-600">{m.budget_native > 0 ? fmt(m.budget_native) : '-'}</td>
                          </tr>
                        )
                      })}
                      <tr className="bg-gray-50 font-medium">
                        <td className="py-2 px-3">Total</td>
                        <td className={`py-2 px-3 text-right ${
                          yearlyPlan.pct_sum > 100 ? 'text-red-600' : yearlyPlan.pct_sum === 100 ? 'text-green-600' : 'text-yellow-600'
                        }`}>
                          {yearlyPlan.pct_sum.toFixed(1)}%
                        </td>
                        <td className="py-2 px-3 text-right">{fmt(yearlyPlan.months.reduce((s, m) => s + m.budget_vnd, 0))}</td>
                        <td className="py-2 px-3 text-right">{fmt(yearlyPlan.months.reduce((s, m) => s + m.budget_native, 0))}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>

          {/* ---- Yearly summary (read-only, all branches) ---- */}
          {yearlyLoading ? (
            <div className="flex items-center justify-center h-64"><div className="text-gray-500">Loading...</div></div>
          ) : (
            <>
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
                            <th className="text-left py-2 px-4 text-gray-500 font-medium">Notes</th>
                          </tr>
                        </thead>
                        <tbody>
                          {totalsVnd.months.map(m => {
                            const hasBudget = m.budget > 0
                            const mPct = m.budget > 0 ? (m.spent / m.budget * 100) : 0
                            const remaining = m.budget - m.spent
                            const isCurrent = m.month === new Date().getMonth() + 1 && year === new Date().getFullYear()
                            const aggregated: { branch: string; channel: string; text: string }[] = []
                            for (const b of yearlyData) {
                              const bm = b.months.find(x => x.month === m.month)
                              for (const n of (bm?.notes || [])) {
                                aggregated.push({ branch: b.branch, channel: n.channel, text: n.text })
                              }
                            }
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
                                <td className="py-2 px-4 text-xs text-gray-600 max-w-sm">
                                  {aggregated.length > 0 ? (
                                    <div className="space-y-0.5">
                                      {aggregated.map((n, idx) => (
                                        <div key={idx} className="flex gap-1.5">
                                          <span className="text-gray-400 capitalize w-24 shrink-0 truncate">{n.branch} · {n.channel}</span>
                                          <span className="text-gray-700">{n.text}</span>
                                        </div>
                                      ))}
                                    </div>
                                  ) : <span className="text-gray-300">—</span>}
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
                            <th className="text-right py-2 px-4 text-gray-500 font-medium">Allocate</th>
                            <th className="text-right py-2 px-4 text-gray-500 font-medium">Actual Spend</th>
                            <th className="text-right py-2 px-4 text-gray-500 font-medium">Remaining</th>
                            <th className="text-right py-2 px-4 text-gray-500 font-medium w-20">%</th>
                            <th className="py-2 px-4 w-32"></th>
                            <th className="text-left py-2 px-4 text-gray-500 font-medium">Note</th>
                          </tr>
                        </thead>
                        <tbody>
                          {branch.months.map(m => {
                            const hasBudget = m.budget > 0
                            const mPct = m.budget > 0 ? (m.spent / m.budget * 100) : 0
                            const remaining = m.budget - m.spent
                            const isCurrentMonth = m.month === new Date().getMonth() + 1 && year === new Date().getFullYear()
                            const monthNotes = m.notes || []
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
                                <td className="py-2 px-4 text-xs text-gray-600 max-w-xs">
                                  {monthNotes.length > 0 ? (
                                    <div className="space-y-0.5">
                                      {monthNotes.map((n, idx) => (
                                        <div key={idx} className="flex gap-1.5">
                                          <span className="text-gray-400 capitalize w-12 shrink-0">{n.channel}:</span>
                                          <span className="text-gray-700">{n.text}</span>
                                        </div>
                                      ))}
                                    </div>
                                  ) : <span className="text-gray-300">—</span>}
                                </td>
                              </tr>
                            )
                          })}
                          <tr className="bg-gray-50 font-medium">
                            <td className="py-2 px-4">Total</td>
                            <td className="py-2 px-4 text-right">{fmt(branch.yearly_budget)}</td>
                            <td className="py-2 px-4 text-right">{fmt(branch.yearly_spent)}</td>
                            <td className={`py-2 px-4 text-right ${branch.yearly_budget - branch.yearly_spent < 0 ? 'text-red-600' : ''}`}>
                              {fmt(branch.yearly_budget - branch.yearly_spent)}
                            </td>
                            <td className="py-2 px-4 text-right text-xs">{pct.toFixed(1)}%</td>
                            <td className="py-2 px-4"></td>
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
            </>
          )}
        </div>
      )}

      {/* ======================== SPLITS TAB ======================== */}
      {tab === 'splits' && (
        <div className="space-y-4">
          {/* Branch sub-picker */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-gray-500">Branch:</span>
            {filterBranches.map(b => (
              <button key={b} onClick={() => setSplitBranch(b)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium border ${
                  splitBranch === b ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                }`}>
                {b}
              </button>
            ))}
          </div>

          {!splitEditable && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg px-4 py-2 text-sm text-yellow-800">
              View-only — you don't have edit access to <strong>{splitBranch}</strong>.
            </div>
          )}

          {splitsLoading ? (
            <div className="flex items-center justify-center h-64"><div className="text-gray-500">Loading...</div></div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-semibold text-gray-900">{splitBranch} — {year} channel splits</h2>
                  <p className="text-xs text-gray-400 mt-0.5">
                    Monthly totals come from the Yearly tab. Set channel % to allocate each month across meta / google / tiktok.
                  </p>
                </div>
                {splitEditable && (
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-gray-500">Apply to all months:</span>
                    {CHANNELS.map(c => (
                      <div key={c} className="flex items-center gap-1">
                        <span className="text-gray-600 capitalize">{c}</span>
                        <input type="number" min={0} max={200} placeholder="%"
                          onKeyDown={e => {
                            if (e.key === 'Enter') {
                              const v = parseFloat((e.target as HTMLInputElement).value)
                              if (Number.isFinite(v)) applyChannelToAll(c, v)
                            }
                          }}
                          className="w-14 border rounded px-1.5 py-0.5 text-right" />
                      </div>
                    ))}
                    <span className="text-gray-400">↵ to apply</span>
                  </div>
                )}
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50">
                      <th className="text-left py-2 px-3 text-gray-500 font-medium w-14">Month</th>
                      <th className="text-right py-2 px-3 text-gray-500 font-medium">Total (VND)</th>
                      {CHANNELS.map(c => (
                        <th key={c} className="text-right py-2 px-2 text-gray-500 font-medium w-20 capitalize">{c} %</th>
                      ))}
                      <th className="text-right py-2 px-2 text-gray-500 font-medium w-16">Sum</th>
                      <th className="text-right py-2 px-3 text-gray-500 font-medium">Native</th>
                      <th className="py-2 px-3 w-24"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {splitRows.map(row => {
                      const isOver = row.pct_sum > 100
                      const isUnder = row.pct_sum > 0 && row.pct_sum < 100
                      const sumColor = isOver ? 'text-red-600 font-semibold' : isUnder ? 'text-yellow-600' : row.pct_sum === 100 ? 'text-green-600' : 'text-gray-300'
                      const status = saveStatus[row.month]
                      const noTotal = !row.total_vnd || row.total_vnd <= 0
                      return (
                        <tr key={row.month} className="border-b border-gray-50 hover:bg-gray-50">
                          <td className="py-2 px-3 font-medium text-gray-700">{MONTH_NAMES[row.month]}</td>
                          <td className="py-2 px-3 text-right text-xs text-gray-600">
                            {row.total_vnd > 0 ? fmt(row.total_vnd) : <span className="text-gray-300">— set in Yearly</span>}
                          </td>
                          {CHANNELS.map(c => (
                            <td key={c} className="py-2 px-2 text-right">
                              <input type="number" min={0} max={200} step={1} disabled={!splitEditable || noTotal}
                                value={row.channel_pct[c] ?? ''}
                                onChange={e => setChannelPct(row.month, c, e.target.value)}
                                className="w-16 border rounded px-1.5 py-1 text-right text-xs disabled:bg-gray-50 disabled:text-gray-400" />
                            </td>
                          ))}
                          <td className={`py-2 px-2 text-right text-xs ${sumColor}`}>{row.pct_sum.toFixed(0)}%</td>
                          <td className="py-2 px-3 text-right text-xs text-gray-600">
                            {row.total_vnd > 0 ? `${fmt(row.total_native)} ${row.currency}` : '-'}
                          </td>
                          <td className="py-2 px-3 text-right">
                            {splitEditable && !noTotal ? (
                              <button onClick={() => saveSplitRow(row)} disabled={savingMonth === row.month}
                                className={`text-xs px-3 py-1 rounded font-medium ${
                                  status === 'ok' ? 'bg-green-100 text-green-700' :
                                  status === 'err' ? 'bg-red-100 text-red-700' :
                                  'bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50'
                                }`}>
                                {savingMonth === row.month ? '...' :
                                  status === 'ok' ? 'Saved' :
                                  status === 'err' ? 'Retry' : 'Save'}
                              </button>
                            ) : (
                              <span className="text-xs text-gray-300">—</span>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
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
                  <div className="px-4 pt-4 pb-3 border-b border-gray-100">
                    <BudgetCard label="Total" spent={tSpent} budget={tBudget} currency={cur} projected={tProjected} daysRemaining={dRem} />
                    {bi.map(item => {
                      const isOver = item.pace_status === 'Over'
                      const overspend = Math.max(0, item.spent - item.total_budget)
                      return (
                        <ChannelNoteEditor
                          key={item.plan_id}
                          planId={item.plan_id}
                          channelLabel={item.channel.charAt(0).toUpperCase() + item.channel.slice(1)}
                          initialNote={item.notes ?? null}
                          isOver={isOver}
                          overspend={overspend}
                          currency={item.currency}
                          editable={editableBranches.includes(item.branch)}
                          onSaved={(note) => {
                            setItems(prev => prev.map(i => i.plan_id === item.plan_id ? { ...i, notes: note } : i))
                          }}
                        />
                      )
                    })}
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
    </div>
  )
}
