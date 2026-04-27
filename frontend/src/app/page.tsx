'use client'

import { useEffect, useMemo, useState, useCallback, useRef } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
  PieChart, Pie, Cell,
} from 'recharts'
import { TrendingUp, TrendingDown, ChevronRight, ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react'
import { useSortableRows } from '@/lib/useSortableRows'
import FunnelRecommendations from '@/components/FunnelRecommendations'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface KPIs {
  total_spend: number
  total_revenue: number
  total_impressions: number
  total_clicks: number
  total_conversions: number
  roas: number
  ctr: number
  cpc: number
  cpa: number
  conversion_rate: number
  total_spend_change: number | null
  total_revenue_change: number | null
  total_impressions_change: number | null
  total_clicks_change: number | null
  total_conversions_change: number | null
  roas_change: number | null
  ctr_change: number | null
  cpc_change: number | null
  cpa_change: number | null
  conversion_rate_change: number | null
  period: { from: string; to: string }
  prev_period: { from: string; to: string }
}

interface DailyRow {
  date: string
  spend: number
  revenue: number
  roas: number
}

interface AccountRow {
  account_id: string
  account_name: string
  platform: string
  currency: string
  spend: number
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  roas: number
  ctr: number
}

interface FunnelStep {
  key: string
  label: string
  value: number
  change: number | null
  drop_off: number | null
  drop_off_change: number | null
}

interface Account {
  id: string
  platform: string
  account_name: string
  currency: string
}

interface Branch {
  name: string
  currency: string
}

interface BranchBreakdownRow {
  branch: string
  currency: string
  spend_vnd: number
  conversions: number
  revenue_vnd: number
}

const CURRENCY_SYMBOLS: Record<string, string> = {
  VND: '₫', TWD: 'NT$', JPY: '¥', USD: '$',
}

function fmtMoney(n: number, currency: string): string {
  const symbol = CURRENCY_SYMBOLS[currency] || currency
  return `${new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(n)} ${symbol}`
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(n)
}

// inverseColor: true = "increase is bad" (cost, cpc, cpa, drop-off)
function ChangeTag({ change, inverseColor = false }: { change: number | null; inverseColor?: boolean }) {
  if (change === null || change === undefined) return <span className="text-xs text-gray-400">No data</span>
  const pct = change * 100
  if (Math.abs(pct) < 0.01) return <span className="text-xs text-gray-400">0%</span>
  const pos = pct > 0
  // If inverseColor: positive = bad (red), negative = good (green)
  const isGood = inverseColor ? !pos : pos
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${isGood ? 'text-green-600' : 'text-red-500'}`}>
      {pos ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
      {pos ? '+' : ''}{pct.toFixed(1)}%
    </span>
  )
}

// Date presets
function getDateRange(preset: string): { from: string; to: string } {
  const today = new Date()
  const to = today.toISOString().split('T')[0]
  const daysBack = (d: number) => {
    const dt = new Date(today)
    dt.setDate(dt.getDate() - d)
    return dt.toISOString().split('T')[0]
  }
  switch (preset) {
    case 'today': return { from: to, to }
    case 'yesterday': {
      const y = daysBack(1)
      return { from: y, to: y }
    }
    case '7d': return { from: daysBack(6), to }
    case '14d': return { from: daysBack(13), to }
    case '30d': return { from: daysBack(29), to }
    case 'this_month': {
      const from = new Date(today.getFullYear(), today.getMonth(), 1).toISOString().split('T')[0]
      return { from, to }
    }
    case 'last_month': {
      const from = new Date(today.getFullYear(), today.getMonth() - 1, 1).toISOString().split('T')[0]
      const last = new Date(today.getFullYear(), today.getMonth(), 0).toISOString().split('T')[0]
      return { from, to: last }
    }
    default: return { from: daysBack(6), to }
  }
}

export default function DashboardPage() {
  const [kpis, setKpis] = useState<KPIs | null>(null)
  const [daily, setDaily] = useState<DailyRow[]>([])
  const [byAccount, setByAccount] = useState<AccountRow[]>([])
  const [byBranch, setByBranch] = useState<BranchBreakdownRow[]>([])
  const [funnel, setFunnel] = useState<FunnelStep[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [branches, setBranches] = useState<Branch[]>([])
  const [loading, setLoading] = useState(true)

  const [selectedBranches, setSelectedBranches] = useState<string[]>([])
  const [branchDropdownOpen, setBranchDropdownOpen] = useState(false)
  const [selectedPlatform, setSelectedPlatform] = useState('')
  const [datePreset, setDatePreset] = useState('7d')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')

  const activeCurrency = (() => {
    if (selectedBranches.length === 0) return 'VND'
    const currencies = [...new Set(selectedBranches.map(b => branches.find(br => br.name === b)?.currency || 'VND'))]
    return currencies.length === 1 ? currencies[0] : 'VND'
  })()

  const resolvedRange = useMemo(() => {
    if (datePreset === 'custom' && customFrom && customTo) {
      return { from: customFrom, to: customTo }
    }
    return getDateRange(datePreset)
  }, [datePreset, customFrom, customTo])

  const getDateParams = useCallback(() => {
    return `date_from=${resolvedRange.from}&date_to=${resolvedRange.to}`
  }, [resolvedRange])

  const fetchData = useCallback(() => {
    setLoading(true)
    const dateParams = getDateParams()
    const branchParam = selectedBranches.length > 0 ? `&branches=${selectedBranches.join(',')}` : ''
    const platParam = selectedPlatform ? `&platform=${selectedPlatform}` : ''
    const qs = `?${dateParams}${branchParam}${platParam}`

    const opts = { credentials: 'include' as const }
    Promise.all([
      fetch(`${API_BASE}/api/dashboard/kpis${qs}`, opts).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/daily${qs}`, opts).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/by-account?${dateParams}${branchParam}${platParam}`, opts).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/funnel${qs}`, opts).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/by-branch?${dateParams}${branchParam}${platParam}`, opts).then(r => r.json()),
    ])
      .then(([kpiRes, dailyRes, accountRes, funnelRes, branchRes]) => {
        if (kpiRes.success) setKpis(kpiRes.data)
        if (dailyRes.success) setDaily(dailyRes.data)
        if (accountRes.success) setByAccount(accountRes.data)
        if (funnelRes.success) setFunnel(funnelRes.data.steps || [])
        if (branchRes.success) setByBranch(branchRes.data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [getDateParams, selectedBranches, selectedPlatform])

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setAccounts(data.data) })
      .catch(() => {})
    fetch(`${API_BASE}/api/branches`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setBranches(data.data) })
      .catch(() => {})
  }, [])

  const branchDropdownRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (branchDropdownRef.current && !branchDropdownRef.current.contains(e.target as Node)) {
        setBranchDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const toggleBranch = (name: string) => {
    setSelectedBranches(prev =>
      prev.includes(name) ? prev.filter(b => b !== name) : [...prev, name]
    )
  }

  useEffect(() => { fetchData() }, [fetchData])

  if (loading && !kpis) {
    return <div className="flex items-center justify-center h-64"><div className="text-gray-500">Loading dashboard...</div></div>
  }

  // inverseColor = true means "increase is bad" (cost metrics)
  const kpiRow1 = [
    { label: `Cost (${activeCurrency})`, value: kpis ? fmtMoney(kpis.total_spend, activeCurrency) : '--', change: kpis?.total_spend_change, inverse: true },
    { label: `Revenue (${activeCurrency})`, value: kpis ? fmtMoney(kpis.total_revenue, activeCurrency) : '--', change: kpis?.total_revenue_change, inverse: false },
    { label: `CPC (${activeCurrency})`, value: kpis ? fmtMoney(kpis.cpc, activeCurrency) : '--', change: kpis?.cpc_change, inverse: true },
    { label: 'ROAS', value: kpis ? kpis.roas.toFixed(2) : '--', change: kpis?.roas_change, inverse: false },
  ]

  const kpiRow2 = [
    { label: 'Clicks', value: kpis ? fmtNum(kpis.total_clicks) : '--', change: kpis?.total_clicks_change, inverse: false },
    { label: 'Impressions', value: kpis ? fmtNum(kpis.total_impressions) : '--', change: kpis?.total_impressions_change, inverse: false },
    { label: 'Conversions', value: kpis ? fmtNum(kpis.total_conversions) : '--', change: kpis?.total_conversions_change, inverse: false },
    { label: 'Conversion rate', value: kpis ? `${(kpis.conversion_rate * 100).toFixed(4)}%` : '--', change: kpis?.conversion_rate_change, inverse: false },
  ]

  // Funnel bar widths (proportional to max value)
  const funnelMax = funnel.length > 0 ? Math.max(...funnel.map(s => s.value), 1) : 1

  return (
    <div>
      {/* Header + Filters */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <h1 className="text-2xl font-bold text-blue-600">ADS Performance</h1>
        <div className="flex flex-wrap items-center gap-2">
          {/* Date presets */}
          <select
            value={datePreset}
            onChange={(e) => setDatePreset(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="today">Today</option>
            <option value="yesterday">Yesterday</option>
            <option value="7d">Last 7 days</option>
            <option value="14d">Last 14 days</option>
            <option value="30d">Last 30 days</option>
            <option value="this_month">This month</option>
            <option value="last_month">Last month</option>
            <option value="custom">Custom range</option>
          </select>

          {datePreset === 'custom' && (
            <>
              <input
                type="date"
                value={customFrom}
                onChange={(e) => setCustomFrom(e.target.value)}
                className="px-2 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <span className="text-gray-400">→</span>
              <input
                type="date"
                value={customTo}
                onChange={(e) => setCustomTo(e.target.value)}
                className="px-2 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </>
          )}

          {/* Platform filter */}
          <select
            value={selectedPlatform}
            onChange={(e) => setSelectedPlatform(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Platforms</option>
            <option value="meta">Meta Ads</option>
            <option value="google">Google Ads</option>
            <option value="tiktok">TikTok Ads</option>
          </select>

          {/* Branch filter (multi-select) */}
          <div className="relative" ref={branchDropdownRef}>
            <button
              onClick={() => setBranchDropdownOpen(!branchDropdownOpen)}
              className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white min-w-[180px] text-left flex items-center justify-between gap-2"
            >
              <span className="truncate">
                {selectedBranches.length === 0
                  ? `All Branches (VND)`
                  : selectedBranches.length === 1
                    ? `${selectedBranches[0]} (${activeCurrency})`
                    : `${selectedBranches.length} branches (${activeCurrency})`}
              </span>
              <svg className={`w-4 h-4 text-gray-400 transition-transform ${branchDropdownOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
            </button>
            {branchDropdownOpen && (
              <div className="absolute z-50 mt-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg py-1">
                {selectedBranches.length > 0 && (
                  <button
                    onClick={() => setSelectedBranches([])}
                    className="w-full px-3 py-1.5 text-xs text-blue-600 hover:bg-gray-50 text-left"
                  >
                    Clear all
                  </button>
                )}
                {branches.map(b => (
                  <label
                    key={b.name}
                    className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={selectedBranches.includes(b.name)}
                      onChange={() => toggleBranch(b.name)}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <span>{b.name}</span>
                    <span className="text-gray-400 text-xs ml-auto">{b.currency}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Period info */}
      {kpis?.period && (
        <p className="text-xs text-gray-400 mb-4">
          {kpis.period.from} → {kpis.period.to} &nbsp;vs&nbsp; {kpis.prev_period.from} → {kpis.prev_period.to}
        </p>
      )}

      {/* KPI Row 1 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
        {kpiRow1.map((card) => (
          <div key={card.label} className="bg-white rounded-xl border border-gray-200 p-5">
            <p className="text-xs text-gray-500 mb-1">{card.label}</p>
            <p className="text-2xl font-bold text-gray-900">{card.value}</p>
            <div className="mt-2"><ChangeTag change={card.change ?? null} inverseColor={card.inverse} /></div>
          </div>
        ))}
      </div>

      {/* KPI Row 2 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {kpiRow2.map((card) => (
          <div key={card.label} className="bg-white rounded-xl border border-gray-200 p-5">
            <p className="text-xs text-gray-500 mb-1">{card.label}</p>
            <p className="text-2xl font-bold text-gray-900">{card.value}</p>
            <div className="mt-2"><ChangeTag change={card.change ?? null} inverseColor={card.inverse} /></div>
          </div>
        ))}
      </div>

      {/* Branch breakdown pies */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <BranchPie
          title="Branch by Cost (VND)"
          rows={byBranch}
          valueKey="spend_vnd"
          selectedBranches={selectedBranches}
          onToggle={toggleBranch}
          valueFormatter={(v) => fmtMoney(v, 'VND')}
        />
        <BranchPie
          title="Branch by Conversion"
          rows={byBranch}
          valueKey="conversions"
          selectedBranches={selectedBranches}
          onToggle={toggleBranch}
          valueFormatter={(v) => fmtNum(v)}
        />
      </div>

      {/* Funnel */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-5">Conversion Funnel</h2>
        <div className="space-y-3">
          {funnel.map((step, i) => {
            const widthPct = Math.max((step.value / funnelMax) * 100, 4)
            return (
              <div key={step.key}>
                {i > 0 && (
                  <div className="flex items-center gap-2 ml-4 mb-1">
                    <ChevronRight className="w-3 h-3 text-gray-300" />
                    {step.drop_off !== null && (
                      <span className="text-xs text-gray-400">
                        {(step.drop_off * 100).toFixed(1)}% drop-off
                      </span>
                    )}
                    {step.drop_off_change !== null && (
                      <ChangeTag change={step.drop_off_change} inverseColor />
                    )}
                  </div>
                )}
                <div className="flex items-center gap-4">
                  <div
                    className="bg-blue-100 rounded-lg py-3 px-4 flex items-center justify-between transition-all"
                    style={{ width: `${widthPct}%`, minWidth: '180px' }}
                  >
                    <span className="text-xs text-gray-600">{step.label}</span>
                    <span className="text-lg font-bold text-gray-900 ml-2">
                      {fmtNum(step.value)}
                    </span>
                  </div>
                  <div className="shrink-0">
                    <ChangeTag change={step.change} />
                  </div>
                </div>
              </div>
            )
          })}
          {funnel.length === 0 && (
            <p className="text-gray-400 text-sm text-center py-4">No funnel data. Run a sync first.</p>
          )}
        </div>
      </div>

      {/* Funnel Recommendations — bottlenecks broken down by Channel × Country
          × Funnel × TA, with deep-link to the page that owns each root cause. */}
      <FunnelRecommendations
        branches={selectedBranches.join(',')}
        platform={selectedPlatform}
        dateFrom={resolvedRange.from}
        dateTo={resolvedRange.to}
      />

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Spend vs Revenue — {activeCurrency}</h2>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmtNum(v)} />
              <Tooltip formatter={(v: number) => fmtMoney(v, activeCurrency)} labelFormatter={(l) => `Date: ${l}`} />
              <Legend />
              <Area type="monotone" dataKey="spend" name="Spend" stroke="#ef4444" fill="#fef2f2" strokeWidth={2} />
              <Area type="monotone" dataKey="revenue" name="Revenue" stroke="#10b981" fill="#ecfdf5" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">ROAS</h2>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={daily}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v.toFixed(1)}x`} />
              <Tooltip formatter={(v: number) => `${v.toFixed(2)}x`} labelFormatter={(l) => `Date: ${l}`} />
              <Area type="monotone" dataKey="roas" name="ROAS" stroke="#3b82f6" fill="#eff6ff" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Performance by Branch */}
      <PerformanceByBranchTable rows={byAccount} />
    </div>
  )
}

const PIE_COLORS = ['#a68a64', '#b8a7d9', '#a3c982', '#7dc4c2', '#eb7373', '#f4b971']

function BranchPie({
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
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <h2 className="text-sm font-semibold text-gray-700 mb-4">{title}</h2>
      {data.length === 0 ? (
        <p className="text-gray-400 text-sm text-center py-16">No data</p>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="40%"
              cy="50%"
              outerRadius={95}
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

function PerformanceByBranchTable({ rows }: { rows: AccountRow[] }) {
  const { sorted, sortBy, sortDir, toggleSort } = useSortableRows<AccountRow>(rows)

  const SortHeader = ({ col, label, align = 'right' }: { col: keyof AccountRow; label: string; align?: 'left' | 'right' }) => {
    const active = sortBy === col
    return (
      <th className={`${align === 'right' ? 'text-right' : 'text-left'} py-3 px-2 text-gray-500 font-medium cursor-pointer select-none hover:text-gray-700`} onClick={() => toggleSort(col)}>
        <span className={`inline-flex items-center gap-1 ${align === 'right' ? 'justify-end w-full' : ''}`}>
          {label}
          {active
            ? (sortDir === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)
            : <ArrowUpDown className="w-3 h-3 opacity-40" />}
        </span>
      </th>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <h2 className="text-sm font-semibold text-gray-700 mb-4">Performance by Branch</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              <SortHeader col="platform" label="Platform" align="left" />
              <SortHeader col="account_name" label="Branch" align="left" />
              <SortHeader col="spend" label="Spend" />
              <SortHeader col="revenue" label="Revenue" />
              <SortHeader col="roas" label="ROAS" />
              <SortHeader col="clicks" label="Clicks" />
              <SortHeader col="ctr" label="CTR" />
              <SortHeader col="conversions" label="Conversions" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
                const platformColors: Record<string, string> = {
                  meta: 'bg-blue-50 text-blue-700',
                  google: 'bg-green-50 text-green-700',
                  tiktok: 'bg-pink-50 text-pink-700',
                }
                const platformLabel = (row.platform || 'meta').charAt(0).toUpperCase() + (row.platform || 'meta').slice(1)
                return (
                <tr key={row.account_id} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="py-3 px-2">
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${platformColors[row.platform] || 'bg-gray-50 text-gray-600'}`}>
                      {platformLabel}
                    </span>
                  </td>
                  <td className="py-3 px-2">
                    <span className="font-medium text-gray-900">{row.account_name}</span>
                    <span className="text-xs text-gray-400 ml-1">({row.currency})</span>
                  </td>
                  <td className="py-3 px-2 text-right text-gray-700">{fmtMoney(row.spend, row.currency)}</td>
                  <td className="py-3 px-2 text-right text-gray-700">{fmtMoney(row.revenue, row.currency)}</td>
                  <td className="py-3 px-2 text-right">
                    <span className={`font-medium ${row.roas >= 1 ? 'text-green-600' : 'text-red-600'}`}>
                      {row.roas.toFixed(2)}x
                    </span>
                  </td>
                  <td className="py-3 px-2 text-right text-gray-700">{fmtNum(row.clicks)}</td>
                  <td className="py-3 px-2 text-right text-gray-700">{(row.ctr * 100).toFixed(2)}%</td>
                  <td className="py-3 px-2 text-right text-gray-700">{row.conversions}</td>
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr><td colSpan={8} className="py-8 text-center text-gray-400">No metrics data yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
