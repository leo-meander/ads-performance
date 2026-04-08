'use client'

import { useEffect, useState, useCallback } from 'react'
import { TrendingUp, TrendingDown } from 'lucide-react'
import { apiFetch } from '@/lib/api'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type CountryOption = { code: string; name: string; adset_count: number }
type Account = { id: string; account_name: string; currency: string }

type CountryKpi = {
  country_code: string
  country: string
  total_spend: number
  total_revenue: number
  roas: number
  ctr: number
  cpa: number
  impressions: number
  clicks: number
  conversions: number
  campaign_count: number
  spend_change: number | null
  revenue_change: number | null
  roas_change: number | null
  ctr_change: number | null
  conversions_change: number | null
}

type TaRow = {
  ta: string
  funnel_stage: string
  spend: number
  revenue: number
  roas: number
  ctr: number
  cpa: number
  conversions: number
  is_remarketing: boolean
  spend_change: number | null
  roas_change: number | null
  conversions_change: number | null
}

type FunnelStage = {
  name: string
  value: number
  change: number | null
  drop_off_rate?: number
}

function ChangeTag({ change, inverseColor = false }: { change: number | null; inverseColor?: boolean }) {
  if (change === null || change === undefined) return <span className="text-xs text-gray-400">--</span>
  const pct = change * 100
  if (Math.abs(pct) < 0.01) return <span className="text-xs text-gray-400">0%</span>
  const pos = pct > 0
  const isGood = inverseColor ? !pos : pos
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${isGood ? 'text-green-600' : 'text-red-500'}`}>
      {pos ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
      {pos ? '+' : ''}{pct.toFixed(1)}%
    </span>
  )
}

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

const fmt = (n: number) => new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(n)

export default function CountryDashboard() {
  const [country, setCountry] = useState('')
  const [platform, setPlatform] = useState('')
  const [funnelStage, setFunnelStage] = useState('')
  const [selectedAccount, setSelectedAccount] = useState('')
  const [datePreset, setDatePreset] = useState('7d')

  const [countries, setCountries] = useState<CountryOption[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [kpiData, setKpiData] = useState<CountryKpi[]>([])
  const [taData, setTaData] = useState<TaRow[]>([])
  const [funnelData, setFunnelData] = useState<FunnelStage[]>([])
  const [comparison, setComparison] = useState<CountryKpi[]>([])
  const [periodInfo, setPeriodInfo] = useState<{ from: string; to: string; prev_from: string; prev_to: string } | null>(null)
  const [loading, setLoading] = useState(true)

  // Load accounts once
  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`)
      .then(r => r.json())
      .then(data => { if (data.success) setAccounts(data.data) })
      .catch(() => {})
  }, [])

  // Load countries (filtered by branch)
  useEffect(() => {
    const accParam = selectedAccount ? `?account_id=${selectedAccount}` : ''
    fetch(`${API_BASE}/api/dashboard/country/countries${accParam}`)
      .then(r => r.json())
      .then(res => { if (res.success) setCountries(res.data) })
      .catch(() => {})
  }, [selectedAccount])

  const buildQs = useCallback(() => {
    const { from, to } = getDateRange(datePreset)
    const params = new URLSearchParams({ date_from: from, date_to: to })
    if (country) params.set('country', country)
    if (platform) params.set('platform', platform)
    if (funnelStage) params.set('funnel_stage', funnelStage)
    if (selectedAccount) params.set('account_id', selectedAccount)
    return params.toString()
  }, [country, platform, funnelStage, selectedAccount, datePreset])

  useEffect(() => {
    setLoading(true)
    const qs = buildQs()
    const { from, to } = getDateRange(datePreset)

    const taQs = country
      ? `country=${country}&date_from=${from}&date_to=${to}${platform ? `&platform=${platform}` : ''}${selectedAccount ? `&account_id=${selectedAccount}` : ''}`
      : null

    Promise.all([
      fetch(`${API_BASE}/api/dashboard/country?${qs}`).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/country/comparison?${qs}`).then(r => r.json()),
      taQs
        ? fetch(`${API_BASE}/api/dashboard/country/ta-breakdown?${taQs}`).then(r => r.json())
        : Promise.resolve({ success: true, data: [] }),
      taQs
        ? fetch(`${API_BASE}/api/dashboard/country/funnel?${taQs}`).then(r => r.json())
        : Promise.resolve({ success: true, data: { stages: [] } }),
    ]).then(([kpi, comp, ta, funnel]) => {
      if (kpi.success && kpi.data) {
        setKpiData(kpi.data.items || [])
        if (kpi.data.period) {
          setPeriodInfo({
            from: kpi.data.period.from,
            to: kpi.data.period.to,
            prev_from: kpi.data.prev_period.from,
            prev_to: kpi.data.prev_period.to,
          })
        }
      }
      if (comp.success) setComparison(comp.data || [])
      if (ta.success) setTaData(Array.isArray(ta.data) ? ta.data : [])
      if (funnel.success) setFunnelData(funnel.data?.stages || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [buildQs, datePreset, country, platform, selectedAccount])

  // Aggregate KPIs when no country is selected
  const aggregatedKpi = kpiData.length > 0 ? kpiData.reduce((acc, k) => ({
    total_spend: acc.total_spend + k.total_spend,
    total_revenue: acc.total_revenue + k.total_revenue,
    impressions: acc.impressions + k.impressions,
    clicks: acc.clicks + k.clicks,
    conversions: acc.conversions + k.conversions,
    campaign_count: acc.campaign_count + k.campaign_count,
  }), { total_spend: 0, total_revenue: 0, impressions: 0, clicks: 0, conversions: 0, campaign_count: 0 }) : null

  const selectedKpi = country
    ? kpiData.find(k => k.country_code === country)
    : aggregatedKpi

  return (
    <div>
      {/* Header + Filters */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h1 className="text-2xl font-bold text-blue-600">Country Dashboard</h1>
        <div className="flex flex-wrap items-center gap-2">
          <select value={datePreset} onChange={e => setDatePreset(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="7d">Last 7 days</option>
            <option value="14d">Last 14 days</option>
            <option value="30d">Last 30 days</option>
            <option value="this_month">This month</option>
            <option value="last_month">Last month</option>
          </select>
          <select value={selectedAccount} onChange={e => setSelectedAccount(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Branches</option>
            {accounts.map(a => (
              <option key={a.id} value={a.id}>{a.account_name}</option>
            ))}
          </select>
          <select value={country} onChange={e => setCountry(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Markets</option>
            {countries.map(c => (
              <option key={c.code} value={c.code}>{c.name}</option>
            ))}
          </select>
          <select value={platform} onChange={e => setPlatform(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Platforms</option>
            <option value="meta">Meta</option>
            <option value="google">Google</option>
            <option value="tiktok">TikTok</option>
          </select>
          <select value={funnelStage} onChange={e => setFunnelStage(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Funnel</option>
            <option value="TOF">TOF (Cold)</option>
            <option value="MOF">MOF (Remarketing)</option>
            <option value="BOF">BOF (Bottom)</option>
          </select>
        </div>
      </div>

      {/* Period info */}
      {periodInfo && (
        <p className="text-xs text-gray-400 mb-4">
          {periodInfo.from} → {periodInfo.to} &nbsp;vs&nbsp; {periodInfo.prev_from} → {periodInfo.prev_to}
        </p>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64"><div className="text-gray-500">Loading dashboard...</div></div>
      ) : (
        <div className="space-y-6">
          {/* KPI Summary */}
          {selectedKpi && (
            <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
              {[
                { label: 'Spend', value: fmt(selectedKpi.total_spend), change: country ? kpiData.find(k => k.country_code === country)?.spend_change : null, inverse: true },
                { label: 'Revenue', value: fmt(selectedKpi.total_revenue), change: country ? kpiData.find(k => k.country_code === country)?.revenue_change : null, inverse: false },
                { label: 'ROAS', value: selectedKpi.total_spend ? (selectedKpi.total_revenue / selectedKpi.total_spend).toFixed(2) + 'x' : '0', change: country ? kpiData.find(k => k.country_code === country)?.roas_change : null, inverse: false },
                { label: 'CTR', value: selectedKpi.impressions ? ((selectedKpi.clicks / selectedKpi.impressions) * 100).toFixed(1) + '%' : '0%', change: country ? kpiData.find(k => k.country_code === country)?.ctr_change : null, inverse: false },
                { label: 'CPA', value: selectedKpi.conversions ? fmt(Math.round(selectedKpi.total_spend / selectedKpi.conversions)) : '--', change: null, inverse: true },
                { label: 'Campaigns', value: String(selectedKpi.campaign_count), change: null, inverse: false },
              ].map(kpi => (
                <div key={kpi.label} className="bg-white rounded-xl border border-gray-200 p-5">
                  <p className="text-xs text-gray-500 mb-1">{kpi.label}</p>
                  <p className="text-2xl font-bold text-gray-900">{kpi.value}</p>
                  <div className="mt-2"><ChangeTag change={kpi.change ?? null} inverseColor={kpi.inverse} /></div>
                </div>
              ))}
            </div>
          )}

          {/* TA Breakdown Table */}
          {country && taData.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b">
                <h2 className="text-sm font-semibold text-gray-700">
                  TA Breakdown — {countries.find(c => c.code === country)?.name || country}
                </h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-left py-3 px-4 text-gray-500 font-medium">TA</th>
                      <th className="text-left py-3 px-4 text-gray-500 font-medium">Funnel</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">Spend</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">Revenue</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">ROAS</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">CTR</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">CPA</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">Conv</th>
                    </tr>
                  </thead>
                  <tbody>
                    {taData
                      .sort((a, b) => b.roas - a.roas)
                      .map((row, i) => (
                        <tr key={`${row.ta}-${row.funnel_stage}`}
                          className={`border-b border-gray-50 ${row.is_remarketing ? 'bg-amber-50' : 'hover:bg-gray-50'}`}>
                          <td className="py-3 px-4 font-medium text-gray-900">{row.ta}</td>
                          <td className="py-3 px-4">
                            <span className={`text-xs px-2 py-0.5 rounded-full ${
                              row.funnel_stage === 'TOF' ? 'bg-blue-100 text-blue-700' :
                              row.funnel_stage === 'MOF' ? 'bg-amber-100 text-amber-700' :
                              row.funnel_stage === 'BOF' ? 'bg-green-100 text-green-700' :
                              'bg-gray-100 text-gray-700'
                            }`}>{row.funnel_stage}</span>
                          </td>
                          <td className="py-3 px-4 text-right">
                            <div>{fmt(row.spend)}</div>
                            <ChangeTag change={row.spend_change} inverseColor />
                          </td>
                          <td className="py-3 px-4 text-right">{fmt(row.revenue)}</td>
                          <td className="py-3 px-4 text-right">
                            <div className={`font-medium ${row.roas >= 1 ? 'text-green-600' : 'text-red-600'}`}>{row.roas.toFixed(2)}x</div>
                            <ChangeTag change={row.roas_change} />
                          </td>
                          <td className="py-3 px-4 text-right">{row.ctr.toFixed(1)}%</td>
                          <td className="py-3 px-4 text-right">{fmt(Math.round(row.cpa))}</td>
                          <td className="py-3 px-4 text-right">
                            <div>{row.conversions}</div>
                            <ChangeTag change={row.conversions_change} />
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Conversion Funnel */}
          {country && funnelData.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-sm font-semibold text-gray-700 mb-5">
                Conversion Funnel — {countries.find(c => c.code === country)?.name || country}
              </h2>
              <div className="space-y-3">
                {funnelData.map((stage, i) => {
                  const maxVal = Math.max(...funnelData.map(s => s.value), 1)
                  const widthPct = Math.max((stage.value / maxVal) * 100, 4)
                  return (
                    <div key={stage.name}>
                      {i > 0 && stage.drop_off_rate !== undefined && (
                        <div className="flex items-center gap-2 ml-4 mb-1">
                          <span className={`text-xs font-medium ${
                            stage.drop_off_rate > 35 ? 'text-green-600' :
                            stage.drop_off_rate > 15 ? 'text-yellow-600' : 'text-red-600'
                          }`}>{stage.drop_off_rate}%</span>
                        </div>
                      )}
                      <div className="flex items-center gap-4">
                        <div className="bg-blue-100 rounded-lg py-3 px-4 flex items-center justify-between transition-all"
                          style={{ width: `${widthPct}%`, minWidth: '180px' }}>
                          <span className="text-xs text-gray-600">{stage.name}</span>
                          <span className="text-lg font-bold text-gray-900 ml-2">{fmt(stage.value)}</span>
                        </div>
                        <ChangeTag change={stage.change} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Country Comparison Table */}
          {comparison.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-6 py-4 border-b">
                <h2 className="text-sm font-semibold text-gray-700">Country Comparison</h2>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="text-left py-3 px-4 text-gray-500 font-medium">Country</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">Spend</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">Revenue</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">ROAS</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">CTR</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">CPA</th>
                      <th className="text-right py-3 px-4 text-gray-500 font-medium">Conversions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparison.map((row) => (
                      <tr key={row.country_code} className="border-b border-gray-50 hover:bg-gray-50">
                        <td className="py-3 px-4">
                          <span className="font-medium text-gray-900">{row.country}</span>
                          <span className="text-xs text-gray-400 ml-1">({row.country_code})</span>
                        </td>
                        <td className="py-3 px-4 text-right">
                          <div>{fmt(row.total_spend)}</div>
                          <ChangeTag change={row.spend_change} inverseColor />
                        </td>
                        <td className="py-3 px-4 text-right">{fmt(row.total_revenue)}</td>
                        <td className="py-3 px-4 text-right">
                          <div className={`font-medium ${row.roas >= 1 ? 'text-green-600' : 'text-red-600'}`}>{row.roas.toFixed(2)}x</div>
                          <ChangeTag change={row.roas_change} />
                        </td>
                        <td className="py-3 px-4 text-right">{row.ctr.toFixed(1)}%</td>
                        <td className="py-3 px-4 text-right">{fmt(Math.round(row.cpa))}</td>
                        <td className="py-3 px-4 text-right">
                          <div>{row.conversions}</div>
                          <ChangeTag change={row.conversions_change} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {!loading && kpiData.length === 0 && (
            <div className="text-center py-12 text-gray-400">
              No data available. Run a sync first to populate metrics.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
