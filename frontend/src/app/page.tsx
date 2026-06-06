'use client'

import { useEffect, useMemo, useState, useCallback, useRef, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { ChevronRight } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import FunnelRecommendations from '@/components/FunnelRecommendations'
import {
  fmtMoney, fmtNum, ChangeTag, getDateRange, DATE_PRESETS,
  FUNNEL_STAGE_PILL, PLATFORM_PILL,
} from '@/components/dashboard/dashboardUtils'
import HorizontalBarBreakdown, { BreakdownItem } from '@/components/dashboard/HorizontalBarBreakdown'
import ActiveFiltersChips from '@/components/dashboard/ActiveFiltersChips'
import BranchPie, { BranchBreakdownRow } from '@/components/dashboard/BranchPie'
import CountryComparisonTable, { CountryKpi } from '@/components/dashboard/CountryComparisonTable'
import TaBreakdownTable, { TaRow } from '@/components/dashboard/TaBreakdownTable'
import CampaignBreakdownTable, { CampaignRow } from '@/components/dashboard/CampaignBreakdownTable'
import ActivityLogPanel from '@/components/dashboard/activity/ActivityLogPanel'
import ManualEntryModal from '@/components/dashboard/activity/ManualEntryModal'
import { TrendRow } from '@/components/dashboard/MetricTrendChart'
import BranchComparisonChart from '@/components/dashboard/BranchComparisonChart'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type FunnelStage = {
  name: string
  value: number
  change: number | null
  drop_off: number | null
  drop_off_change: number | null
}

type CountryOption = { code: string; name: string; adset_count: number }
type Branch = { name: string; currency: string }

type DailyRow = TrendRow

function DashboardInner() {
  const search = useSearchParams()
  // Deep-link inputs (read once on mount, then state owns them).
  const initialBranches = (search.get('branches') || '').split(',').map(s => s.trim()).filter(Boolean)
  const initialCountry = (search.get('country') || '').toUpperCase()
  const initialPlatform = (search.get('platform') || '').toLowerCase()
  const initialFunnel = (search.get('funnel') || '').toUpperCase()
  const initialRange = search.get('range') || '7d'
  const highlightCampaignId = search.get('campaign') || ''

  // -------------------- filter state --------------------
  const [country, setCountry] = useState(initialCountry)
  const [platform, setPlatform] = useState(initialPlatform)
  const [funnelStage, setFunnelStage] = useState(initialFunnel)
  const [selectedBranches, setSelectedBranches] = useState<string[]>(initialBranches)
  const [datePreset, setDatePreset] = useState(initialRange)
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [branchDropdownOpen, setBranchDropdownOpen] = useState(false)
  const [breakdownMetric, setBreakdownMetric] = useState<'spend' | 'roas' | 'conversions'>('spend')

  // -------------------- data state --------------------
  const [branches, setBranches] = useState<Branch[]>([])
  const [countries, setCountries] = useState<CountryOption[]>([])
  const [kpiItems, setKpiItems] = useState<CountryKpi[]>([])
  const [aggregateKpi, setAggregateKpi] = useState<CountryKpi | null>(null)
  const [responseCurrency, setResponseCurrency] = useState('VND')
  const [periodInfo, setPeriodInfo] = useState<{ from: string; to: string; prev_from: string; prev_to: string } | null>(null)
  const [daily, setDaily] = useState<DailyRow[]>([])
  const [funnelData, setFunnelData] = useState<FunnelStage[]>([])
  const [byBranch, setByBranch] = useState<BranchBreakdownRow[]>([])
  const [byPlatform, setByPlatform] = useState<BreakdownItem[]>([])
  const [byFunnel, setByFunnel] = useState<BreakdownItem[]>([])
  const [comparison, setComparison] = useState<CountryKpi[]>([])
  const [taData, setTaData] = useState<TaRow[]>([])
  const [campaignRows, setCampaignRows] = useState<CampaignRow[]>([])
  const [loading, setLoading] = useState(true)
  const [canEditAnalytics, setCanEditAnalytics] = useState(false)
  const [manualModalOpen, setManualModalOpen] = useState(false)
  const [activityRefreshKey, setActivityRefreshKey] = useState(0)

  // -------------------- derived --------------------
  const activeCurrency = useMemo(() => {
    if (selectedBranches.length === 0) return 'VND'
    const currencies = [...new Set(selectedBranches.map(b => branches.find(br => br.name === b)?.currency || 'VND'))]
    return currencies.length === 1 ? currencies[0] : 'VND'
  }, [selectedBranches, branches])

  const resolvedRange = useMemo(() => {
    if (datePreset === 'custom' && customFrom && customTo) {
      return { from: customFrom, to: customTo }
    }
    return getDateRange(datePreset)
  }, [datePreset, customFrom, customTo])

  const branchParam = selectedBranches.length > 0 ? selectedBranches.join(',') : ''

  // -------------------- fetchers --------------------
  // Build a query string honoring all dashboard filters.
  const buildQs = useCallback((extra?: Record<string, string>) => {
    const params = new URLSearchParams({ date_from: resolvedRange.from, date_to: resolvedRange.to })
    if (country) params.set('country', country)
    if (platform) params.set('platform', platform)
    if (funnelStage) params.set('funnel_stage', funnelStage)
    if (branchParam) params.set('branches', branchParam)
    if (extra) {
      for (const [k, v] of Object.entries(extra)) {
        if (v) params.set(k, v)
      }
    }
    return params.toString()
  }, [resolvedRange, country, platform, funnelStage, branchParam])

  // Bootstrap: branches list (once).
  useEffect(() => {
    fetch(`${API_BASE}/api/branches`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setBranches(d.data) })
      .catch(() => {})
  }, [])

  // Check whether the current user can add manual activity-log entries.
  useEffect(() => {
    apiFetch<{ is_admin: boolean; permissions?: Array<{ section: string; level: string }> }>('/api/auth/me')
      .then((res) => {
        if (!res.success || !res.data) return
        if (res.data.is_admin) { setCanEditAnalytics(true); return }
        const hasEdit = (res.data.permissions || []).some(p => p.section === 'analytics' && p.level === 'edit')
        setCanEditAnalytics(hasEdit)
      })
      .catch(() => {})
  }, [])

  // Countries list — refetch when branch scope changes (admin sees all by default).
  useEffect(() => {
    const qp = branchParam ? `?branches=${encodeURIComponent(branchParam)}` : ''
    fetch(`${API_BASE}/api/dashboard/country/countries${qp}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setCountries(d.data) })
      .catch(() => {})
  }, [branchParam])

  // Main data load — re-runs whenever any filter changes.
  useEffect(() => {
    if (datePreset === 'custom' && (!customFrom || !customTo)) return
    setLoading(true)

    const qs = buildQs()
    const opts = { credentials: 'include' as const }

    // Country drill-down endpoints only fire when a country is selected — they
    // require the param and would otherwise return 422.
    const taQs = country ? `country=${country}&${qs}` : null

    Promise.all([
      fetch(`${API_BASE}/api/dashboard/country?${qs}`, opts).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/country/daily-spend?${qs}`, opts).then(r => r.json()),
      // Reuse /dashboard/funnel which already accepts platform+branches; conversion
      // funnel for the selected country uses /country/funnel which needs ?country.
      country
        ? fetch(`${API_BASE}/api/dashboard/country/funnel?${taQs}`, opts).then(r => r.json())
        : fetch(`${API_BASE}/api/dashboard/funnel?${qs}`, opts).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/breakdown/branch?${qs}`, opts).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/breakdown/platform?${qs}`, opts).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/breakdown/funnel?${qs}`, opts).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/country/comparison?${qs}`, opts).then(r => r.json()),
      taQs ? fetch(`${API_BASE}/api/dashboard/country/ta-breakdown?${taQs}`, opts).then(r => r.json())
           : Promise.resolve({ success: true, data: [] }),
      fetch(`${API_BASE}/api/dashboard/country/campaigns?${qs}`, opts).then(r => r.json()),
    ]).then(([kpi, daily, funnel, brBranch, brPlat, brFun, comp, ta, camp]) => {
      if (kpi.success && kpi.data) {
        setKpiItems(kpi.data.items || [])
        setAggregateKpi(kpi.data.aggregate || null)
        setResponseCurrency(kpi.data.currency || 'VND')
        if (kpi.data.period && kpi.data.prev_period) {
          setPeriodInfo({
            from: kpi.data.period.from,
            to: kpi.data.period.to,
            prev_from: kpi.data.prev_period.from,
            prev_to: kpi.data.prev_period.to,
          })
        }
      }
      if (daily.success && daily.data) {
        setDaily((daily.data.series || []).map((s: Partial<TrendRow> & { date: string }) => ({
          date: s.date,
          spend: s.spend ?? 0, revenue: s.revenue ?? 0, roas: s.roas ?? 0,
          ctr: s.ctr ?? 0, cpa: s.cpa ?? 0, cpc: s.cpc ?? 0,
          cr: s.cr ?? 0, aov: s.aov ?? 0, conversions: s.conversions ?? 0,
        })))
      }
      if (funnel.success && funnel.data) {
        // /dashboard/funnel returns {steps:[{key,label,value,...}]}, /country/funnel
        // returns {stages:[{name,value,...}]}. Normalize to FunnelStage shape.
        const raw = funnel.data.stages || (funnel.data.steps || []).map((s: { label: string; value: number; change: number | null; drop_off: number | null; drop_off_change: number | null }) => ({
          name: s.label, value: s.value, change: s.change,
          drop_off: s.drop_off, drop_off_change: s.drop_off_change,
        }))
        setFunnelData(raw)
      }
      if (brBranch.success && brBranch.data) setByBranch(brBranch.data.items || [])
      if (brPlat.success && brPlat.data) {
        setByPlatform((brPlat.data.items || []).map((it: { platform: string; spend: number; revenue: number; conversions: number; roas: number; spend_change: number | null; roas_change: number | null; conversions_change: number | null }) => ({
          key: it.platform,
          label: it.platform.charAt(0).toUpperCase() + it.platform.slice(1),
          badgeClass: PLATFORM_PILL[it.platform],
          spend: it.spend, revenue: it.revenue, conversions: it.conversions,
          roas: it.roas,
          spend_change: it.spend_change, roas_change: it.roas_change,
          conversions_change: it.conversions_change,
        })))
      }
      if (brFun.success && brFun.data) {
        setByFunnel((brFun.data.items || []).map((it: { funnel_stage: string; spend: number; revenue: number; conversions: number; roas: number; spend_change: number | null; roas_change: number | null; conversions_change: number | null }) => ({
          key: it.funnel_stage,
          label: it.funnel_stage,
          badgeClass: FUNNEL_STAGE_PILL[it.funnel_stage] || FUNNEL_STAGE_PILL.Unknown,
          spend: it.spend, revenue: it.revenue, conversions: it.conversions,
          roas: it.roas,
          spend_change: it.spend_change, roas_change: it.roas_change,
          conversions_change: it.conversions_change,
        })))
      }
      if (comp.success) setComparison(comp.data || [])
      if (ta.success) setTaData(Array.isArray(ta.data) ? ta.data : [])
      if (camp.success) setCampaignRows(camp.data?.items || [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [buildQs, datePreset, customFrom, customTo, country, platform, funnelStage, branchParam])

  // Branch dropdown click-outside.
  const branchDropdownRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (branchDropdownRef.current && !branchDropdownRef.current.contains(e.target as Node)) {
        setBranchDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const toggleBranch = (name: string) => {
    setSelectedBranches(prev => prev.includes(name) ? prev.filter(b => b !== name) : [...prev, name])
  }

  // -------------------- aggregated KPIs --------------------
  // When ?country is set, we look at that single country's row (which already
  // carries period-over-period change). Otherwise we use `aggregate` from the
  // backend, which sums across all countries in the response and computes
  // change against the previous period — same shape as a single-country row.
  const selectedKpi = useMemo(() => {
    if (country) return kpiItems.find(k => k.country_code === country) || null
    return aggregateKpi
  }, [kpiItems, country, aggregateKpi])

  const kpiForChange = selectedKpi

  // -------------------- chips --------------------
  const chips = useMemo(() => {
    const out: { key: string; label: string; value: string; onClear: () => void }[] = []
    if (country) {
      out.push({
        key: 'country', label: 'Country',
        value: countries.find(c => c.code === country)?.name || country,
        onClear: () => setCountry(''),
      })
    }
    if (platform) {
      out.push({
        key: 'platform', label: 'Platform',
        value: platform.charAt(0).toUpperCase() + platform.slice(1),
        onClear: () => setPlatform(''),
      })
    }
    if (funnelStage) {
      out.push({
        key: 'funnel', label: 'Funnel',
        value: funnelStage,
        onClear: () => setFunnelStage(''),
      })
    }
    selectedBranches.forEach(b => {
      out.push({
        key: `branch-${b}`, label: 'Branch',
        value: b,
        onClear: () => setSelectedBranches(prev => prev.filter(x => x !== b)),
      })
    })
    return out
  }, [country, platform, funnelStage, selectedBranches, countries])

  const resetAll = () => {
    setCountry(''); setPlatform(''); setFunnelStage('')
    setSelectedBranches([])
  }

  // -------------------- render --------------------
  if (loading && !selectedKpi) {
    return <div className="flex items-center justify-center h-64"><div className="text-gray-500">Loading dashboard...</div></div>
  }

  const funnelMax = funnelData.length > 0 ? Math.max(...funnelData.map(s => s.value), 1) : 1

  return (
    <div>
      {/* Sticky header + filter bar — stays pinned so filters remain usable
          while scrolling. -mx/-mt cancel the <main> padding for a full-bleed
          bar; px/pt restore the inner spacing. */}
      <div className="sticky top-0 z-30 -mx-6 -mt-6 px-6 pt-6 pb-3 mb-4 bg-gray-50/95 backdrop-blur border-b border-gray-200">
      {/* Header + filter bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <h1 className="text-2xl font-bold text-blue-600">ADS Performance</h1>
        <div className="flex flex-wrap items-center gap-2">
          <select value={datePreset} onChange={e => setDatePreset(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {DATE_PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
          {datePreset === 'custom' && (
            <>
              <input type="date" value={customFrom} onChange={e => setCustomFrom(e.target.value)}
                className="px-2 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <span className="text-gray-400">→</span>
              <input type="date" value={customTo} onChange={e => setCustomTo(e.target.value)}
                className="px-2 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </>
          )}
          <div className="relative" ref={branchDropdownRef}>
            <button
              onClick={() => setBranchDropdownOpen(o => !o)}
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
              <div className="absolute z-50 mt-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg py-1 right-0">
                {selectedBranches.length > 0 && (
                  <button
                    onClick={() => setSelectedBranches([])}
                    className="w-full px-3 py-1.5 text-xs text-blue-600 hover:bg-gray-50 text-left"
                  >Clear all</button>
                )}
                {branches.map(b => (
                  <label key={b.name} className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm">
                    <input type="checkbox" checked={selectedBranches.includes(b.name)} onChange={() => toggleBranch(b.name)}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
                    <span>{b.name}</span>
                    <span className="text-gray-400 text-xs ml-auto">{b.currency}</span>
                  </label>
                ))}
              </div>
            )}
          </div>
          <select value={country} onChange={e => setCountry(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">All Countries</option>
            {countries.map(c => <option key={c.code} value={c.code}>{c.name}</option>)}
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

      {/* Active filter chips */}
      <div className="[&>div]:mb-0">
        <ActiveFiltersChips chips={chips} onResetAll={resetAll} />
      </div>

      {/* Period info */}
      {periodInfo && (
        <p className="text-xs text-gray-400 mt-2">
          {periodInfo.from} → {periodInfo.to} &nbsp;vs&nbsp; {periodInfo.prev_from} → {periodInfo.prev_to}
        </p>
      )}
      </div>{/* end sticky header */}

      {/* KPI summary — headline + ROAS decomposition. Shown for both country=
          empty (aggregated) and country=set (per-country). The decomposition
          row is only meaningful with a single country since CR/AOV/CPC don't
          aggregate cleanly across countries. */}
      {selectedKpi && (() => {
        const cr = selectedKpi.clicks ? (selectedKpi.conversions / selectedKpi.clicks) * 100 : 0
        const aov = selectedKpi.conversions ? selectedKpi.total_revenue / selectedKpi.conversions : 0
        const cpc = selectedKpi.clicks ? selectedKpi.total_spend / selectedKpi.clicks : 0
        const roas = selectedKpi.total_spend ? selectedKpi.total_revenue / selectedKpi.total_spend : 0
        const ctr = selectedKpi.impressions ? (selectedKpi.clicks / selectedKpi.impressions) * 100 : 0
        const cpa = selectedKpi.conversions ? selectedKpi.total_spend / selectedKpi.conversions : 0
        const headline = [
          { label: `Spend (${responseCurrency})`, value: fmtMoney(selectedKpi.total_spend, responseCurrency), change: kpiForChange?.spend_change ?? null, inverse: true },
          { label: `Revenue (${responseCurrency})`, value: fmtMoney(selectedKpi.total_revenue, responseCurrency), change: kpiForChange?.revenue_change ?? null, inverse: false },
          { label: 'ROAS', value: roas ? roas.toFixed(2) + 'x' : '0', change: kpiForChange?.roas_change ?? null, inverse: false },
          { label: 'CTR', value: ctr ? ctr.toFixed(1) + '%' : '0%', change: kpiForChange?.ctr_change ?? null, inverse: false },
          { label: `CPA (${responseCurrency})`, value: cpa ? fmtMoney(Math.round(cpa), responseCurrency) : '--', change: kpiForChange?.cpa_change ?? null, inverse: true },
          { label: 'Conversions', value: fmtNum(selectedKpi.conversions), change: kpiForChange?.conversions_change ?? null, inverse: false },
        ]
        // ROAS decomposition (CR × AOV / CPC). Always shown — when no country
        // is selected we use the cross-country aggregate (totals re-derive
        // ratios cleanly since they're computed from summed counters).
        const decomp = [
          { label: 'CR (Conversion Rate)', value: cr ? cr.toFixed(2) + '%' : '--', change: kpiForChange?.cr_change ?? null, inverse: false },
          { label: `AOV (${responseCurrency})`, value: aov ? fmtMoney(Math.round(aov), responseCurrency) : '--', change: kpiForChange?.aov_change ?? null, inverse: false },
          { label: `CPC (${responseCurrency})`, value: cpc ? fmtMoney(Math.round(cpc), responseCurrency) : '--', change: kpiForChange?.cpc_change ?? null, inverse: true },
        ]

        const Card = ({ k }: { k: typeof headline[number] }) => (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <p className="text-xs text-gray-500 mb-1 truncate">{k.label}</p>
            <p className="text-2xl font-bold text-gray-900">{k.value}</p>
            <div className="mt-2"><ChangeTag change={k.change} inverseColor={k.inverse} /></div>
          </div>
        )

        return (
          <div className="space-y-4 mb-6">
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
              {headline.map(k => <Card key={k.label} k={k} />)}
            </div>
            <div>
              <div className="flex items-center gap-2 mb-2 text-[11px] uppercase tracking-wider text-gray-400 font-semibold">
                ROAS decomposition
                <span className="text-gray-300 normal-case font-normal tracking-normal">ROAS = CR × AOV / CPC</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {decomp.map(k => <Card key={k.label} k={k} />)}
              </div>
            </div>
          </div>
        )
      })()}

      {/* Cross-filter breakdowns — pies on one row, bars on the next so each
          pair sits side-by-side at the same width. */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <BranchPie
          title="By Branch (Cost)"
          rows={byBranch as BranchBreakdownRow[]}
          valueKey="spend_vnd"
          selectedBranches={selectedBranches}
          onToggle={toggleBranch}
          valueFormatter={(v) => fmtMoney(v, 'VND')}
        />
        <BranchPie
          title="By Branch (Conversions)"
          rows={byBranch as BranchBreakdownRow[]}
          valueKey="conversions"
          selectedBranches={selectedBranches}
          onToggle={toggleBranch}
          valueFormatter={(v) => fmtNum(v)}
        />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <HorizontalBarBreakdown
          title="By Platform"
          items={byPlatform}
          currency={responseCurrency}
          selectedKey={platform}
          onSelect={(k) => setPlatform(prev => prev === k ? '' : k)}
          metric={breakdownMetric}
          onMetricChange={setBreakdownMetric}
        />
        <HorizontalBarBreakdown
          title="By Funnel"
          items={byFunnel}
          currency={responseCurrency}
          selectedKey={funnelStage}
          onSelect={(k) => setFunnelStage(prev => prev === k ? '' : k)}
          metric={breakdownMetric}
        />
      </div>

      {/* Branch comparison — ROAS / CPA / CTR side-by-side across branches */}
      {byBranch.length > 0 && (
        <div className="mb-6">
          <BranchComparisonChart rows={byBranch as (BranchBreakdownRow & { roas: number; cpa: number; ctr: number })[]} />
        </div>
      )}

      {/* Country comparison — always shown, click row to filter */}
      {comparison.length > 0 && (
        <div className="mb-6">
          <CountryComparisonTable
            rows={comparison}
            currency={responseCurrency}
            selectedCountry={country}
            onSelectCountry={setCountry}
          />
        </div>
      )}

      {/* Conversion funnel (always shown — global when country empty, per-country otherwise) */}
      {funnelData.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <h2 className="text-sm font-semibold text-gray-700 mb-5">
            Conversion Funnel
            {country && <span className="text-gray-400 font-normal ml-2">— {countries.find(c => c.code === country)?.name || country}</span>}
          </h2>
          <div className="space-y-3">
            {funnelData.map((stage, i) => {
              const widthPct = Math.max((stage.value / funnelMax) * 100, 4)
              return (
                <div key={`${stage.name}-${i}`}>
                  {i > 0 && (
                    <div className="flex items-center gap-2 ml-4 mb-1">
                      <ChevronRight className="w-3 h-3 text-gray-300" />
                      {stage.drop_off !== null && (
                        <span className="text-xs text-gray-400">
                          {(stage.drop_off * 100).toFixed(1)}% drop-off
                        </span>
                      )}
                      {stage.drop_off_change !== null && (
                        <ChangeTag change={stage.drop_off_change} inverseColor />
                      )}
                    </div>
                  )}
                  <div className="flex items-center gap-4">
                    <div className="bg-blue-100 rounded-lg py-3 px-4 flex items-center justify-between transition-all"
                      style={{ width: `${widthPct}%`, minWidth: '180px' }}>
                      <span className="text-xs text-gray-600">{stage.name}</span>
                      <span className="text-lg font-bold text-gray-900 ml-2">{fmtNum(stage.value)}</span>
                    </div>
                    <ChangeTag change={stage.change} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Country drill-down: TA breakdown */}
      {country && taData.length > 0 && (
        <div className="mb-6">
          <TaBreakdownTable
            rows={taData}
            currency={responseCurrency}
            title={`TA Breakdown — ${countries.find(c => c.code === country)?.name || country}`}
          />
        </div>
      )}

      {/* Campaign breakdown — always shown, scoped to active filters */}
      {campaignRows.length > 0 && (
        <div className="mb-6">
          <CampaignBreakdownTable
            rows={campaignRows}
            currency={responseCurrency}
            highlightId={highlightCampaignId}
            title={
              country
                ? `Campaign Breakdown — ${countries.find(c => c.code === country)?.name || country}`
                : 'Campaign Breakdown'
            }
          />
        </div>
      )}

      {/* Metric trends + activity log (combined) — tick any metrics to overlay
          their lines, with change-markers showing what changed each day so the
          user can correlate spend/ROAS swings to specific actions. */}
      <div className="mb-6">
        <ActivityLogPanel
          country={country}
          branches={branchParam}
          platform={platform}
          dateFrom={resolvedRange.from}
          dateTo={resolvedRange.to}
          canEdit={canEditAnalytics}
          onAddManual={() => setManualModalOpen(true)}
          refreshKey={activityRefreshKey}
          trend={daily}
          currency={responseCurrency}
        />
      </div>

      {/* AI funnel recommendations — deep-links back into this page with filters set */}
      <FunnelRecommendations
        branches={branchParam}
        platform={platform}
        dateFrom={resolvedRange.from}
        dateTo={resolvedRange.to}
      />

      {!loading && kpiItems.length === 0 && (
        <div className="text-center py-12 text-gray-400">
          No data available. Run a sync first to populate metrics.
        </div>
      )}

      {manualModalOpen && (
        <ManualEntryModal
          open={manualModalOpen}
          onClose={() => setManualModalOpen(false)}
          onCreated={() => {
            setActivityRefreshKey(k => k + 1)
            setManualModalOpen(false)
          }}
          defaultCountry={country || null}
          defaultBranch={selectedBranches.length === 1 ? selectedBranches[0] : null}
          branches={branches}
          countries={countries}
        />
      )}
    </div>
  )
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center h-64"><div className="text-gray-500">Loading...</div></div>}>
      <DashboardInner />
    </Suspense>
  )
}
