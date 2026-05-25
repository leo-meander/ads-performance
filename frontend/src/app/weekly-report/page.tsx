'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  TrendingUp,
  AlertTriangle,
  Target,
  Printer,
  Activity,
  ArrowRight,
} from 'lucide-react'
import { apiFetch } from '@/lib/api'
import {
  fmtMoney,
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
  MIN_SPEND_SHARE,
} from '@/components/weekly-report/analysis'

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

const SEVERITY_STYLES: Record<string, string> = {
  high: 'bg-red-100 text-red-700 border-red-200',
  medium: 'bg-amber-100 text-amber-700 border-amber-200',
  low: 'bg-gray-100 text-gray-600 border-gray-200',
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

export default function WeeklyReportPage() {
  // filters
  const [branches, setBranches] = useState<Branch[]>([])
  const [selectedBranches, setSelectedBranches] = useState<string[]>([])
  const [platform, setPlatform] = useState('')
  const [datePreset, setDatePreset] = useState('7d')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [branchDropdownOpen, setBranchDropdownOpen] = useState(false)

  // data
  const [rows, setRows] = useState<CampaignRow[]>([])
  const [currency, setCurrency] = useState('VND')
  const [period, setPeriod] = useState<{ from: string; to: string } | null>(null)
  const [prevPeriod, setPrevPeriod] = useState<{ from: string; to: string } | null>(null)
  const [agg, setAgg] = useState<CountryKpiAgg | null>(null)
  const [changelog, setChangelog] = useState<ChangeLogItem[]>([])
  const [loading, setLoading] = useState(true)

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
    return params.toString()
  }, [resolvedRange, platform, branchParam])

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
    ])
      .then(([camp, kpi, log]) => {
        if (camp.success && camp.data) {
          setRows(camp.data.items || [])
          setCurrency(camp.data.currency || 'VND')
          setPeriod(camp.data.period || null)
          setPrevPeriod(camp.data.prev_period || null)
        } else {
          setRows([])
        }
        if (kpi.success && kpi.data) setAgg(kpi.data.aggregate || null)
        if (log.success && log.data) setChangelog(log.data.items || [])
        else setChangelog([])
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [buildQs, datePreset, customFrom, customTo])

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
  const insights = useMemo(() => buildInsights(rows, changelog), [rows, changelog])
  const nextActions = useMemo(() => buildNextActions(insights), [insights])

  const winners = useMemo(
    () =>
      insights
        .filter((i) => i.verdict === 'winner' && i.row.spend > 0)
        .sort((a, b) => b.row.roas - a.row.roas),
    [insights],
  )
  const losers = useMemo(
    () =>
      insights
        .filter((i) => i.verdict !== 'winner' && i.spendShare >= MIN_SPEND_SHARE)
        .sort((a, b) => b.bleed - a.bleed || b.row.spend - a.row.spend),
    [insights],
  )

  return (
    <div className="pb-10">
      {/* Header + filters */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-2 print:mb-4">
        <div>
          <h1 className="text-2xl font-bold text-blue-600">Weekly Report</h1>
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
                      <Metric label={`Spend`} value={fmtMoney(i.row.spend, currency)} change={i.row.spend_change} inverse />
                      <Metric label="Conv" value={String(i.row.conversions)} change={i.row.conversions_change} />
                    </div>
                    <p className="text-xs text-gray-600 mt-3">{i.recommendations[0]}</p>
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
                            {i.diagnosis && (
                              <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${FUNNEL_STAGE_PILL[i.diagnosis.stage]}`}>
                                ⚠ {i.diagnosis.stage} funnel
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
                        <Metric label={`Spend`} value={fmtMoney(i.row.spend, currency)} change={i.row.spend_change} inverse />
                        <Metric label="CR" value={`${i.row.cr.toFixed(2)}%`} change={i.row.cr_change} />
                        <Metric label="CTR" value={`${i.row.ctr.toFixed(2)}%`} />
                        <Metric label={`CPC`} value={i.row.cpc ? fmtMoney(Math.round(i.row.cpc), currency) : '--'} change={i.row.cpc_change} inverse />
                        <Metric label={`AOV`} value={i.row.aov ? fmtMoney(Math.round(i.row.aov), currency) : '--'} change={i.row.aov_change} />
                        <Metric label="Conv" value={String(i.row.conversions)} change={i.row.conversions_change} />
                      </div>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-0 md:gap-4 text-sm">
                      {/* Why */}
                      <div className="p-4 md:border-r border-gray-50">
                        <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1">Why it&apos;s underperforming</p>
                        <p className="text-gray-700 text-xs">{i.diagnosis?.reason}</p>
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
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Appendix: full campaign table */}
          <div className="print:hidden">
            <CampaignBreakdownTable rows={rows} currency={currency} highlightId="" title="All campaigns" />
          </div>
        </>
      )}
    </div>
  )
}
