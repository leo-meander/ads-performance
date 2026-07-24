'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  TrendingUp,
  AlertTriangle,
  Target,
  Printer,
  Activity,
  ArrowRight,
  Filter as FilterIcon,
  Search,
  X,
} from 'lucide-react'
import { apiFetch } from '@/lib/api'
import {
  fmtMoney,
  fmtNum,
  ChangeTag,
  getDateRange,
  DATE_PRESETS,
  FUNNEL_STAGE_PILL,
  PLATFORM_PILL,
} from '@/components/dashboard/dashboardUtils'
import type { CampaignRow } from '@/components/dashboard/CampaignBreakdownTable'
import CampaignBreakdownTable from '@/components/dashboard/CampaignBreakdownTable'
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

type Branch = { name: string; currency: string }

type CountryKpiAgg = {
  total_spend: number
  total_revenue: number
  conversions: number
  roas: number
  ctr: number
  cpa: number
  spend_change: number | null
  revenue_change: number | null
  roas_change: number | null
  ctr_change: number | null
  cpa_change: number | null
  conversions_change: number | null
}

type CampaignsResponse = {
  items: CampaignRow[]
  currency: string
  period: { from: string; to: string }
  prev_period: { from: string; to: string }
}

type ChangelogResponse = { items: ChangeLogItem[]; total: number }
type FunnelResponse = { steps: FunnelStep[] }

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

// --- small presentational helpers -----------------------------------------

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

// ---------------------------------------------------------------------------

export default function ActionNeededPage() {
  // filters
  const [branches, setBranches] = useState<Branch[]>([])
  const [selectedBranches, setSelectedBranches] = useState<string[]>([])
  const [platform, setPlatform] = useState('')
  const [datePreset, setDatePreset] = useState('7d')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [branchDropdownOpen, setBranchDropdownOpen] = useState(false)
  const [campaignType, setCampaignType] = useState<'all' | 'sale' | 'lead'>('all')
  const [campaignSearch, setCampaignSearch] = useState('')

  // data
  const [rows, setRows] = useState<CampaignRow[]>([])
  const [currency, setCurrency] = useState('VND')
  const [period, setPeriod] = useState<{ from: string; to: string } | null>(null)
  const [prevPeriod, setPrevPeriod] = useState<{ from: string; to: string } | null>(null)
  const [agg, setAgg] = useState<CountryKpiAgg | null>(null)
  const [changelog, setChangelog] = useState<ChangeLogItem[]>([])
  const [funnel, setFunnel] = useState<FunnelStep[]>([])
  const [loading, setLoading] = useState(true)
  const [comparisonMode, setComparisonMode] = useState<'prev' | 'benchmark'>('prev')
  const [benchmarkFunnel, setBenchmarkFunnel] = useState<FunnelStep[]>([])
  const [benchmarkLoading, setBenchmarkLoading] = useState(false)
  const [campaignFunnel, setCampaignFunnel] = useState<FunnelStep[]>([])
  const [campaignFunnelLoading, setCampaignFunnelLoading] = useState(false)
  // Per-campaign apply/mark-done status, keyed by campaign_id.
  const [actionState, setActionState] = useState<
    Record<string, { status: 'loading' | 'done' | 'error'; msg?: string; tail?: string }>
  >({})

  const branchParam = selectedBranches.length > 0 ? selectedBranches.join(',') : ''

  const resolvedRange = useMemo(() => {
    if (datePreset === 'custom' && customFrom && customTo) return { from: customFrom, to: customTo }
    return getDateRange(datePreset)
  }, [datePreset, customFrom, customTo])

  const activeCurrency = useMemo(() => {
    if (selectedBranches.length === 0) return 'VND'
    const set = [...new Set(selectedBranches.map((b) => branches.find((br) => br.name === b)?.currency || 'VND'))]
    return set.length === 1 ? set[0] : 'VND'
  }, [selectedBranches, branches])

  const buildQs = useCallback(() => {
    const params = new URLSearchParams({ date_from: resolvedRange.from, date_to: resolvedRange.to })
    if (platform) params.set('platform', platform)
    if (branchParam) params.set('branches', branchParam)
    if (campaignType === 'lead') params.set('campaign_type', 'lead')
    else if (campaignType === 'sale') params.set('campaign_type', 'sale')
    return params.toString()
  }, [resolvedRange, platform, branchParam, campaignType])

  // branches list (once)
  useEffect(() => {
    apiFetch<Branch[]>('/api/branches')
      .then((res) => { if (res.success && res.data) setBranches(res.data) })
      .catch(() => {})
  }, [])

  // main load
  useEffect(() => {
    if (datePreset === 'custom' && (!customFrom || !customTo)) return
    setLoading(true)
    const qs = buildQs()
    Promise.all([
      apiFetch<CampaignsResponse>(`/api/dashboard/country/campaigns?${qs}`),
      apiFetch<{ aggregate: CountryKpiAgg | null; currency: string }>(`/api/dashboard/country?${qs}`),
      apiFetch<ChangelogResponse>(`/api/dashboard/country/changelog?${qs}&limit=200`),
      apiFetch<FunnelResponse>(`/api/dashboard/funnel?${qs}`),
    ])
      .then(([camp, kpi, log, fun]) => {
        if (camp.success && camp.data) {
          setRows(camp.data.items || [])
          setCurrency(camp.data.currency || 'VND')
          setPeriod(camp.data.period || null)
          setPrevPeriod(camp.data.prev_period || null)
        } else {
          setRows([])
        }
        if (kpi.success && kpi.data) setAgg(kpi.data.aggregate || null)
        setChangelog(log.success && log.data ? log.data.items || [] : [])
        setFunnel(fun.success && fun.data ? fun.data.steps || [] : [])
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [buildQs, datePreset, customFrom, customTo])

  // Benchmark funnel: 90-day window for the same branch/platform scope.
  // Fetched lazily when user switches to benchmark mode.
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
    apiFetch<FunnelResponse>(`/api/dashboard/funnel?${params}`)
      .then((res) => {
        if (cancelled) return
        setBenchmarkFunnel(res.success && res.data ? res.data.steps || [] : [])
      })
      .catch(() => { if (!cancelled) setBenchmarkFunnel([]) })
      .finally(() => { if (!cancelled) setBenchmarkLoading(false) })
    return () => { cancelled = true }
  }, [comparisonMode, branchParam, platform, campaignType])

  // Fetch funnel scoped to filtered campaigns when campaign search is active
  useEffect(() => {
    if (!campaignSearch.trim() || filteredRows.length === 0) {
      setCampaignFunnel([])
      return
    }
    let cancelled = false
    setCampaignFunnelLoading(true)
    const ids = filteredRows.map((r) => r.campaign_id).join(',')
    const params = new URLSearchParams(buildQs())
    params.set('campaign_ids', ids)
    apiFetch<FunnelResponse>(`/api/dashboard/funnel?${params}`)
      .then((res) => {
        if (cancelled) return
        setCampaignFunnel(res.success && res.data ? res.data.steps || [] : [])
      })
      .catch(() => { if (!cancelled) setCampaignFunnel([]) })
      .finally(() => { if (!cancelled) setCampaignFunnelLoading(false) })
    return () => { cancelled = true }
  }, [campaignSearch, filteredRows, buildQs])

  // close branch dropdown on outside click
  const branchRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (branchRef.current && !branchRef.current.contains(e.target as Node)) setBranchDropdownOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  const toggleBranch = (name: string) =>
    setSelectedBranches((prev) => (prev.includes(name) ? prev.filter((b) => b !== name) : [...prev, name]))

  // --- analysis ---
  const money = useCallback((n: number) => fmtMoney(n, currency), [currency])
  const insights = useMemo(() => buildInsights(rows, changelog, money), [rows, changelog, money])
  const displayFunnel = useMemo(
    () => (campaignSearch.trim() && campaignFunnel.length > 0 ? campaignFunnel : funnel),
    [campaignSearch, campaignFunnel, funnel],
  )
  const funnelDiag = useMemo(() => diagnoseConversionFunnel(displayFunnel), [displayFunnel])

  const filteredInsights = useMemo(() => {
    if (!campaignSearch.trim()) return insights
    const q = campaignSearch.toLowerCase()
    return insights.filter((i) => i.row.campaign_name.toLowerCase().includes(q))
  }, [insights, campaignSearch])

  const filteredRows = useMemo(() => {
    if (!campaignSearch.trim()) return rows
    const q = campaignSearch.toLowerCase()
    return rows.filter((r) => r.campaign_name.toLowerCase().includes(q))
  }, [rows, campaignSearch])

  const nextActions = useMemo(() => buildNextActions(filteredInsights, funnelDiag), [filteredInsights, funnelDiag])

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

  const funnelMax = displayFunnel.length > 0 ? Math.max(...displayFunnel.map((s) => s.value), 1) : 1

  // SURF modal state — open per (campaign, action). raise_budget / cut_budget
  // routes through the modal so the user can fine-tune per-branch caps before
  // Apply. pause_campaign keeps the direct window.confirm() path because there's
  // nothing for the user to tune.
  const [surfModal, setSurfModal] = useState<{
    insight: CampaignInsight
    action: 'raise_budget' | 'cut_budget'
  } | null>(null)

  // Apply (real Meta mutation) or mark-done (log only). Both write the Activity Log.
  const handleApply = useCallback(async (insight: CampaignInsight, opt: ApplyOption) => {
    const cid = insight.row.campaign_id
    if (opt.kind === 'auto') {
      // SURF actions open the modal — user can adjust caps + confirm there.
      if (opt.action === 'raise_budget' || opt.action === 'cut_budget') {
        setSurfModal({ insight, action: opt.action })
        return
      }
      // Pause stays simple: confirm + go.
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
      // Opt the campaign into a continuous tactic (no immediate Meta mutation).
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
                : `Enrolled in "${res.data?.tactic_name}"${
                    res.data?.dry_run ? ' (dry-run)' : ''
                  }`,
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

  // Called from SurfApplyModal after a successful Meta mutation. The modal
  // already POSTed /action-needed/apply; we just flip the card's badge to
  // "done" with the message the backend produced (carries the actual delta).
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

  return (
    <div className="pb-10">
      {/* Header + filters */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2 print:mb-4">
        <div>
          <div className="flex items-center gap-3 mb-0.5">
            <h1 className="text-2xl font-bold text-blue-600">Action Needed</h1>
            <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm print:hidden">
              <button onClick={() => setCampaignType('all')}
                className={`px-3 py-1.5 font-medium transition-colors ${campaignType === 'all' ? 'bg-gray-700 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>All</button>
              <button onClick={() => setCampaignType('sale')}
                className={`px-3 py-1.5 font-medium transition-colors ${campaignType === 'sale' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>Sale</button>
              <button onClick={() => setCampaignType('lead')}
                className={`px-3 py-1.5 font-medium transition-colors ${campaignType === 'lead' ? 'bg-orange-500 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'}`}>Lead</button>
            </div>
          </div>
          {period && prevPeriod && (
            <p className="text-xs text-gray-400 mt-0.5">
              {period.from} → {period.to} &nbsp;vs&nbsp; {prevPeriod.from} → {prevPeriod.to}
              {selectedBranches.length === 0 && (
                <span className="ml-2 text-gray-400">· converted to VND for cross-branch comparison</span>
              )}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 print:hidden">
          <select
            value={datePreset}
            onChange={(e) => setDatePreset(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {DATE_PRESETS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          {datePreset === 'custom' && (
            <>
              <input type="date" value={customFrom} onChange={(e) => setCustomFrom(e.target.value)}
                className="px-2 py-2 border border-gray-200 rounded-lg text-sm" />
              <span className="text-gray-400">→</span>
              <input type="date" value={customTo} onChange={(e) => setCustomTo(e.target.value)}
                className="px-2 py-2 border border-gray-200 rounded-lg text-sm" />
            </>
          )}
          <div className="relative" ref={branchRef}>
            <button
              onClick={() => setBranchDropdownOpen((o) => !o)}
              className="px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white min-w-[170px] text-left flex items-center justify-between gap-2"
            >
              <span className="truncate">
                {selectedBranches.length === 0
                  ? 'All Branches (VND)'
                  : selectedBranches.length === 1
                    ? `${selectedBranches[0]} (${activeCurrency})`
                    : `${selectedBranches.length} branches (${activeCurrency})`}
              </span>
              <svg className={`w-4 h-4 text-gray-400 transition-transform ${branchDropdownOpen ? 'rotate-180' : ''}`}
                fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            {branchDropdownOpen && (
              <div className="absolute z-50 mt-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg py-1 right-0">
                {selectedBranches.length > 0 && (
                  <button onClick={() => setSelectedBranches([])}
                    className="w-full px-3 py-1.5 text-xs text-blue-600 hover:bg-gray-50 text-left">Clear all</button>
                )}
                {branches.map((b) => (
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
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
            <input
              type="text"
              placeholder="Filter campaigns…"
              value={campaignSearch}
              onChange={(e) => setCampaignSearch(e.target.value)}
              className="pl-8 pr-7 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 w-48"
            />
            {campaignSearch && (
              <button
                onClick={() => setCampaignSearch('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <select value={platform} onChange={(e) => setPlatform(e.target.value)}
            className="px-3 py-2 border border-gray-200 rounded-lg text-sm">
            <option value="">All Platforms</option>
            <option value="meta">Meta</option>
            <option value="google">Google</option>
            <option value="tiktok">TikTok</option>
          </select>
          <button
            onClick={() => window.print()}
            className="inline-flex items-center gap-1.5 px-3 py-2 border border-gray-200 rounded-lg text-sm text-gray-700 hover:bg-gray-50"
          >
            <Printer className="w-4 h-4" /> Print / PDF
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64 text-gray-500">Building report…</div>
      ) : rows.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          No campaign data for this period yet. Run a sync first.
        </div>
      ) : (
        <>
          {/* Topline KPI */}
          {agg && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
              {[
                { label: `Spend (${currency})`, value: fmtMoney(agg.total_spend, currency), change: agg.spend_change, inverse: true },
                { label: `Revenue (${currency})`, value: fmtMoney(agg.total_revenue, currency), change: agg.revenue_change, inverse: false },
                { label: 'ROAS', value: `${agg.roas.toFixed(2)}x`, change: agg.roas_change, inverse: false },
                { label: 'CTR', value: `${agg.ctr.toFixed(1)}%`, change: agg.ctr_change, inverse: false },
                { label: `CPA (${currency})`, value: agg.cpa ? fmtMoney(Math.round(agg.cpa), currency) : '--', change: agg.cpa_change, inverse: true },
                { label: 'Conversions', value: String(agg.conversions), change: agg.conversions_change, inverse: false },
              ].map((k) => (
                <div key={k.label} className="bg-white rounded-xl border border-gray-200 p-4">
                  <p className="text-xs text-gray-500 mb-1 truncate">{k.label}</p>
                  <p className="text-xl font-bold text-gray-900">{k.value}</p>
                  <div className="mt-1"><ChangeTag change={k.change} inverseColor={k.inverse} /></div>
                </div>
              ))}
            </div>
          )}

          {/* Next actions */}
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

          {/* Conversion funnel diagnosis */}
          {(displayFunnel.length > 1 || (campaignSearch.trim() && funnel.length > 1)) && (
            <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
              <div className="flex items-start justify-between mb-1">
                <div className="flex items-center gap-2">
                  <FilterIcon className="w-4 h-4 text-blue-600" />
                  <h2 className="text-sm font-semibold text-gray-800">Conversion funnel — where we lose people</h2>
                  {campaignSearch.trim() && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">
                      {campaignFunnelLoading ? 'loading…' : `filtered: "${campaignSearch}"`}
                    </span>
                  )}
                </div>
                {/* Comparison mode tabs */}
                <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-0.5">
                  <button
                    onClick={() => setComparisonMode('prev')}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                      comparisonMode === 'prev' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    vs Last Period
                  </button>
                  <button
                    onClick={() => setComparisonMode('benchmark')}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                      comparisonMode === 'benchmark' ? 'bg-white text-gray-800 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    {benchmarkLoading ? '…' : 'vs 90-day Avg'}
                  </button>
                </div>
              </div>
              <p className="text-[11px] text-gray-400 mb-4">
                Impression → Click → Search → Add to cart → Checkout → Booking · drop-off shown between steps
                {comparisonMode === 'benchmark' && (
                  <span className="ml-2 text-blue-500">
                    · comparing to 90-day average{selectedBranches.length === 1 ? ` for ${selectedBranches[0]}` : selectedBranches.length > 1 ? ' for selected branches' : ' across all branches'}
                  </span>
                )}
              </p>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Funnel bars */}
                <div className="space-y-2">
                  {displayFunnel.map((s, i) => {
                    const width = Math.max((s.value / funnelMax) * 100, 6)
                    const isLeak = funnelDiag?.stepKey === s.key
                    // Benchmark delta: current drop_off minus benchmark drop_off
                    const bmStep = benchmarkFunnel.find((b) => b.key === s.key)
                    const bmDelta = comparisonMode === 'benchmark' && s.drop_off != null && bmStep?.drop_off != null
                      ? s.drop_off - bmStep.drop_off
                      : null
                    return (
                      <div key={s.key}>
                        {i > 0 && (
                          <div className="flex items-center gap-2 ml-3 mb-1">
                            <span className="text-[11px] text-gray-400">
                              {s.drop_off != null ? `${(s.drop_off * 100).toFixed(1)}% drop-off` : '—'}
                            </span>
                            {comparisonMode === 'prev' ? (
                              <ChangeTag change={s.drop_off_change} inverseColor />
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
                        <div className="flex items-center gap-3">
                          <div
                            className={`rounded-lg py-2 px-3 flex items-center justify-between transition-all ${isLeak ? 'bg-red-100 ring-2 ring-inset ring-red-300' : 'bg-blue-50'}`}
                            style={{ width: `${width}%`, minWidth: '150px' }}
                          >
                            <span className="text-xs text-gray-600">{s.label}</span>
                            <span className="text-sm font-bold text-gray-900 ml-2">{fmtNum(s.value)}</span>
                          </div>
                          <ChangeTag change={s.change} />
                          {/* Benchmark reference rate */}
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

                {/* Diagnosis + fixes */}
                <div className="flex flex-col justify-center">
                  {funnelDiag ? (
                    <div className={`rounded-lg border p-4 ${SEVERITY_STYLES[funnelDiag.severity]}`}>
                      <div className="flex items-center gap-2 mb-2">
                        <AlertTriangle className="w-4 h-4" />
                        <span className="text-sm font-semibold">{funnelDiag.transition}</span>
                      </div>
                      <p className="text-xs text-gray-700 mb-3">{funnelDiag.reason}</p>
                      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1">How to fix</p>
                      <ul className="space-y-1">
                        {funnelDiag.fixes.map((f, idx) => (
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
            </div>
          )}

          {/* Winners */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-3">
              <TrendingUp className="w-4 h-4 text-green-600" />
              <h2 className="text-sm font-semibold text-gray-800">Working well ({winners.length})</h2>
            </div>
            {winners.length === 0 ? (
              <p className="text-sm text-gray-400">No campaign hit ROAS ≥ 1.5x this period.</p>
            ) : (
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
                      <Metric label="Spend" value={fmtMoney(i.row.spend, currency)} change={i.row.spend_change} inverse />
                      <Metric label="Conv" value={String(i.row.conversions)} change={i.row.conversions_change} />
                    </div>
                    <p className="text-xs text-gray-600 mt-3">{i.recommendations[0]}</p>
                    {renderActions(i)}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Losers / needs attention */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-4 h-4 text-red-500" />
              <h2 className="text-sm font-semibold text-gray-800">Needs attention ({losers.length})</h2>
            </div>
            {losers.length === 0 ? (
              <p className="text-sm text-gray-400">Nothing concerning (no campaign under 1.5x ROAS with meaningful spend).</p>
            ) : (
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
                        <Metric label="Spend" value={fmtMoney(i.row.spend, currency)} change={i.row.spend_change} inverse />
                        <Metric label="CR" value={`${i.row.cr.toFixed(2)}%`} change={i.row.cr_change} />
                        <Metric label="CTR" value={`${i.row.ctr.toFixed(2)}%`} />
                        <Metric label="CPC" value={i.row.cpc ? fmtMoney(Math.round(i.row.cpc), currency) : '--'} change={i.row.cpc_change} inverse />
                        <Metric label="AOV" value={i.row.aov ? fmtMoney(Math.round(i.row.aov), currency) : '--'} change={i.row.aov_change} />
                        <Metric label="Conv" value={String(i.row.conversions)} change={i.row.conversions_change} />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-0 md:gap-4 text-sm">
                      {/* Why */}
                      <div className="p-4 md:border-r border-gray-50">
                        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1">Why it&apos;s underperforming</p>
                        <p className="text-gray-700 text-xs">{i.reason}</p>
                      </div>
                      {/* Activity log */}
                      <div className="p-4 md:border-r border-gray-50">
                        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1 flex items-center gap-1">
                          <Activity className="w-3 h-3" /> Related Activity Log
                        </p>
                        <ActivityChips items={i.activity} />
                      </div>
                      {/* Recommendation */}
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
            )}
          </div>

          {/* Appendix: full campaign table */}
          <div className="print:hidden">
            <CampaignBreakdownTable rows={filteredRows} currency={currency} highlightId="" title="All campaigns" />
          </div>
        </>
      )}

      {/* SURF Apply modal — mounted at root so it overlays the whole page.
          Stays null when surfModal is null (modal returns null on !open). */}
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
            currency,
          }}
          action={surfModal.action}
        />
      )}
    </div>
  )
}
