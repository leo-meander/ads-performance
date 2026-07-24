'use client'

import { useEffect, useMemo, useState, useCallback, useRef, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  ChevronRight, Search, X,
  TrendingUp, AlertTriangle, Target, Activity, ArrowRight,
  Filter as FilterIcon,
} from 'lucide-react'
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
import { TrendRow } from '@/components/dashboard/MetricTrendChart'
import BranchComparisonChart from '@/components/dashboard/BranchComparisonChart'
import type { ChangeLogItem } from '@/components/dashboard/activity/ActivityLogPanel'
import {
  buildInsights,
  buildNextActions,
  diagnoseConversionFunnel,
  MIN_SPEND_SHARE,
  type FunnelStep,
  type CampaignInsight,
  type ApplyOption,
} from '@/components/action-needed/analysis'
import SurfApplyModal from '@/components/action-needed/SurfApplyModal'

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
type ChangelogResponse = { items: ChangeLogItem[]; total: number }

const SEVERITY_STYLES: Record<string, string> = {
  high: 'bg-red-100 text-red-700 border-red-200',
  medium: 'bg-amber-100 text-amber-700 border-amber-200',
  low: 'bg-gray-100 text-gray-600 border-gray-200',
}

const LEAK_PILL: Record<string, string> = {
  'Impression → Click': 'bg-blue-100 text-blue-700',
  'Post-click · 0 bookings': 'bg-red-100 text-red-700',
  'Click cost · CPC': 'bg-amber-100 text-amber-700',
  Profitability: 'bg-gray-100 text-gray-600',
}

function Metric({ label, value, change, inverse }: {
  label: string
  value: string
  change?: number | null
  inverse?: boolean
}) {
  return (
    <div>
      <p className="text-[11px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-sm font-semibold text-gray-900">{value}</p>
      {change !== undefined && <ChangeTag change={change} inverseColor={inverse} />}
    </div>
  )
}

function ActivityChips({ items }: { items: ChangeLogItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-xs text-gray-400 italic">
        No Activity Log changes tied to this campaign in this period.
      </p>
    )
  }
  return (
    <ul className="space-y-1.5">
      {items.slice(0, 4).map((it) => (
        <li key={it.id} className="text-xs">
          <span className="text-gray-400">{it.occurred_at.slice(0, 10)}</span>{' '}
          <span className="font-medium text-gray-800">{it.title}</span>
          {it.before_value && it.after_value && (
            <span className="ml-1 text-gray-500">
              {Object.keys(it.after_value)
                .filter((k) => JSON.stringify(it.before_value?.[k]) !== JSON.stringify(it.after_value?.[k]))
                .slice(0, 3)
                .map((k) => (
                  <span key={k} className="inline-flex items-center gap-0.5 ml-1">
                    <span className="text-gray-400">{k}:</span>
                    <span className="line-through text-red-500">{String(it.before_value?.[k])}</span>
                    <ArrowRight className="w-2.5 h-2.5 text-gray-300" />
                    <span className="text-emerald-600">{String(it.after_value?.[k])}</span>
                  </span>
                ))}
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}

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
  const [campaignType, setCampaignType] = useState<'all' | 'sale' | 'lead'>('all')
  const [country, setCountry] = useState(initialCountry)
  const [platform, setPlatform] = useState(initialPlatform)
  const [funnelStage, setFunnelStage] = useState(initialFunnel)
  const [selectedBranches, setSelectedBranches] = useState<string[]>(initialBranches)
  const [datePreset, setDatePreset] = useState(initialRange)
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [branchDropdownOpen, setBranchDropdownOpen] = useState(false)
  const [breakdownMetric, setBreakdownMetric] = useState<'spend' | 'roas' | 'conversions'>('spend')

  // Campaign search combobox
  const [campaignSearch, setCampaignSearch] = useState('')
  const [campaignDropdownOpen, setCampaignDropdownOpen] = useState(false)
  const campaignSearchRef = useRef<HTMLDivElement>(null)

  // -------------------- data state --------------------
  const [branches, setBranches] = useState<Branch[]>([])
  const [countries, setCountries] = useState<CountryOption[]>([])
  const [kpiItems, setKpiItems] = useState<CountryKpi[]>([])
  const [aggregateKpi, setAggregateKpi] = useState<CountryKpi | null>(null)
  const [responseCurrency, setResponseCurrency] = useState('VND')
  const [periodInfo, setPeriodInfo] = useState<{ from: string; to: string; prev_from: string; prev_to: string } | null>(null)
  const [daily, setDaily] = useState<DailyRow[]>([])
  const [prevDaily, setPrevDaily] = useState<TrendRow[]>([])
  const [funnelData, setFunnelData] = useState<FunnelStage[]>([])
  const [funnel, setFunnel] = useState<FunnelStep[]>([])  // raw steps for analysis
  const [byBranch, setByBranch] = useState<BranchBreakdownRow[]>([])
  const [byPlatform, setByPlatform] = useState<BreakdownItem[]>([])
  const [byFunnel, setByFunnel] = useState<BreakdownItem[]>([])
  const [comparison, setComparison] = useState<CountryKpi[]>([])
  const [taData, setTaData] = useState<TaRow[]>([])
  const [campaignRows, setCampaignRows] = useState<CampaignRow[]>([])
  const [changelog, setChangelog] = useState<ChangeLogItem[]>([])
  const [loading, setLoading] = useState(true)

  // Per-campaign apply/mark-done status
  const [actionState, setActionState] = useState<
    Record<string, { status: 'loading' | 'done' | 'error'; msg?: string; tail?: string }>
  >({})

  // SURF modal
  const [surfModal, setSurfModal] = useState<{
    insight: CampaignInsight
    action: 'raise_budget' | 'cut_budget'
  } | null>(null)

  // Funnel view mode
  const [funnelView, setFunnelView] = useState<'single' | 'by-branch' | 'by-campaign'>('single')
  const [branchFunnels, setBranchFunnels] = useState<Record<string, FunnelStep[]>>({})
  const [branchFunnelLoading, setBranchFunnelLoading] = useState(false)
  const [campaignFunnelTable, setCampaignFunnelTable] = useState<Record<string, FunnelStep[]>>({})
  const [campaignFunnelTableLoading, setCampaignFunnelTableLoading] = useState(false)
  const [campaignFunnel, setCampaignFunnel] = useState<FunnelStep[]>([])
  const [campaignFunnelLoading, setCampaignFunnelLoading] = useState(false)

  // Benchmark comparison
  const [comparisonMode, setComparisonMode] = useState<'prev' | 'benchmark'>('prev')
  const [benchmarkFunnel, setBenchmarkFunnel] = useState<FunnelStep[]>([])
  const [benchmarkLoading, setBenchmarkLoading] = useState(false)

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
  const buildQs = useCallback((extra?: Record<string, string>) => {
    const params = new URLSearchParams({ date_from: resolvedRange.from, date_to: resolvedRange.to })
    if (country) params.set('country', country)
    if (platform) params.set('platform', platform)
    if (funnelStage) params.set('funnel_stage', funnelStage)
    if (branchParam) params.set('branches', branchParam)
    if (campaignType === 'lead') params.set('campaign_type', 'lead')
    else if (campaignType === 'sale') params.set('campaign_type', 'sale')
    if (extra) {
      for (const [k, v] of Object.entries(extra)) {
        if (v) params.set(k, v)
      }
    }
    return params.toString()
  }, [resolvedRange, country, platform, funnelStage, branchParam, campaignType])

  // Bootstrap: branches list (once).
  useEffect(() => {
    fetch(`${API_BASE}/api/branches`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setBranches(d.data) })
      .catch(() => {})
  }, [])

  // Countries list — refetch when branch scope changes.
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

    const taQs = country ? `country=${country}&${qs}` : null

    Promise.all([
      fetch(`${API_BASE}/api/dashboard/country?${qs}`, opts).then(r => r.json()),
      fetch(`${API_BASE}/api/dashboard/country/daily-spend?${qs}`, opts).then(r => r.json()),
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
      apiFetch<ChangelogResponse>(`/api/dashboard/country/changelog?${qs}&limit=200`),
    ]).then(([kpi, daily, funnelRes, brBranch, brPlat, brFun, comp, ta, camp, log]) => {
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
        const mapSeries = (arr: (Partial<TrendRow> & { date: string })[]) => arr.map(s => ({
          date: s.date,
          spend: s.spend ?? 0, revenue: s.revenue ?? 0, roas: s.roas ?? 0,
          ctr: s.ctr ?? 0, cpa: s.cpa ?? 0, cpc: s.cpc ?? 0,
          cr: s.cr ?? 0, aov: s.aov ?? 0, conversions: s.conversions ?? 0,
          do_imp_click: s.do_imp_click ?? 0,
          do_click_search: s.do_click_search ?? 0,
          do_search_cart: s.do_search_cart ?? 0,
          do_cart_checkout: s.do_cart_checkout ?? 0,
          do_checkout_book: s.do_checkout_book ?? 0,
        }))
        setDaily(mapSeries(daily.data.series || []))
        setPrevDaily(mapSeries(daily.data.prev_series || []))
      }
      if (funnelRes.success && funnelRes.data) {
        const raw = funnelRes.data.stages || (funnelRes.data.steps || []).map((s: { label: string; value: number; change: number | null; drop_off: number | null; drop_off_change: number | null }) => ({
          name: s.label, value: s.value, change: s.change,
          drop_off: s.drop_off, drop_off_change: s.drop_off_change,
        }))
        setFunnelData(raw)
        // Capture raw FunnelStep[] for analysis (only available from /dashboard/funnel, not /country/funnel)
        if (!country && funnelRes.data.steps) {
          setFunnel(funnelRes.data.steps)
        } else {
          setFunnel([])
        }
      }
      if (brBranch.success && brBranch.data) setByBranch(brBranch.data.items || [])
      if (brPlat.success && brPlat.data) {
        setByPlatform((brPlat.data.items || []).map((it: { platform: string; spend: number; revenue: number; conversions: number; leads: number; roas: number; spend_change: number | null; roas_change: number | null; conversions_change: number | null }) => ({
          key: it.platform,
          label: it.platform.charAt(0).toUpperCase() + it.platform.slice(1),
          badgeClass: PLATFORM_PILL[it.platform],
          spend: it.spend, revenue: it.revenue, conversions: it.conversions, leads: it.leads ?? 0,
          roas: it.roas,
          spend_change: it.spend_change, roas_change: it.roas_change,
          conversions_change: it.conversions_change,
        })))
      }
      if (brFun.success && brFun.data) {
        setByFunnel((brFun.data.items || []).map((it: { funnel_stage: string; spend: number; revenue: number; conversions: number; leads: number; roas: number; spend_change: number | null; roas_change: number | null; conversions_change: number | null }) => ({
          key: it.funnel_stage,
          label: it.funnel_stage,
          badgeClass: FUNNEL_STAGE_PILL[it.funnel_stage] || FUNNEL_STAGE_PILL.Unknown,
          spend: it.spend, revenue: it.revenue, conversions: it.conversions, leads: it.leads ?? 0,
          roas: it.roas,
          spend_change: it.spend_change, roas_change: it.roas_change,
          conversions_change: it.conversions_change,
        })))
      }
      if (comp.success) setComparison(comp.data || [])
      if (ta.success) setTaData(Array.isArray(ta.data) ? ta.data : [])
      if (camp.success) setCampaignRows(camp.data?.items || [])
      setChangelog(log.success && log.data ? log.data.items || [] : [])
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [buildQs, datePreset, customFrom, customTo, country, platform, funnelStage, branchParam, campaignType])

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

  // Campaign search click-outside.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (campaignSearchRef.current && !campaignSearchRef.current.contains(e.target as Node))
        setCampaignDropdownOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  // Benchmark funnel: 90-day window, fetched lazily when user switches to benchmark mode.
  useEffect(() => {
    if (comparisonMode !== 'benchmark') return
    let cancelled = false
    setBenchmarkLoading(true)
    const today = new Date()
    const d90ago = new Date(today)
    d90ago.setDate(today.getDate() - 89)
    const fmt = (d: Date) => d.toISOString().slice(0, 10)
    const params = new URLSearchParams({ date_from: fmt(d90ago), date_to: fmt(today) })
    if (platform) params.set('platform', platform)
    if (branchParam) params.set('branches', branchParam)
    if (campaignType === 'lead') params.set('campaign_type', 'lead')
    else if (campaignType === 'sale') params.set('campaign_type', 'sale')
    apiFetch<{ steps: FunnelStep[] }>(`/api/dashboard/funnel?${params}`)
      .then((res) => {
        if (cancelled) return
        setBenchmarkFunnel(res.success && res.data ? res.data.steps || [] : [])
      })
      .catch(() => { if (!cancelled) setBenchmarkFunnel([]) })
      .finally(() => { if (!cancelled) setBenchmarkLoading(false) })
    return () => { cancelled = true }
  }, [comparisonMode, branchParam, platform, campaignType])

  // Declared here (before effects) to avoid temporal dead zone — effects below reference it.
  const filteredRows = useMemo(() => {
    if (!campaignSearch.trim()) return campaignRows
    const q = campaignSearch.toLowerCase()
    return campaignRows.filter((r) => r.campaign_name.toLowerCase().includes(q))
  }, [campaignRows, campaignSearch])

  // Campaign-scoped funnel (when search active).
  useEffect(() => {
    if (!campaignSearch.trim() || filteredRows.length === 0) { setCampaignFunnel([]); return }
    let cancelled = false
    setCampaignFunnelLoading(true)
    const ids = filteredRows.map((r) => r.campaign_id).join(',')
    const params = new URLSearchParams(buildQs())
    params.set('campaign_ids', ids)
    apiFetch<{ steps: FunnelStep[] }>(`/api/dashboard/funnel?${params}`)
      .then((res) => { if (!cancelled) setCampaignFunnel(res.success && res.data ? res.data.steps || [] : []) })
      .catch(() => { if (!cancelled) setCampaignFunnel([]) })
      .finally(() => { if (!cancelled) setCampaignFunnelLoading(false) })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignSearch, filteredRows, buildQs])

  // By-branch funnel.
  useEffect(() => {
    if (funnelView !== 'by-branch') { setBranchFunnels({}); return }
    const targetBranches = selectedBranches.length > 0 ? selectedBranches : branches.map((b) => b.name)
    if (targetBranches.length === 0) return
    let cancelled = false
    setBranchFunnelLoading(true)
    const baseQs = buildQs()
    const campaignIdParam = campaignSearch.trim() && filteredRows.length > 0
      ? filteredRows.map((r) => r.campaign_id).join(',')
      : null
    Promise.all(
      targetBranches.map(async (branchName) => {
        const params = new URLSearchParams(baseQs)
        params.set('branches', branchName)
        if (campaignIdParam) params.set('campaign_ids', campaignIdParam)
        const res = await apiFetch<{ steps: FunnelStep[] }>(`/api/dashboard/funnel?${params}`)
        return [branchName, res.success && res.data ? res.data.steps || [] : []] as [string, FunnelStep[]]
      }),
    )
      .then((results) => { if (!cancelled) setBranchFunnels(Object.fromEntries(results)) })
      .catch(() => { if (!cancelled) setBranchFunnels({}) })
      .finally(() => { if (!cancelled) setBranchFunnelLoading(false) })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [funnelView, selectedBranches, branches, campaignSearch, filteredRows, buildQs])

  // By-campaign funnel.
  useEffect(() => {
    if (funnelView !== 'by-campaign') { setCampaignFunnelTable({}); return }
    const targets = [...filteredRows].sort((a, b) => b.spend - a.spend).slice(0, 10)
    if (targets.length === 0) return
    let cancelled = false
    setCampaignFunnelTableLoading(true)
    const baseQs = buildQs()
    Promise.all(
      targets.map(async (row) => {
        const params = new URLSearchParams(baseQs)
        params.set('campaign_ids', row.campaign_id)
        const res = await apiFetch<{ steps: FunnelStep[] }>(`/api/dashboard/funnel?${params}`)
        return [row.campaign_name, res.success && res.data ? res.data.steps || [] : []] as [string, FunnelStep[]]
      }),
    )
      .then((results) => { if (!cancelled) setCampaignFunnelTable(Object.fromEntries(results)) })
      .catch(() => { if (!cancelled) setCampaignFunnelTable({}) })
      .finally(() => { if (!cancelled) setCampaignFunnelTableLoading(false) })
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [funnelView, filteredRows, buildQs])

  const toggleBranch = (name: string) => {
    setSelectedBranches(prev => prev.includes(name) ? prev.filter(b => b !== name) : [...prev, name])
  }

  // -------------------- aggregated KPIs --------------------
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

  // -------------------- analysis memos --------------------
  const money = useCallback((n: number) => fmtMoney(n, activeCurrency || responseCurrency), [activeCurrency, responseCurrency])

  const insights = useMemo(() => buildInsights(campaignRows, changelog, money), [campaignRows, changelog, money])

  const filteredInsights = useMemo(() => {
    if (!campaignSearch.trim()) return insights
    const q = campaignSearch.toLowerCase()
    return insights.filter((i) => i.row.campaign_name.toLowerCase().includes(q))
  }, [insights, campaignSearch])

  const displayFunnel = useMemo(
    () => (campaignSearch.trim() && campaignFunnel.length > 0 ? campaignFunnel : funnel),
    [campaignSearch, campaignFunnel, funnel],
  )

  const funnelDiagAN = useMemo(() => diagnoseConversionFunnel(displayFunnel), [displayFunnel])

  const nextActions = useMemo(() => buildNextActions(filteredInsights, funnelDiagAN), [filteredInsights, funnelDiagAN])

  const winners = useMemo(
    () =>
      filteredInsights
        .filter((i) => i.verdict === 'winner' && i.row.spend > 0)
        .sort((a, b) => b.row.roas - a.row.roas),
    [filteredInsights],
  )
  const losers = useMemo(
    () =>
      filteredInsights
        .filter((i) => i.verdict !== 'winner' && i.spendShare >= MIN_SPEND_SHARE)
        .sort((a, b) => b.bleed - a.bleed || b.row.spend - a.row.spend),
    [filteredInsights],
  )

  // -------------------- action handlers --------------------
  const handleApply = useCallback(async (insight: CampaignInsight, opt: ApplyOption) => {
    const cid = insight.row.campaign_id
    if (opt.kind === 'auto') {
      if (opt.action === 'raise_budget' || opt.action === 'cut_budget') {
        setSurfModal({ insight, action: opt.action })
        return
      }
      if (!window.confirm(
        `This will PAUSE "${insight.row.campaign_name}" on Meta (live ads). Continue?`,
      )) return
      setActionState((s) => ({ ...s, [cid]: { status: 'loading' } }))
      const res = await apiFetch<{ campaign_id: string }>('/api/action-needed/apply', {
        method: 'POST',
        body: JSON.stringify({ campaign_id: cid, action: opt.action, confirm: true }),
      })
      setActionState((s) => ({
        ...s,
        [cid]: res.success ? { status: 'done', msg: opt.label } : { status: 'error', msg: res.error || 'Failed' },
      }))
    } else if (opt.kind === 'enroll') {
      setActionState((s) => ({ ...s, [cid]: { status: 'loading' } }))
      const res = await apiFetch<{
        tactic_name: string; created: boolean; already_enrolled: boolean
        dry_run: boolean; campaign_count: number
      }>('/api/tactics/enroll-campaign', {
        method: 'POST',
        body: JSON.stringify({ campaign_id: cid, preset_type: opt.preset }),
      })
      setActionState((s) => ({
        ...s,
        [cid]: res.success
          ? {
              status: 'done',
              msg: res.data?.already_enrolled
                ? `Already in "${res.data.tactic_name}"`
                : `Enrolled in "${res.data?.tactic_name}"${res.data?.dry_run ? ' (dry-run)' : ''}`,
              tail: res.data?.dry_run ? 'bật live ở /tactics' : 'managed on /tactics',
            }
          : { status: 'error', msg: res.error || 'Failed' },
      }))
    } else {
      const title = insight.leakLabel ? `${insight.leakLabel} — ${insight.row.campaign_name}` : insight.row.campaign_name
      setActionState((s) => ({ ...s, [cid]: { status: 'loading' } }))
      const res = await apiFetch('/api/action-needed/mark-done', {
        method: 'POST',
        body: JSON.stringify({ campaign_id: cid, platform: insight.row.platform, title }),
      })
      setActionState((s) => ({
        ...s,
        [cid]: res.success ? { status: 'done', msg: 'Marked done' } : { status: 'error', msg: res.error || 'Failed' },
      }))
    }
  }, [])

  const handleSurfApplied = useCallback((cid: string, msg: string) => {
    setActionState((s) => ({ ...s, [cid]: { status: 'done', msg } }))
  }, [])

  const renderActions = (insight: CampaignInsight) => {
    const st = actionState[insight.row.campaign_id]
    if (st?.status === 'done') {
      return <p className="text-xs text-green-600 mt-2">✓ {st.msg} · {st.tail ?? 'logged to Activity Log'}</p>
    }
    return (
      <div className="mt-2">
        <div className="flex flex-wrap gap-2 print:hidden">
          {insight.applyOptions.map((opt) => (
            <button
              key={opt.kind === 'auto' ? opt.action : opt.kind === 'enroll' ? `enroll:${opt.preset}` : 'manual'}
              onClick={() => handleApply(insight, opt)}
              disabled={st?.status === 'loading'}
              className={`text-xs px-2.5 py-1 rounded-md border disabled:opacity-50 ${
                opt.kind === 'auto'
                  ? 'border-blue-200 text-blue-700 bg-blue-50 hover:bg-blue-100'
                  : opt.kind === 'enroll'
                    ? 'border-emerald-200 text-emerald-700 bg-emerald-50 hover:bg-emerald-100'
                    : 'border-gray-200 text-gray-600 bg-white hover:bg-gray-50'
              }`}
            >
              {st?.status === 'loading' ? '…' : opt.label}
            </button>
          ))}
        </div>
        {st?.status === 'error' && <p className="text-xs text-red-600 mt-1">{st.msg}</p>}
      </div>
    )
  }

  // -------------------- render --------------------
  if (loading && !selectedKpi) {
    return <div className="flex items-center justify-center h-64"><div className="text-gray-500">Loading dashboard...</div></div>
  }

  const funnelMax = funnelData.length > 0 ? Math.max(...funnelData.map(s => s.value), 1) : 1

  return (
    <div>
      {/* Sticky header + filter bar */}
      <div className="sticky top-0 z-30 -mx-6 -mt-6 px-6 pt-6 pb-3 mb-4 bg-gray-50/95 backdrop-blur border-b border-gray-200">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-blue-600">ADS Performance</h1>
          <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
            <button
              onClick={() => setCampaignType('all')}
              className={`px-3 py-1.5 font-medium transition-colors ${campaignType === 'all' ? 'bg-gray-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
            >All</button>
            <button
              onClick={() => setCampaignType('sale')}
              className={`px-3 py-1.5 font-medium transition-colors ${campaignType === 'sale' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
            >Sale</button>
            <button
              onClick={() => setCampaignType('lead')}
              className={`px-3 py-1.5 font-medium transition-colors ${campaignType === 'lead' ? 'bg-orange-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}
            >Lead</button>
          </div>
        </div>
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

          {/* Campaign search combobox */}
          <div className="relative" ref={campaignSearchRef}>
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none z-10" />
            <input
              type="text"
              placeholder="Filter campaigns…"
              value={campaignSearch}
              onChange={(e) => { setCampaignSearch(e.target.value); setCampaignDropdownOpen(true) }}
              onFocus={() => setCampaignDropdownOpen(true)}
              onKeyDown={(e) => { if (e.key === 'Escape') setCampaignDropdownOpen(false) }}
              className="pl-8 pr-7 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-52"
            />
            {campaignSearch && (
              <button
                onClick={() => { setCampaignSearch(''); setCampaignDropdownOpen(false) }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 z-10"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
            {campaignDropdownOpen && (() => {
              const q = campaignSearch.toLowerCase().trim()
              const suggestions = campaignRows
                .filter((r) => !q || r.campaign_name.toLowerCase().includes(q))
                .sort((a, b) => b.spend - a.spend)
                .slice(0, 8)
              if (suggestions.length === 0) return null
              return (
                <div className="absolute z-50 top-full mt-1 left-0 w-96 bg-white border border-gray-200 rounded-lg shadow-lg py-1 max-h-72 overflow-y-auto">
                  {!q && (
                    <p className="px-3 py-1.5 text-[10px] text-gray-400 uppercase tracking-wide font-medium">Top campaigns by spend</p>
                  )}
                  {suggestions.map((r) => (
                    <button
                      key={r.campaign_id}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => { setCampaignSearch(r.campaign_name); setCampaignDropdownOpen(false) }}
                      className={`w-full text-left px-3 py-2 hover:bg-blue-50 transition-colors ${campaignSearch === r.campaign_name ? 'bg-blue-50' : ''}`}
                    >
                      <p className="text-xs font-medium text-gray-900 truncate">{r.campaign_name}</p>
                      <p className="text-[10px] text-gray-400 mt-0.5">{[r.account_name, r.platform, r.funnel_stage].filter(Boolean).join(' · ')}</p>
                    </button>
                  ))}
                </div>
              )
            })()}
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

      {/* KPI summary */}
      {selectedKpi && (() => {
        const cr = selectedKpi.clicks ? (selectedKpi.conversions / selectedKpi.clicks) * 100 : 0
        const aov = selectedKpi.conversions ? selectedKpi.total_revenue / selectedKpi.conversions : 0
        const cpc = selectedKpi.clicks ? selectedKpi.total_spend / selectedKpi.clicks : 0
        const roas = selectedKpi.total_spend ? selectedKpi.total_revenue / selectedKpi.total_spend : 0
        const ctr = selectedKpi.impressions ? (selectedKpi.clicks / selectedKpi.impressions) * 100 : 0
        const cpa = selectedKpi.conversions ? selectedKpi.total_spend / selectedKpi.conversions : 0

        const Card = ({ k }: { k: { label: string; value: string; change: number | null; inverse: boolean } }) => (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <p className="text-xs text-gray-500 mb-1 truncate">{k.label}</p>
            <p className="text-2xl font-bold text-gray-900">{k.value}</p>
            <div className="mt-2"><ChangeTag change={k.change} inverseColor={k.inverse} /></div>
          </div>
        )

        if (campaignType === 'lead') {
          const leadCount = selectedKpi.leads ?? 0
          const cpl = leadCount ? selectedKpi.total_spend / leadCount : 0
          const leadHeadline = [
            { label: `Spend (${responseCurrency})`, value: fmtMoney(selectedKpi.total_spend, responseCurrency), change: kpiForChange?.spend_change ?? null, inverse: true },
            { label: 'Leads', value: fmtNum(leadCount), change: kpiForChange?.conversions_change ?? null, inverse: false },
            { label: `CPL (${responseCurrency})`, value: cpl ? fmtMoney(Math.round(cpl), responseCurrency) : '--', change: kpiForChange?.cpa_change ?? null, inverse: true },
            { label: `Revenue (${responseCurrency})`, value: fmtMoney(selectedKpi.total_revenue, responseCurrency), change: kpiForChange?.revenue_change ?? null, inverse: false },
            { label: 'ROAS', value: roas ? roas.toFixed(2) + 'x' : '0', change: kpiForChange?.roas_change ?? null, inverse: false },
            { label: 'CTR', value: ctr ? ctr.toFixed(1) + '%' : '0%', change: kpiForChange?.ctr_change ?? null, inverse: false },
          ]
          const leadDecomp = [
            { label: 'Lead Rate (Leads / Clicks)', value: selectedKpi.clicks ? ((leadCount / selectedKpi.clicks) * 100).toFixed(2) + '%' : '--', change: kpiForChange?.cr_change ?? null, inverse: false },
            { label: 'Clicks', value: fmtNum(selectedKpi.clicks), change: kpiForChange?.ctr_change ?? null, inverse: false },
            { label: `CPC (${responseCurrency})`, value: cpc ? fmtMoney(Math.round(cpc), responseCurrency) : '--', change: kpiForChange?.cpc_change ?? null, inverse: true },
          ]
          return (
            <div className="space-y-4 mb-6">
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                {leadHeadline.map(k => <Card key={k.label} k={k} />)}
              </div>
              <div>
                <div className="flex items-center gap-2 mb-2 text-[11px] uppercase tracking-wider text-orange-400 font-semibold">
                  Lead Funnel
                  <span className="text-gray-300 normal-case font-normal tracking-normal">Comment → Landing Page → Form Fill → Email Flow</span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  {leadDecomp.map(k => <Card key={k.label} k={k} />)}
                </div>
              </div>
            </div>
          )
        }

        const headline = [
          { label: `Spend (${responseCurrency})`, value: fmtMoney(selectedKpi.total_spend, responseCurrency), change: kpiForChange?.spend_change ?? null, inverse: true },
          { label: `Revenue (${responseCurrency})`, value: fmtMoney(selectedKpi.total_revenue, responseCurrency), change: kpiForChange?.revenue_change ?? null, inverse: false },
          { label: 'ROAS', value: roas ? roas.toFixed(2) + 'x' : '0', change: kpiForChange?.roas_change ?? null, inverse: false },
          { label: 'CTR', value: ctr ? ctr.toFixed(1) + '%' : '0%', change: kpiForChange?.ctr_change ?? null, inverse: false },
          { label: `CPA (${responseCurrency})`, value: cpa ? fmtMoney(Math.round(cpa), responseCurrency) : '--', change: kpiForChange?.cpa_change ?? null, inverse: true },
          { label: 'Conversions', value: fmtNum(selectedKpi.conversions), change: kpiForChange?.conversions_change ?? null, inverse: false },
        ]
        const decomp = [
          { label: 'CR (Conversion Rate)', value: cr ? cr.toFixed(2) + '%' : '--', change: kpiForChange?.cr_change ?? null, inverse: false },
          { label: `AOV (${responseCurrency})`, value: aov ? fmtMoney(Math.round(aov), responseCurrency) : '--', change: kpiForChange?.aov_change ?? null, inverse: false },
          { label: `CPC (${responseCurrency})`, value: cpc ? fmtMoney(Math.round(cpc), responseCurrency) : '--', change: kpiForChange?.cpc_change ?? null, inverse: true },
        ]

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

      {/* Next actions — prioritized */}
      {nextActions.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
          <div className="flex items-center gap-2 mb-3">
            <Target className="w-4 h-4 text-blue-600" />
            <h2 className="text-sm font-semibold text-gray-800">Next actions — prioritized</h2>
          </div>
          <ol className="space-y-2">
            {nextActions.map((a, i) => (
              <li key={i} className="flex items-start gap-3">
                <span className="text-xs font-bold text-gray-400 mt-0.5 w-4">{i + 1}</span>
                <span className={`text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded border ${SEVERITY_STYLES[a.severity]} mt-0.5`}>
                  {a.severity === 'high' ? 'High' : a.severity === 'medium' ? 'Med' : 'Low'}
                </span>
                <span className="text-sm text-gray-700 flex-1">
                  {a.campaign && <span className="font-medium text-gray-900">{a.campaign}: </span>}
                  {a.text}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Cross-filter breakdowns */}
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
          title={campaignType === 'lead' ? 'By Branch (Leads)' : 'By Branch (Conversions)'}
          rows={byBranch as BranchBreakdownRow[]}
          valueKey={campaignType === 'lead' ? 'leads' : 'conversions'}
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
          campaignType={campaignType}
        />
        <HorizontalBarBreakdown
          title="By Funnel"
          items={byFunnel}
          currency={responseCurrency}
          selectedKey={funnelStage}
          onSelect={(k) => setFunnelStage(prev => prev === k ? '' : k)}
          metric={breakdownMetric}
          campaignType={campaignType}
        />
      </div>

      {/* Branch comparison */}
      {byBranch.length > 0 && (
        <div className="mb-6">
          <BranchComparisonChart rows={byBranch as (BranchBreakdownRow & { roas: number; cpa: number; ctr: number })[]} campaignType={campaignType} />
        </div>
      )}

      {/* Country comparison */}
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

      {/* Conversion funnel — enhanced with view toggle + diagnosis */}
      {funnelData.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <div className="flex items-start justify-between mb-1">
            <div className="flex items-center gap-2">
              <FilterIcon className="w-4 h-4 text-blue-600" />
              <h2 className="text-sm font-semibold text-gray-700">
                {campaignType === 'lead' ? 'Lead Funnel' : 'Conversion Funnel'}
                {country && <span className="text-gray-400 font-normal ml-2">— {countries.find(c => c.code === country)?.name || country}</span>}
                {campaignSearch.trim() && (
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium ml-2">
                    {campaignFunnelLoading ? 'loading…' : `filtered: "${campaignSearch}"`}
                  </span>
                )}
              </h2>
            </div>
            <div className="flex items-center gap-2">
              {funnelView === 'single' && (
                <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-0.5">
                  <button
                    onClick={() => setComparisonMode('prev')}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${comparisonMode === 'prev' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
                  >vs Last Period</button>
                  <button
                    onClick={() => setComparisonMode('benchmark')}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${comparisonMode === 'benchmark' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
                  >{benchmarkLoading ? '…' : 'vs 90-day Avg'}</button>
                </div>
              )}
              <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-0.5">
                {(['single', 'by-branch', 'by-campaign'] as const).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setFunnelView(mode)}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${funnelView === mode ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
                  >
                    {mode === 'single' ? 'Aggregate' : mode === 'by-branch' ? (branchFunnelLoading ? '…' : 'By Branch') : (campaignFunnelTableLoading ? '…' : 'By Campaign')}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <p className="text-[11px] text-gray-400 mb-4">
            {funnelView === 'by-branch'
              ? `Per-branch funnel · ${selectedBranches.length > 0 ? selectedBranches.join(', ') : 'all branches'} · worst drop-off highlighted red`
              : funnelView === 'by-campaign'
              ? `Per-campaign funnel · top ${Math.min(filteredRows.length, 10)} campaigns by spend · worst drop-off highlighted red`
              : 'Impression → Click → Search → Add to cart → Checkout → Booking · drop-off shown between steps'}
            {funnelView === 'single' && comparisonMode === 'benchmark' && (
              <span className="ml-2 text-blue-500">
                · comparing to 90-day average{selectedBranches.length === 1 ? ` for ${selectedBranches[0]}` : selectedBranches.length > 1 ? ' for selected branches' : ' across all branches'}
              </span>
            )}
          </p>

          {funnelView === 'by-branch' ? (
            branchFunnelLoading ? (
              <p className="text-sm text-gray-400 py-6 text-center">Loading per-branch funnel…</p>
            ) : Object.keys(branchFunnels).length === 0 ? (
              <p className="text-sm text-gray-400 py-6 text-center">No data.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm border-separate border-spacing-0">
                  <thead>
                    <tr>
                      <th className="text-left text-[11px] text-gray-400 uppercase tracking-wide pb-3 pr-6 w-32 font-medium">Step</th>
                      {Object.keys(branchFunnels).map((branch) => (
                        <th key={branch} className="text-left text-xs font-semibold text-gray-700 pb-3 px-3 whitespace-nowrap">{branch}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {displayFunnel.map((step, i) => {
                      const dropOffs = Object.values(branchFunnels)
                        .map((steps) => steps.find((s) => s.key === step.key)?.drop_off)
                        .filter((v): v is number => v != null)
                      const maxDropOff = dropOffs.length > 0 ? Math.max(...dropOffs) : 0
                      const minDropOff = dropOffs.length > 0 ? Math.min(...dropOffs) : 0
                      return (
                        <tr key={step.key} className={i % 2 === 0 ? 'bg-gray-50/50' : ''}>
                          <td className="py-3 pr-6 align-top">
                            {i > 0 && <div className="text-[10px] text-gray-400 mb-0.5">↓</div>}
                            <span className="text-xs font-medium text-gray-700">{step.label}</span>
                          </td>
                          {Object.entries(branchFunnels).map(([branch, steps]) => {
                            const s = steps.find((st) => st.key === step.key)
                            const isWorst = i > 0 && s?.drop_off != null && dropOffs.length > 1 && s.drop_off === maxDropOff && maxDropOff > minDropOff
                            const isBest = i > 0 && s?.drop_off != null && dropOffs.length > 1 && s.drop_off === minDropOff && maxDropOff > minDropOff
                            return (
                              <td key={branch} className={`py-3 px-3 align-top rounded ${isWorst ? 'bg-red-50' : isBest ? 'bg-emerald-50' : ''}`}>
                                <div className="text-sm font-bold text-gray-900">{s ? fmtNum(s.value) : '—'}</div>
                                {i > 0 && s?.drop_off != null && (
                                  <div className={`text-[11px] font-semibold mt-0.5 ${isWorst ? 'text-red-600' : isBest ? 'text-emerald-600' : 'text-gray-500'}`}>
                                    {(s.drop_off * 100).toFixed(1)}% drop
                                    {isWorst && <span className="ml-1">⚠</span>}
                                    {isBest && <span className="ml-1">✓</span>}
                                  </div>
                                )}
                                {s?.change != null && (
                                  <div className="mt-0.5"><ChangeTag change={s.change} /></div>
                                )}
                              </td>
                            )
                          })}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )
          ) : funnelView === 'by-campaign' ? (
            campaignFunnelTableLoading ? (
              <p className="text-sm text-gray-400 py-6 text-center">Loading per-campaign funnel…</p>
            ) : Object.keys(campaignFunnelTable).length === 0 ? (
              <p className="text-sm text-gray-400 py-6 text-center">No campaign data — run a sync or adjust filters.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm border-separate border-spacing-0">
                  <thead>
                    <tr>
                      <th className="text-left text-[11px] text-gray-400 uppercase tracking-wide pb-3 pr-6 w-32 font-medium">Step</th>
                      {Object.keys(campaignFunnelTable).map((name) => (
                        <th key={name} className="text-left text-[11px] font-semibold text-gray-700 pb-3 px-3 whitespace-nowrap max-w-[160px]" title={name}>
                          <span className="block truncate max-w-[160px]">{name}</span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {displayFunnel.map((step, i) => {
                      const dropOffs = Object.values(campaignFunnelTable)
                        .map((steps) => steps.find((s) => s.key === step.key)?.drop_off)
                        .filter((v): v is number => v != null)
                      const maxDropOff = dropOffs.length > 0 ? Math.max(...dropOffs) : 0
                      const minDropOff = dropOffs.length > 0 ? Math.min(...dropOffs) : 0
                      return (
                        <tr key={step.key} className={i % 2 === 0 ? 'bg-gray-50/50' : ''}>
                          <td className="py-3 pr-6 align-top">
                            {i > 0 && <div className="text-[10px] text-gray-400 mb-0.5">↓</div>}
                            <span className="text-xs font-medium text-gray-700">{step.label}</span>
                          </td>
                          {Object.entries(campaignFunnelTable).map(([name, steps]) => {
                            const s = steps.find((st) => st.key === step.key)
                            const isWorst = i > 0 && s?.drop_off != null && dropOffs.length > 1 && s.drop_off === maxDropOff && maxDropOff > minDropOff
                            const isBest = i > 0 && s?.drop_off != null && dropOffs.length > 1 && s.drop_off === minDropOff && maxDropOff > minDropOff
                            return (
                              <td key={name} className={`py-3 px-3 align-top rounded ${isWorst ? 'bg-red-50' : isBest ? 'bg-emerald-50' : ''}`}>
                                <div className="text-sm font-bold text-gray-900">{s ? fmtNum(s.value) : '—'}</div>
                                {i > 0 && s?.drop_off != null && (
                                  <div className={`text-[11px] font-semibold mt-0.5 ${isWorst ? 'text-red-600' : isBest ? 'text-emerald-600' : 'text-gray-500'}`}>
                                    {(s.drop_off * 100).toFixed(1)}% drop
                                    {isWorst && <span className="ml-1">⚠</span>}
                                    {isBest && <span className="ml-1">✓</span>}
                                  </div>
                                )}
                                {s?.change != null && (
                                  <div className="mt-0.5"><ChangeTag change={s.change} /></div>
                                )}
                              </td>
                            )
                          })}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )
          ) : (
            /* Single aggregate view */
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="space-y-3">
                {funnelData.map((stage, i) => {
                  const widthPct = Math.max((stage.value / funnelMax) * 100, 4)
                  // Match to FunnelStep for leak highlighting
                  const funnelStep = funnel.find((s) => s.label === stage.name)
                  const isLeak = funnelDiagAN?.stepKey != null && funnelStep?.key === funnelDiagAN.stepKey
                  const bmStep = benchmarkFunnel.find((b) => b.label === stage.name)
                  const bmDelta = comparisonMode === 'benchmark' && stage.drop_off != null && bmStep?.drop_off != null
                    ? stage.drop_off - bmStep.drop_off
                    : null
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
                          {comparisonMode === 'prev' ? (
                            stage.drop_off_change !== null && <ChangeTag change={stage.drop_off_change} inverseColor />
                          ) : bmDelta != null ? (
                            <span className={`text-[11px] font-medium ${bmDelta > 0.005 ? 'text-red-500' : bmDelta < -0.005 ? 'text-emerald-600' : 'text-gray-400'}`}>
                              {bmDelta > 0 ? '+' : ''}{(bmDelta * 100).toFixed(1)}pp vs avg
                            </span>
                          ) : benchmarkLoading ? (
                            <span className="text-[11px] text-gray-300">loading…</span>
                          ) : null}
                          {isLeak && (
                            <span className="text-[10px] font-semibold text-red-600 bg-red-50 px-1.5 py-0.5 rounded">worst leak</span>
                          )}
                        </div>
                      )}
                      <div className="flex items-center gap-4">
                        <div
                          className={`rounded-lg py-3 px-4 flex items-center justify-between transition-all ${isLeak ? 'bg-red-100 ring-2 ring-inset ring-red-300' : campaignType === 'lead' ? 'bg-orange-100' : 'bg-blue-100'}`}
                          style={{ width: `${widthPct}%`, minWidth: '180px' }}
                        >
                          <span className="text-xs text-gray-600">{stage.name}</span>
                          <span className="text-lg font-bold text-gray-900 ml-2">{fmtNum(stage.value)}</span>
                        </div>
                        <ChangeTag change={stage.change} />
                        {comparisonMode === 'benchmark' && bmStep?.drop_off != null && i > 0 && (
                          <span className="text-[10px] text-gray-400 whitespace-nowrap">
                            avg drop: {(bmStep.drop_off * 100).toFixed(1)}%
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
              <div className="flex flex-col justify-center">
                {funnelDiagAN ? (
                  <div className={`rounded-lg border p-4 ${SEVERITY_STYLES[funnelDiagAN.severity]}`}>
                    <div className="flex items-center gap-2 mb-2">
                      <AlertTriangle className="w-4 h-4" />
                      <span className="text-sm font-semibold">{funnelDiagAN.transition}</span>
                    </div>
                    <p className="text-xs text-gray-700 mb-3">{funnelDiagAN.reason}</p>
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1">How to fix</p>
                    <ul className="space-y-1">
                      {funnelDiagAN.fixes.map((f, idx) => (
                        <li key={idx} className="text-xs text-gray-700 flex gap-1.5">
                          <span className="text-blue-500">→</span>
                          <span>{f}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">Funnel looks healthy — no single step is leaking notably.</p>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Winners */}
      {winners.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp className="w-4 h-4 text-green-600" />
            <h2 className="text-sm font-semibold text-gray-800">Working well ({winners.length})</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {winners.slice(0, 6).map((i) => (
              <div key={i.row.campaign_id} className="bg-white rounded-xl border border-green-100 p-4">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-medium text-gray-900 text-sm break-words" title={i.row.campaign_name}>
                    {i.row.campaign_name}
                  </span>
                  {i.row.funnel_stage && (
                    <span className={`text-[10px] px-2 py-0.5 rounded-full whitespace-nowrap ${FUNNEL_STAGE_PILL[i.row.funnel_stage] || FUNNEL_STAGE_PILL.Unknown}`}>
                      {i.row.funnel_stage}
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-gray-400 mt-0.5">
                  {[i.row.account_name, i.row.platform, i.row.ta].filter(Boolean).join(' · ')}
                </p>
                <div className="grid grid-cols-3 gap-2 mt-3">
                  <Metric label="ROAS" value={`${i.row.roas.toFixed(2)}x`} change={i.row.roas_change} />
                  <Metric label="Spend" value={fmtMoney(i.row.spend, responseCurrency)} change={i.row.spend_change} inverse />
                  <Metric label="Conv" value={String(i.row.conversions)} change={i.row.conversions_change} />
                </div>
                <p className="text-xs text-gray-600 mt-3">{i.recommendations[0]}</p>
                {renderActions(i)}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Losers / Needs attention */}
      {losers.length > 0 && (
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4 text-red-500" />
            <h2 className="text-sm font-semibold text-gray-800">Needs attention ({losers.length})</h2>
          </div>
          <div className="space-y-3">
            {losers.map((i) => (
              <div key={i.row.campaign_id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                <div className="p-4 border-b border-gray-50">
                  <div className="flex items-start justify-between gap-3 flex-wrap">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-gray-900 text-sm break-words" title={i.row.campaign_name}>
                          {i.row.campaign_name}
                        </span>
                        {i.row.funnel_stage && (
                          <span className={`text-[10px] px-2 py-0.5 rounded-full ${FUNNEL_STAGE_PILL[i.row.funnel_stage] || FUNNEL_STAGE_PILL.Unknown}`}>
                            {i.row.funnel_stage}
                          </span>
                        )}
                        {i.leakLabel && (
                          <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${LEAK_PILL[i.leakLabel] || 'bg-gray-100 text-gray-600'}`}>
                            ⚠ {i.leakLabel}
                          </span>
                        )}
                        <span className={`text-[10px] px-2 py-0.5 rounded ${PLATFORM_PILL[i.row.platform] || 'bg-gray-50 text-gray-600'}`}>
                          {i.row.platform}
                        </span>
                      </div>
                      <p className="text-[11px] text-gray-400 mt-0.5">
                        {[i.row.account_name, i.row.ta].filter(Boolean).join(' · ')}
                      </p>
                    </div>
                    <div className={`text-sm font-bold ${i.row.roas >= 1 ? 'text-amber-600' : 'text-red-600'}`}>
                      {i.row.roas.toFixed(2)}x ROAS
                    </div>
                  </div>
                  <div className="grid grid-cols-3 md:grid-cols-6 gap-3 mt-3">
                    <Metric label="Spend" value={fmtMoney(i.row.spend, responseCurrency)} change={i.row.spend_change} inverse />
                    <Metric label="CR" value={`${i.row.cr.toFixed(2)}%`} change={i.row.cr_change} />
                    <Metric label="CTR" value={`${i.row.ctr.toFixed(2)}%`} />
                    <Metric label="CPC" value={i.row.cpc ? fmtMoney(Math.round(i.row.cpc), responseCurrency) : '--'} change={i.row.cpc_change} inverse />
                    <Metric label="AOV" value={i.row.aov ? fmtMoney(Math.round(i.row.aov), responseCurrency) : '--'} change={i.row.aov_change} />
                    <Metric label="Conv" value={String(i.row.conversions)} change={i.row.conversions_change} />
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-0 md:gap-4 text-sm">
                  <div className="p-4 md:border-r border-gray-50">
                    <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1">Why it&apos;s underperforming</p>
                    <p className="text-gray-700 text-xs">{i.reason}</p>
                  </div>
                  <div className="p-4 md:border-r border-gray-50">
                    <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1 flex items-center gap-1">
                      <Activity className="w-3 h-3" /> Related Activity Log
                    </p>
                    <ActivityChips items={i.activity} />
                  </div>
                  <div className="p-4">
                    <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1">What to do</p>
                    <ul className="space-y-1">
                      {i.recommendations.map((r, idx) => (
                        <li key={idx} className="text-xs text-gray-700 flex gap-1.5">
                          <span className="text-blue-400">→</span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                    {renderActions(i)}
                  </div>
                </div>
              </div>
            ))}
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

      {/* Campaign breakdown — filtered by campaign search */}
      {filteredRows.length > 0 && (
        <div className="mb-6">
          <CampaignBreakdownTable
            rows={filteredRows}
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

      {/* AI funnel recommendations */}
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

      {/* SURF Apply modal */}
      {surfModal && (
        <SurfApplyModal
          open={true}
          onClose={() => setSurfModal(null)}
          onApplied={(msg) => handleSurfApplied(surfModal.insight.row.campaign_id, msg)}
          campaign={{
            id: surfModal.insight.row.campaign_id,
            name: surfModal.insight.row.campaign_name,
            account_id: surfModal.insight.row.account_id,
            account_name: surfModal.insight.row.account_name,
            daily_budget: surfModal.insight.row.daily_budget,
            currency: activeCurrency || responseCurrency,
          }}
          action={surfModal.action}
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
