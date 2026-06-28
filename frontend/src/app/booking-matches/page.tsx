'use client'

import { Fragment, useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { API_BASE } from '@/lib/api'
import { formatLocalDate } from '@/lib/dates'
import { fmtMoney } from '@/components/dashboard/dashboardUtils'

type BookingMatch = {
  id: string
  match_date: string | null
  ads_revenue: number
  matched_revenue: number
  ads_bookings: number
  ads_country: string | null
  ads_channel: string | null
  campaign_name: string | null
  campaign_id: string | null
  ad_id: string | null
  ad_name: string | null
  purchase_kind: string | null
  reservation_numbers: string | null
  guest_names: string | null
  guest_emails: string | null
  reservation_statuses: string | null
  room_types: string | null
  rate_plans: string | null
  reservation_sources: string | null
  matched_country: string | null
  branch: string | null
  match_result: string
  confidence: string | null
  matched_at: string | null
}

type ChannelKpi = { channel: string; matches: number; revenue: number; bookings: number }
type BranchKpi = { branch: string; matches: number; revenue: number; bookings: number }
type ResultKpi = { result: string; count: number }
type ConfidenceKpi = { confidence: string; matches: number; bookings: number; revenue: number }

type Summary = {
  total_matches: number
  total_revenue: number
  total_bookings: number
  currency: string
  by_channel: ChannelKpi[]
  by_branch: BranchKpi[]
  by_result: ResultKpi[]
  by_confidence: ConfidenceKpi[]
  period: { from: string; to: string }
}

type Stats = { count: number; avg: number; median: number; min: number; max: number }
type RoomTypeStat = { room_type: string; count: number; revenue: number; nights: number }
type Insights = {
  lead_time_days: Stats
  room_types: RoomTypeStat[]
  adults: Stats
  nights: Stats
  adr: Stats
  currency: string
  total_reservations: number
  period: { from: string; to: string }
}

type RoomMini = { room_type: string; bookings: number; revenue: number }
type ActualCountry = { country: string; bookings: number }
type CampaignInsight = {
  campaign_id: string | null
  campaign_name: string
  channel: string | null
  branch: string | null
  target_country: string | null
  matches: number
  bookings: number
  matched_revenue: number
  ads_revenue: number
  confirmed_share: number
  cancel_count: number
  cancel_rate: number
  avg_lead_time: number
  avg_nights: number
  adr: number
  website_bookings: number
  offline_bookings: number
  lead_buckets: Record<string, number>
  top_rooms: RoomMini[]
  top_actual_countries: ActualCountry[]
}
type CountryFlow = {
  target: string
  actual: string
  bookings: number
  revenue: number
  exact: number
  cross: number
  null_count: number
}
type CampaignInsights = {
  currency: string
  campaigns: CampaignInsight[]
  country_flow: CountryFlow[]
  totals: {
    bookings: number
    cancel_count: number
    cancel_rate: number
    confirmed_share: number
    leakage_rate: number
    country_known: number
    country_exact: number
    country_cross: number
    country_unknown: number
  }
  period: { from: string; to: string }
}

const LEAD_BUCKET_ORDER = ['0', '1-3', '4-7', '8-14', '15+']

type Branch = { name: string; currency: string }

const CHANNELS = ['meta', 'google']
const MATCH_RESULTS = ['Matched', 'Matched (country)', 'Matched (combo)', 'Multiple']

function getDateRange(preset: string): { from: string; to: string } {
  const today = new Date()
  const to = formatLocalDate(today)
  const daysBack = (d: number) => {
    const dt = new Date(today)
    dt.setDate(dt.getDate() - d)
    return formatLocalDate(dt)
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
    case '90d': return { from: daysBack(89), to }
    case 'this_month': {
      const from = formatLocalDate(new Date(today.getFullYear(), today.getMonth(), 1))
      return { from, to }
    }
    case 'last_month': {
      const from = formatLocalDate(new Date(today.getFullYear(), today.getMonth() - 1, 1))
      const last = formatLocalDate(new Date(today.getFullYear(), today.getMonth(), 0))
      return { from, to: last }
    }
    case 'this_year': {
      const from = formatLocalDate(new Date(today.getFullYear(), 0, 1))
      return { from, to }
    }
    case 'last_year': {
      const from = formatLocalDate(new Date(today.getFullYear() - 1, 0, 1))
      const last = formatLocalDate(new Date(today.getFullYear() - 1, 11, 31))
      return { from, to: last }
    }
    default: return { from: daysBack(29), to }
  }
}

function rowBgColor(result: string): string {
  if (result === 'Matched' || result === 'Matched (country)' || result === 'Matched (combo)') {
    return 'bg-green-50'
  }
  if (result === 'Multiple') return 'bg-yellow-50'
  return ''
}

function fmtNum(v: number, digits = 1): string {
  if (!isFinite(v)) return '--'
  return v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: digits })
}

function StatCard({
  label, avg, median, min, max, count, digits = 1, isMoney = false, currency,
}: {
  label: string
  avg: number
  median: number
  min: number
  max: number
  count: number
  digits?: number
  isMoney?: boolean
  currency?: string
}) {
  const fmt = (v: number) => isMoney ? fmtMoney(v, currency || 'VND') : fmtNum(v, digits)
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-2xl font-bold mt-1">{count > 0 ? fmt(avg) : '--'}</p>
      <p className="text-xs text-gray-400 mt-1">avg · n={count}</p>
      {count > 0 && (
        <div className="mt-2 text-xs text-gray-500 flex justify-between border-t pt-2">
          <span>med {fmt(median)}</span>
          <span>min {fmt(min)}</span>
          <span>max {fmt(max)}</span>
        </div>
      )}
    </div>
  )
}

function ResultBadge({ result }: { result: string }) {
  const isGreen = result.startsWith('Matched')
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
      isGreen ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'
    }`}>
      {result}
    </span>
  )
}

function ConfidenceBadge({ confidence }: { confidence: string | null }) {
  if (confidence === 'confirmed') {
    return (
      <span
        title="Revenue summed to the ads value — value + count both agree"
        className="inline-block px-1.5 py-0.5 rounded text-[11px] font-medium bg-emerald-100 text-emerald-800"
      >✓ confirmed</span>
    )
  }
  return (
    <span
      title="Matched by capacity/count only — revenue did not line up"
      className="inline-block px-1.5 py-0.5 rounded text-[11px] font-medium bg-amber-100 text-amber-800"
    >~ inferred</span>
  )
}

function fmtPct(v: number): string {
  if (!isFinite(v)) return '--'
  return `${v.toFixed(0)}%`
}

// Colour a cancellation rate: green low, amber mid, red high — quick scan for
// campaigns driving junk bookings.
function cancelColor(rate: number): string {
  if (rate >= 30) return 'text-red-600 font-semibold'
  if (rate >= 15) return 'text-amber-600 font-medium'
  return 'text-gray-700'
}

function LeadHistogram({ buckets }: { buckets: Record<string, number> }) {
  const max = Math.max(1, ...LEAD_BUCKET_ORDER.map(b => buckets[b] || 0))
  return (
    <div className="flex items-end gap-2 h-20">
      {LEAD_BUCKET_ORDER.map(b => {
        const n = buckets[b] || 0
        const h = Math.round((n / max) * 100)
        return (
          <div key={b} className="flex flex-col items-center gap-1 flex-1">
            <span className="text-[10px] text-gray-500">{n}</span>
            <div className="w-full bg-blue-100 rounded-sm relative" style={{ height: '64px' }}>
              <div
                className="absolute bottom-0 w-full bg-blue-500 rounded-sm"
                style={{ height: `${h}%` }}
              />
            </div>
            <span className="text-[10px] text-gray-400">{b}</span>
          </div>
        )
      })}
    </div>
  )
}

export default function BookingMatchesDashboard() {
  const [datePreset, setDatePreset] = useState('30d')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [branches, setBranches] = useState<Branch[]>([])
  const [selectedBranches, setSelectedBranches] = useState<string[]>([])
  const [branchDropdownOpen, setBranchDropdownOpen] = useState(false)
  const [channel, setChannel] = useState('')
  const [matchResult, setMatchResult] = useState('')
  const [purchaseKind, setPurchaseKind] = useState('')
  const [confidenceFilter, setConfidenceFilter] = useState('')

  const resolveRange = useCallback(() => {
    if (datePreset === 'custom' && customFrom && customTo) {
      return { from: customFrom, to: customTo }
    }
    return getDateRange(datePreset)
  }, [datePreset, customFrom, customTo])
  const [summary, setSummary] = useState<Summary | null>(null)
  const [insights, setInsights] = useState<Insights | null>(null)
  const [campaignInsights, setCampaignInsights] = useState<CampaignInsights | null>(null)
  const [expandedCampaign, setExpandedCampaign] = useState<string | null>(null)
  const [matches, setMatches] = useState<BookingMatch[]>([])
  const [listCurrency, setListCurrency] = useState<string>('VND')
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [runMessage, setRunMessage] = useState<string | null>(null)

  // Same rule as the dashboard: single branch (or several sharing one currency)
  // shows that native currency; multi-branch / mixed / all-branches shows VND.
  const activeCurrency = useMemo(() => {
    if (selectedBranches.length === 0) return 'VND'
    const currencies = [...new Set(
      selectedBranches.map(b => branches.find(br => br.name === b)?.currency || 'VND')
    )]
    return currencies.length === 1 ? currencies[0] : 'VND'
  }, [selectedBranches, branches])

  const branchParam = selectedBranches.length > 0 ? selectedBranches.join(',') : ''

  // Branches list for the dropdown.
  useEffect(() => {
    fetch(`${API_BASE}/api/branches`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setBranches(d.data) })
      .catch(() => {})
  }, [])

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const { from, to } = resolveRange()
      if (!from || !to) { setLoading(false); return }
      const params = new URLSearchParams({ date_from: from, date_to: to })
      if (branchParam) params.set('branches', branchParam)
      if (channel) params.set('channel', channel)
      if (matchResult) params.set('match_result', matchResult)
      if (purchaseKind) params.set('purchase_kind', purchaseKind)
      if (confidenceFilter) params.set('confidence', confidenceFilter)

      const summaryParams = new URLSearchParams({ date_from: from, date_to: to })
      if (branchParam) summaryParams.set('branches', branchParam)

      // Insights honour the same filters as the list (channel/result/kind),
      // so the lead-time / ADR cards reflect what's shown in the table.
      const insightsParams = new URLSearchParams(params)

      const [summaryRes, listRes, insightsRes, campaignRes] = await Promise.all([
        fetch(`${API_BASE}/api/booking-matches/summary?${summaryParams}`, { credentials: 'include' }).then(r => r.json()),
        fetch(`${API_BASE}/api/booking-matches?${params}`, { credentials: 'include' }).then(r => r.json()),
        fetch(`${API_BASE}/api/booking-matches/insights?${insightsParams}`, { credentials: 'include' }).then(r => r.json()),
        fetch(`${API_BASE}/api/booking-matches/campaign-insights?${insightsParams}`, { credentials: 'include' }).then(r => r.json()),
      ])

      if (summaryRes.success) setSummary(summaryRes.data)
      if (listRes.success) {
        setMatches(listRes.data.items)
        setListCurrency(listRes.data.currency || 'VND')
      }
      if (insightsRes.success) setInsights(insightsRes.data)
      if (campaignRes.success) setCampaignInsights(campaignRes.data)
    } finally {
      setLoading(false)
    }
  }, [resolveRange, branchParam, channel, matchResult, purchaseKind, confidenceFilter])

  useEffect(() => { fetchData() }, [fetchData])

  // Close branch dropdown on outside click.
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

  const runManualMatch = async () => {
    setRunning(true)
    setRunMessage(null)
    try {
      const { from, to } = resolveRange()
      if (!from || !to) {
        setRunMessage('Pick a custom date range first.')
        setRunning(false)
        return
      }
      const scopeLabel = selectedBranches.length > 0 ? selectedBranches.join(', ') : 'all branches'
      setRunMessage(`Syncing & matching ${from} → ${to} · ${scopeLabel}...`)
      const runParams = new URLSearchParams({ date_from: from, date_to: to })
      if (branchParam) runParams.set('branches', branchParam)
      const res = await fetch(
        `${API_BASE}/api/booking-matches/run?${runParams}`,
        { method: 'POST', credentials: 'include' }
      ).then(r => r.json())

      if (res.success) {
        const sync = res.data.sync
        const matching = res.data.matching
        const syncPart = sync?.skipped_concurrent
          ? `Sync skipped (another run in progress)`
          : `Sync: ${sync?.created ?? 0} created, ${sync?.updated ?? 0} updated`
              + ` (fetched ${sync?.total_fetched ?? 0}, skipped non-hotel ${sync?.skipped ?? 0})`
        const byBranch: Record<string, number> = matching?.matches_by_branch || {}
        const branchBits = Object.entries(byBranch)
          .sort((a, b) => b[1] - a[1])
          .map(([b, n]) => `${b} ${n}`)
          .join(', ')
        const matchPart =
          `Matching: ${matching?.matches_created ?? 0} matches`
          + (branchBits ? ` (${branchBits})` : '')
          + ` · ✓${matching?.matches_confirmed ?? 0} confirmed / ~${matching?.matches_inferred ?? 0} inferred`
          + ` · ads rows ${matching?.ads_rows_processed ?? 0}`
          + ` · reservations in window ${matching?.reservations_loaded ?? 0}`
          + ` · ads no-branch ${matching?.ads_rows_no_branch ?? 0}`
          + ` · ads no-candidate ${matching?.ads_rows_no_candidates ?? 0}`
        setRunMessage(`${from} → ${to} · ${scopeLabel} · ${syncPart} · ${matchPart}`)
        await fetchData()
      } else {
        setRunMessage(`Error: ${res.error}`)
      }
    } catch (e: any) {
      setRunMessage(`Error: ${e.message}`)
    } finally {
      setRunning(false)
    }
  }

  const summaryCurrency = summary?.currency || activeCurrency

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Booking from Ads</h1>
          <p className="text-sm text-gray-500 mt-1">
            Match real PMS reservations to ad campaigns by date + branch + country. Each campaign claims up to its reported conversion count; revenue shown is the real PMS total.
          </p>
        </div>
        <button
          onClick={runManualMatch}
          disabled={running}
          title={(() => { const { from, to } = resolveRange(); const scope = selectedBranches.length > 0 ? selectedBranches.join(', ') : 'all branches'; return from && to ? `Will sync & match ${from} → ${to} · ${scope}` : 'Pick a date range first' })()}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {running ? 'Running...' : 'Sync & Run Matching'}
        </button>
      </div>

      {runMessage && (
        <div className="px-4 py-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800">
          {runMessage}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <select
          value={datePreset}
          onChange={(e) => setDatePreset(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
        >
          <option value="today">Today</option>
          <option value="yesterday">Yesterday</option>
          <option value="7d">Last 7 days</option>
          <option value="14d">Last 14 days</option>
          <option value="30d">Last 30 days</option>
          <option value="90d">Last 90 days</option>
          <option value="this_month">This month</option>
          <option value="last_month">Last month</option>
          <option value="this_year">This year</option>
          <option value="last_year">Last year</option>
          <option value="custom">Custom range</option>
        </select>

        {datePreset === 'custom' && (
          <>
            <input
              type="date"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
              className="px-2 py-2 border border-gray-300 rounded-lg text-sm"
            />
            <span className="text-gray-400">→</span>
            <input
              type="date"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
              className="px-2 py-2 border border-gray-300 rounded-lg text-sm"
            />
          </>
        )}

        <div className="relative" ref={branchDropdownRef}>
          <button
            onClick={() => setBranchDropdownOpen(o => !o)}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white min-w-[180px] text-left flex items-center justify-between gap-2"
          >
            <span className="truncate">
              {selectedBranches.length === 0
                ? `All branches (VND)`
                : selectedBranches.length === 1
                  ? `${selectedBranches[0]} (${activeCurrency})`
                  : `${selectedBranches.length} branches (${activeCurrency})`}
            </span>
            <svg className={`w-4 h-4 text-gray-400 transition-transform ${branchDropdownOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
          </button>
          {branchDropdownOpen && (
            <div className="absolute z-50 mt-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg py-1 left-0">
              {selectedBranches.length > 0 && (
                <button
                  onClick={() => setSelectedBranches([])}
                  className="w-full px-3 py-1.5 text-xs text-blue-600 hover:bg-gray-50 text-left"
                >Clear all</button>
              )}
              {branches.map(b => (
                <label key={b.name} className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm">
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

        <select
          value={channel}
          onChange={(e) => setChannel(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
        >
          <option value="">All channels</option>
          {CHANNELS.map(c => <option key={c} value={c}>{c}</option>)}
        </select>

        <select
          value={purchaseKind}
          onChange={(e) => setPurchaseKind(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
        >
          <option value="">All kinds</option>
          <option value="website">Website</option>
          <option value="offline">Offline</option>
        </select>

        <select
          value={matchResult}
          onChange={(e) => setMatchResult(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
        >
          <option value="">All results</option>
          {MATCH_RESULTS.map(r => <option key={r} value={r}>{r}</option>)}
        </select>

        <select
          value={confidenceFilter}
          onChange={(e) => setConfidenceFilter(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-lg text-sm"
        >
          <option value="">All confidence</option>
          <option value="confirmed">✓ Confirmed</option>
          <option value="inferred">~ Inferred</option>
        </select>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-sm text-gray-500">Matched Bookings</p>
          <p className="text-2xl font-bold mt-1">{summary ? summary.total_bookings.toLocaleString() : '--'}</p>
          <p className="text-xs text-gray-400 mt-1">{summary?.total_matches ?? 0} match rows</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-sm text-gray-500">Matched Revenue ({summaryCurrency})</p>
          <p className="text-2xl font-bold mt-1">{summary ? fmtMoney(summary.total_revenue, summaryCurrency) : '--'}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-sm text-gray-500">Match Confidence</p>
          <div className="mt-1 space-y-1">
            {(() => {
              const conf = summary?.by_confidence?.find(c => c.confidence === 'confirmed')
              const inf = summary?.by_confidence?.find(c => c.confidence === 'inferred')
              const cb = conf?.bookings ?? 0
              const ib = inf?.bookings ?? 0
              const total = cb + ib
              const pct = total > 0 ? Math.round((cb / total) * 100) : 0
              return (
                <>
                  <div className="flex justify-between text-xs">
                    <span className="text-emerald-700">✓ Confirmed (value)</span>
                    <span className="font-semibold">{cb} · {fmtMoney(conf?.revenue ?? 0, summaryCurrency)}</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-amber-700">~ Inferred (count)</span>
                    <span className="font-semibold">{ib} · {fmtMoney(inf?.revenue ?? 0, summaryCurrency)}</span>
                  </div>
                  <div className="flex justify-between text-xs border-t pt-1 mt-1 text-gray-500">
                    <span>Confirmed share</span>
                    <span className="font-semibold">{pct}%</span>
                  </div>
                </>
              )
            })()}
          </div>
        </div>
      </div>

      {/* Channel + Branch breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">By Channel</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b">
                <th className="text-left py-2">Channel</th>
                <th className="text-right py-2">Matches</th>
                <th className="text-right py-2">Bookings</th>
                <th className="text-right py-2">Revenue ({summaryCurrency})</th>
              </tr>
            </thead>
            <tbody>
              {summary?.by_channel.map(c => (
                <tr key={c.channel} className="border-b last:border-0">
                  <td className="py-2 capitalize">{c.channel}</td>
                  <td className="text-right py-2">{c.matches}</td>
                  <td className="text-right py-2">{c.bookings}</td>
                  <td className="text-right py-2">{fmtMoney(c.revenue, summaryCurrency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">By Branch</h3>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b">
                <th className="text-left py-2">Branch</th>
                <th className="text-right py-2">Matches</th>
                <th className="text-right py-2">Bookings</th>
                <th className="text-right py-2">Revenue ({summaryCurrency})</th>
              </tr>
            </thead>
            <tbody>
              {summary?.by_branch.map(b => (
                <tr key={b.branch} className="border-b last:border-0">
                  <td className="py-2">{b.branch}</td>
                  <td className="text-right py-2">{b.matches}</td>
                  <td className="text-right py-2">{b.bookings}</td>
                  <td className="text-right py-2">{fmtMoney(b.revenue, summaryCurrency)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Reservation Insights */}
      {insights && insights.total_reservations > 0 && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard
              label="Lead time (days)"
              avg={insights.lead_time_days.avg}
              median={insights.lead_time_days.median}
              min={insights.lead_time_days.min}
              max={insights.lead_time_days.max}
              count={insights.lead_time_days.count}
              digits={1}
            />
            <StatCard
              label="Nights"
              avg={insights.nights.avg}
              median={insights.nights.median}
              min={insights.nights.min}
              max={insights.nights.max}
              count={insights.nights.count}
              digits={1}
            />
            <StatCard
              label="Adults"
              avg={insights.adults.avg}
              median={insights.adults.median}
              min={insights.adults.min}
              max={insights.adults.max}
              count={insights.adults.count}
              digits={1}
            />
            <StatCard
              label={`ADR (${insights.currency})`}
              avg={insights.adr.avg}
              median={insights.adr.median}
              min={insights.adr.min}
              max={insights.adr.max}
              count={insights.adr.count}
              currency={insights.currency}
              isMoney
            />
          </div>

          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-900">By Room Type</h3>
              <span className="text-xs text-gray-400">{insights.total_reservations} reservations</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500 border-b">
                    <th className="text-left py-2">Room Type</th>
                    <th className="text-right py-2">Bookings</th>
                    <th className="text-right py-2">Nights</th>
                    <th className="text-right py-2">Revenue ({insights.currency})</th>
                    <th className="text-right py-2">ADR ({insights.currency})</th>
                  </tr>
                </thead>
                <tbody>
                  {insights.room_types.map(rt => {
                    const adr = rt.nights > 0 ? rt.revenue / rt.nights : 0
                    return (
                      <tr key={rt.room_type} className="border-b last:border-0">
                        <td className="py-2 max-w-md truncate" title={rt.room_type}>{rt.room_type}</td>
                        <td className="text-right py-2">{rt.count}</td>
                        <td className="text-right py-2">{rt.nights}</td>
                        <td className="text-right py-2">{fmtMoney(rt.revenue, insights.currency)}</td>
                        <td className="text-right py-2">{adr > 0 ? fmtMoney(adr, insights.currency) : '--'}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Campaign Intelligence */}
      {campaignInsights && campaignInsights.campaigns.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-sm font-semibold text-gray-900">Campaign Breakdown</h3>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-gray-500">
                Cancel rate <span className={cancelColor(campaignInsights.totals.cancel_rate)}>{fmtPct(campaignInsights.totals.cancel_rate)}</span>
              </span>
              <span className="text-gray-500">
                Confirmed <span className="text-emerald-700 font-medium">{fmtPct(campaignInsights.totals.confirmed_share)}</span>
              </span>
            </div>
          </div>
          <p className="text-xs text-gray-400 mb-3">
            Per-campaign bookings, cancellation, lead time and rooms. Click a row to expand the lead-time histogram + room mix.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-500 border-b">
                  <th className="text-left py-2 w-6"></th>
                  <th className="text-left py-2">Campaign</th>
                  <th className="text-left py-2">Chan</th>
                  <th className="text-right py-2">Bookings</th>
                  <th className="text-right py-2">Revenue ({campaignInsights.currency})</th>
                  <th className="text-right py-2" title="Share of bookings whose revenue confirmed the match">Conf%</th>
                  <th className="text-right py-2">Cancel%</th>
                  <th className="text-right py-2">Avg lead</th>
                  <th className="text-right py-2" title="Website / offline bookings">Web/Off</th>
                  <th className="text-left py-2 pl-3">Target → Actual</th>
                  <th className="text-right py-2">ADR</th>
                </tr>
              </thead>
              <tbody>
                {campaignInsights.campaigns.map((c, i) => {
                  const key = c.campaign_id || `${c.campaign_name}-${i}`
                  const open = expandedCampaign === key
                  const topActual = c.top_actual_countries[0]
                  return (
                    <Fragment key={key}>
                      <tr
                        className="border-b last:border-0 hover:bg-gray-50 cursor-pointer"
                        onClick={() => setExpandedCampaign(open ? null : key)}
                      >
                        <td className="py-2 text-gray-400">
                          <svg className={`w-4 h-4 transition-transform ${open ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
                        </td>
                        <td className="py-2 max-w-[260px] truncate" title={c.campaign_name}>{c.campaign_name}</td>
                        <td className="py-2 capitalize text-gray-500 text-xs">{c.channel}</td>
                        <td className="py-2 text-right">{c.bookings}</td>
                        <td
                          className="py-2 text-right"
                          title={`PMS real: ${fmtMoney(c.matched_revenue, campaignInsights.currency)} · Platform-reported: ${fmtMoney(c.ads_revenue, campaignInsights.currency)}`}
                        >{fmtMoney(c.matched_revenue, campaignInsights.currency)}</td>
                        <td className="py-2 text-right text-emerald-700">{fmtPct(c.confirmed_share)}</td>
                        <td className={`py-2 text-right ${cancelColor(c.cancel_rate)}`}>{fmtPct(c.cancel_rate)}</td>
                        <td className="py-2 text-right">{fmtNum(c.avg_lead_time, 1)}d</td>
                        <td className="py-2 text-right text-xs text-gray-500">{c.website_bookings}/{c.offline_bookings}</td>
                        <td className="py-2 pl-3 whitespace-nowrap">
                          <span className="text-gray-700">{c.target_country || '—'}</span>
                          <span className="text-gray-400 mx-1">→</span>
                          {topActual
                            ? <span className={topActual.country === c.target_country ? 'text-gray-700' : 'text-orange-600 font-medium'}>{topActual.country} ({topActual.bookings})</span>
                            : <span className="text-gray-400">—</span>}
                        </td>
                        <td className="py-2 text-right">{c.adr > 0 ? fmtMoney(c.adr, campaignInsights.currency) : '--'}</td>
                      </tr>
                      {open && (
                        <tr className="bg-gray-50/60">
                          <td colSpan={11} className="py-4 px-6">
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                              <div>
                                <p className="text-xs font-semibold text-gray-600 mb-2">Lead time (days to check-in)</p>
                                <LeadHistogram buckets={c.lead_buckets} />
                              </div>
                              <div>
                                <p className="text-xs font-semibold text-gray-600 mb-2">Top rooms booked</p>
                                <table className="w-full text-xs">
                                  <tbody>
                                    {c.top_rooms.map(rt => (
                                      <tr key={rt.room_type} className="border-b last:border-0 border-gray-100">
                                        <td className="py-1 max-w-[180px] truncate" title={rt.room_type}>{rt.room_type}</td>
                                        <td className="py-1 text-right text-gray-500">{rt.bookings}</td>
                                        <td className="py-1 text-right">{fmtMoney(rt.revenue, campaignInsights.currency)}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                              <div>
                                <p className="text-xs font-semibold text-gray-600 mb-2">Actual guest countries</p>
                                <div className="flex flex-wrap gap-1.5">
                                  {c.top_actual_countries.map(a => (
                                    <span
                                      key={a.country}
                                      className={`inline-block px-2 py-0.5 rounded text-xs ${
                                        a.country === c.target_country
                                          ? 'bg-emerald-100 text-emerald-800'
                                          : a.country === 'Unknown'
                                            ? 'bg-gray-100 text-gray-600'
                                            : 'bg-orange-100 text-orange-800'
                                      }`}
                                    >{a.country} · {a.bookings}</span>
                                  ))}
                                </div>
                                <p className="text-[11px] text-gray-400 mt-2">
                                  Green = matched target · Orange = different country (spillover) · Grey = PMS had no nationality
                                </p>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Target → Actual country flow */}
      {campaignInsights && campaignInsights.country_flow.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-sm font-semibold text-gray-900">Target → Actual Country</h3>
            <span className="text-xs text-gray-500">
              Leakage <span className="text-orange-600 font-semibold">{fmtPct(campaignInsights.totals.leakage_rate)}</span>
              <span className="text-gray-400"> · of {campaignInsights.totals.country_known} known-country bookings</span>
            </span>
          </div>
          <p className="text-xs text-gray-400 mb-3">
            Where the ad was aimed (campaign geo) vs where the guest actually came from. High leakage = budget targeting one country but converting another — consider shifting targets to where guests actually book.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-500 border-b">
                  <th className="text-left py-2">Target geo</th>
                  <th className="text-left py-2">Actual guest</th>
                  <th className="text-right py-2">Bookings</th>
                  <th className="text-right py-2">Revenue ({campaignInsights.currency})</th>
                  <th className="text-left py-2 pl-4">Match</th>
                </tr>
              </thead>
              <tbody>
                {campaignInsights.country_flow.map((f, i) => {
                  const isExact = f.exact > 0
                  const isNull = f.null_count > 0 && f.exact === 0 && f.cross === 0
                  return (
                    <tr key={`${f.target}-${f.actual}-${i}`} className="border-b last:border-0">
                      <td className="py-2 font-medium text-gray-700">{f.target}</td>
                      <td className="py-2">{f.actual}</td>
                      <td className="py-2 text-right">{f.bookings}</td>
                      <td className="py-2 text-right">{fmtMoney(f.revenue, campaignInsights.currency)}</td>
                      <td className="py-2 pl-4">
                        {isExact && <span className="inline-block px-2 py-0.5 rounded text-[11px] bg-emerald-100 text-emerald-800">exact</span>}
                        {!isExact && !isNull && <span className="inline-block px-2 py-0.5 rounded text-[11px] bg-orange-100 text-orange-800">cross-country</span>}
                        {isNull && <span className="inline-block px-2 py-0.5 rounded text-[11px] bg-gray-100 text-gray-600">unknown</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Matches Table */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Matched Bookings</h3>
          <span className="text-xs text-gray-400">Revenue in {listCurrency}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-xs text-gray-600">
                <th className="text-left px-3 py-2">Date</th>
                <th className="text-right px-3 py-2">Revenue ({listCurrency})</th>
                <th className="text-right px-3 py-2">Bookings</th>
                <th className="text-left px-3 py-2">Branch</th>
                <th className="text-left px-3 py-2">Channel</th>
                <th className="text-left px-3 py-2">Campaign</th>
                <th className="text-left px-3 py-2">Ad</th>
                <th className="text-left px-3 py-2">Kind</th>
                <th className="text-left px-3 py-2">Country</th>
                <th className="text-left px-3 py-2">Reservation #</th>
                <th className="text-left px-3 py-2">Guest</th>
                <th className="text-left px-3 py-2">Status</th>
                <th className="text-left px-3 py-2">Room</th>
                <th className="text-left px-3 py-2">Rate Plan</th>
                <th className="text-left px-3 py-2">Source</th>
                <th className="text-left px-3 py-2">Country</th>
                <th className="text-left px-3 py-2">Result</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={17} className="text-center py-8 text-gray-400">Loading...</td></tr>
              )}
              {!loading && matches.length === 0 && (
                <tr><td colSpan={17} className="text-center py-8 text-gray-400">No matches found</td></tr>
              )}
              {matches.map(m => (
                <tr key={m.id} className={`border-t border-gray-100 ${rowBgColor(m.match_result)}`}>
                  <td className="px-3 py-2 whitespace-nowrap">{m.match_date}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap" title={`Ads-reported: ${fmtMoney(m.ads_revenue, listCurrency)}`}>{fmtMoney(m.matched_revenue, listCurrency)}</td>
                  <td className="px-3 py-2 text-right">{m.ads_bookings}</td>
                  <td className="px-3 py-2">{m.branch}</td>
                  <td className="px-3 py-2 capitalize">{m.ads_channel}</td>
                  <td className="px-3 py-2 max-w-xs truncate" title={m.campaign_name || ''}>{m.campaign_name}</td>
                  <td className="px-3 py-2 max-w-[200px] truncate" title={m.ad_name || ''}>{m.ad_name}</td>
                  <td className="px-3 py-2">
                    {m.purchase_kind === 'website' && (
                      <span className="inline-block px-1.5 py-0.5 rounded text-[11px] font-medium bg-blue-100 text-blue-800">website</span>
                    )}
                    {m.purchase_kind === 'offline' && (
                      <span className="inline-block px-1.5 py-0.5 rounded text-[11px] font-medium bg-purple-100 text-purple-800">offline</span>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">{m.ads_country}</td>
                  <td className="px-3 py-2 max-w-[140px] truncate" title={m.reservation_numbers || ''}>{m.reservation_numbers}</td>
                  <td className="px-3 py-2 max-w-[160px] truncate" title={m.guest_names || ''}>{m.guest_names}</td>
                  <td className="px-3 py-2">{m.reservation_statuses}</td>
                  <td className="px-3 py-2 max-w-[140px] truncate" title={m.room_types || ''}>{m.room_types}</td>
                  <td className="px-3 py-2 max-w-[160px] truncate" title={m.rate_plans || ''}>{m.rate_plans}</td>
                  <td className="px-3 py-2">{m.reservation_sources}</td>
                  <td className="px-3 py-2 max-w-[120px] truncate" title={m.matched_country || ''}>{m.matched_country}</td>
                  <td className="px-3 py-2">
                    <div className="flex flex-col gap-1 items-start">
                      <ResultBadge result={m.match_result} />
                      <ConfidenceBadge confidence={m.confidence} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
