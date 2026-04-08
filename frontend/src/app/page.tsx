'use client'

import { useEffect, useState, useCallback } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { TrendingUp, TrendingDown, ChevronRight } from 'lucide-react'

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
  account_name: string
  currency: string
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
  const [funnel, setFunnel] = useState<FunnelStep[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)

  const [selectedAccount, setSelectedAccount] = useState('')
  const [datePreset, setDatePreset] = useState('7d')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')

  const activeCurrency = selectedAccount
    ? accounts.find(a => a.id === selectedAccount)?.currency || 'VND'
    : 'VND'

  const getDateParams = useCallback(() => {
    if (datePreset === 'custom' && customFrom && customTo) {
      return `date_from=${customFrom}&date_to=${customTo}`
    }
    const { from, to } = getDateRange(datePreset)
    return `date_from=${from}&date_to=${to}`
  }, [datePreset, customFrom, customTo])

  const fetchData = useCallback(() => {
    setLoading(true)
    const dateParams = getDateParams()
    const accParam = selectedAccount ? `&account_id=${selectedAccount}` : ''
    const qs = `?${dateParams}${accParam}`

    Promise.all([
      fetch(`${API_BASE}/api/dashboard/kpis${qs}`).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/daily${qs}`).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/by-account?${dateParams}`).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/funnel${qs}`).then(r => r.json()),
    ])
      .then(([kpiRes, dailyRes, accountRes, funnelRes]) => {
        if (kpiRes.success) setKpis(kpiRes.data)
        if (dailyRes.success) setDaily(dailyRes.data)
        if (accountRes.success) setByAccount(accountRes.data)
        if (funnelRes.success) setFunnel(funnelRes.data.steps || [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [getDateParams, selectedAccount])

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`)
      .then(r => r.json())
      .then(data => { if (data.success) setAccounts(data.data) })
      .catch(() => {})
  }, [])

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

          {/* Branch filter */}
          <select
            value={selectedAccount}
            onChange={(e) => setSelectedAccount(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Branches (VND)</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.account_name} ({a.currency})</option>
            ))}
          </select>
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
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">Performance by Branch</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left py-3 px-2 text-gray-500 font-medium">Branch</th>
                <th className="text-right py-3 px-2 text-gray-500 font-medium">Spend</th>
                <th className="text-right py-3 px-2 text-gray-500 font-medium">Revenue</th>
                <th className="text-right py-3 px-2 text-gray-500 font-medium">ROAS</th>
                <th className="text-right py-3 px-2 text-gray-500 font-medium">Clicks</th>
                <th className="text-right py-3 px-2 text-gray-500 font-medium">CTR</th>
                <th className="text-right py-3 px-2 text-gray-500 font-medium">Conversions</th>
              </tr>
            </thead>
            <tbody>
              {byAccount.map((row) => (
                <tr key={row.account_id} className="border-b border-gray-50 hover:bg-gray-50">
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
              ))}
              {byAccount.length === 0 && (
                <tr><td colSpan={7} className="py-8 text-center text-gray-400">No metrics data yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
