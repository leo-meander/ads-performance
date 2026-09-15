'use client'

import { Fragment, useEffect, useState, useCallback, useMemo, useRef, type ReactNode } from 'react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { API_BASE } from '@/lib/api'
import { formatLocalDate } from '@/lib/dates'
import { fmtMoney } from '@/components/dashboard/dashboardUtils'
import { downloadCsv, toCsv, type CsvColumn } from '@/lib/csv'

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
  reservation_ids: string | null
  reservation_numbers: string | null
  guest_names: string | null
  guest_emails: string | null
  reservation_statuses: string | null
  // Joined from the reservations behind this match, in the same order as
  // reservation_numbers. Empty string for a reservation with no date on file.
  check_in_dates: string | null
  check_out_dates: string | null
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

// Rate plans are read PMS-wide, not through the match table: a CRM / direct
// plan never touches an ad, so scoping it to matches would hide it entirely.
type PlanSlice = { bookings: number; revenue: number }
type RatePlan = {
  rate_plan: string
  bookings: number
  canceled: number
  live: number
  cancel_rate: number
  revenue: number
  revenue_net: number
  first_booking: string | null
  last_booking: string | null
  by_status: (PlanSlice & { status: string })[]
  by_country: (PlanSlice & { country: string; country_iso: string | null })[]
  by_branch: (PlanSlice & { branch: string })[]
  by_source: (PlanSlice & { source: string })[]
  by_room: (PlanSlice & { room_type: string })[]
  lead_buckets: Record<string, number>
  nights: Stats
  adults: Stats
  adr: Stats
  lead_time_days: Stats
}
type RatePlans = {
  plans: RatePlan[]
  total_plans: number
  total_reservations: number
  untagged_reservations: number
  currency: string
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
  // Window-wide reservation stats, folded into this response so the page
  // doesn't need a second full scan from /booking-matches/insights.
  overall: Omit<Insights, 'currency' | 'period'>
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

// CSV layout mirrors the raw table, plus the ids / emails the table hides
// for width. Money stays as raw numbers (no thousands separators) so the
// file stays sum-able in Excel/Sheets; the currency lives in the header.
function bookingCsvColumns(currency: string): CsvColumn<BookingMatch>[] {
  return [
    { header: 'Date', value: m => m.match_date },
    { header: 'Branch', value: m => m.branch },
    { header: 'Channel', value: m => m.ads_channel },
    { header: 'Campaign', value: m => m.campaign_name },
    { header: 'Campaign ID', value: m => m.campaign_id },
    { header: 'Ad', value: m => m.ad_name },
    { header: 'Ad ID', value: m => m.ad_id },
    { header: 'Kind', value: m => m.purchase_kind },
    { header: 'Ads Country', value: m => m.ads_country },
    { header: 'Bookings', value: m => m.ads_bookings },
    { header: `Matched Revenue (${currency})`, value: m => m.matched_revenue },
    { header: `Ads Revenue (${currency})`, value: m => m.ads_revenue },
    { header: 'Reservation ID', value: m => m.reservation_ids },
    { header: 'Reservation #', value: m => m.reservation_numbers },
    { header: 'Guest', value: m => m.guest_names },
    { header: 'Guest Email', value: m => m.guest_emails },
    { header: 'Status', value: m => m.reservation_statuses },
    { header: 'Check-in', value: m => m.check_in_dates },
    { header: 'Check-out', value: m => m.check_out_dates },
    { header: 'Room', value: m => m.room_types },
    { header: 'Rate Plan', value: m => m.rate_plans },
    { header: 'Source', value: m => m.reservation_sources },
    { header: 'Matched Country', value: m => m.matched_country },
    { header: 'Result', value: m => m.match_result },
    { header: 'Confidence', value: m => m.confidence },
    { header: 'Matched At', value: m => m.matched_at },
  ]
}
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

// Shared palette (matches the dashboard so colours stay consistent).
const CHART_COLORS = ['#a68a64', '#b8a7d9', '#a3c982', '#7dc4c2', '#eb7373', '#f4b971']
const CHANNEL_COLOR: Record<string, string> = { google: '#7dc4c2', meta: '#b8a7d9' }

// A labelled horizontal bar — the building block for the visual "bar list"
// breakdowns that replace the old dense tables.
function HBar({
  label, sublabel, value, max, color, right, onClick, active,
}: {
  label: string
  sublabel?: string
  value: number
  max: number
  color: string
  right?: ReactNode
  onClick?: () => void
  active?: boolean
}) {
  const pct = max > 0 ? Math.max(1.5, (value / max) * 100) : 0
  const Wrapper: any = onClick ? 'button' : 'div'
  return (
    <Wrapper
      onClick={onClick}
      className={`w-full text-left block ${onClick ? 'hover:bg-gray-50 cursor-pointer' : ''} rounded px-1 py-1 transition-colors ${active ? 'bg-gray-50' : ''}`}
    >
      <div className="flex items-baseline justify-between gap-2 mb-1">
        <span className="text-sm text-gray-700 truncate" title={label}>
          {label}
          {sublabel && <span className="text-gray-400 text-xs ml-1.5">{sublabel}</span>}
        </span>
        <span className="text-xs text-gray-600 whitespace-nowrap flex items-center gap-2">{right}</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
    </Wrapper>
  )
}

// Stacked bar showing exact / cross / unknown split for one target country.
function FlowStack({ exact, cross, nul, max, leakage }: { exact: number; cross: number; nul: number; max: number; leakage: number }) {
  const total = exact + cross + nul
  const scale = max > 0 ? (total / max) * 100 : 0
  const seg = (n: number) => (total > 0 ? (n / total) * 100 : 0)
  return (
    <div className="flex items-center gap-2">
      <div className="h-3.5 bg-gray-100 rounded-full overflow-hidden flex-1" style={{ maxWidth: `${Math.max(8, scale)}%` }}>
        <div className="h-full flex">
          {exact > 0 && <div style={{ width: `${seg(exact)}%`, backgroundColor: '#34d399' }} title={`exact ${exact}`} />}
          {cross > 0 && <div style={{ width: `${seg(cross)}%`, backgroundColor: '#fb923c' }} title={`cross ${cross}`} />}
          {nul > 0 && <div style={{ width: `${seg(nul)}%`, backgroundColor: '#d1d5db' }} title={`unknown ${nul}`} />}
        </div>
      </div>
      {cross > 0 && <span className="text-[11px] text-orange-600 font-medium whitespace-nowrap">{leakage.toFixed(0)}% leak</span>}
    </div>
  )
}

// PMS statuses are free text per property, so colour by meaning, not by an
// enum we don't control.
function statusTone(status: string): string {
  const s = status.toLowerCase()
  if (s.includes('cancel') || s.includes('no_show') || s.includes('no-show')) return 'bg-red-100 text-red-800'
  if (s.includes('check') || s.includes('confirm') || s.includes('stay')) return 'bg-emerald-100 text-emerald-800'
  if (s.includes('pend') || s.includes('hold') || s.includes('option')) return 'bg-amber-100 text-amber-800'
  return 'bg-gray-100 text-gray-700'
}

// One plan's drill-down. Every number here already shipped with the list, so
// opening a plan costs no request.
function RatePlanModal({
  plan, currency, onClose,
}: { plan: RatePlan; currency: string; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const countryMax = Math.max(1, ...plan.by_country.map(c => c.bookings))
  const roomMax = Math.max(1, ...plan.by_room.map(r => r.bookings))
  const sourceMax = Math.max(1, ...plan.by_source.map(s => s.bookings))

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-start md:items-center justify-center p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-3xl my-4 max-h-[88vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-white border-b border-gray-200 px-5 py-3 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-gray-900 truncate" title={plan.rate_plan}>{plan.rate_plan}</h3>
            <p className="text-xs text-gray-400 mt-0.5">
              {plan.first_booking && plan.last_booking
                ? `booked ${plan.first_booking} → ${plan.last_booking}`
                : 'no booking dates on file'}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-xl leading-none shrink-0"
            aria-label="Close"
          >×</button>
        </div>

        <div className="p-5 space-y-5">
          {/* Headline counters */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="border border-gray-200 rounded-lg p-3">
              <p className="text-xs text-gray-500">Bookings</p>
              <p className="text-xl font-bold mt-0.5">{plan.bookings}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">{plan.live} live · {plan.canceled} cancelled</p>
            </div>
            <div className="border border-gray-200 rounded-lg p-3">
              <p className="text-xs text-gray-500">Cancel rate</p>
              <p className={`text-xl font-bold mt-0.5 ${cancelColor(plan.cancel_rate)}`}>{fmtPct(plan.cancel_rate)}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">of all bookings</p>
            </div>
            <div className="border border-gray-200 rounded-lg p-3">
              <p className="text-xs text-gray-500">Revenue ({currency})</p>
              <p className="text-xl font-bold mt-0.5">{fmtMoney(plan.revenue_net, currency)}</p>
              <p className="text-[11px] text-gray-400 mt-0.5" title="Including cancelled bookings">
                gross {fmtMoney(plan.revenue, currency)}
              </p>
            </div>
            <div className="border border-gray-200 rounded-lg p-3">
              <p className="text-xs text-gray-500">ADR ({currency})</p>
              <p className="text-xl font-bold mt-0.5">
                {plan.adr.count > 0 ? fmtMoney(plan.adr.avg, currency) : '--'}
              </p>
              <p className="text-[11px] text-gray-400 mt-0.5">
                {plan.adr.count > 0 ? `med ${fmtMoney(plan.adr.median, currency)}` : 'no priced nights'}
              </p>
            </div>
          </div>

          {/* Status */}
          <div>
            <p className="text-xs font-semibold text-gray-600 mb-2">Status</p>
            <div className="flex flex-wrap gap-1.5">
              {plan.by_status.map(s => (
                <span key={s.status} className={`inline-block px-2 py-0.5 rounded text-xs ${statusTone(s.status)}`}>
                  {s.status} · {s.bookings}
                </span>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Country */}
            <div>
              <p className="text-xs font-semibold text-gray-600 mb-2">Guest country</p>
              <div className="space-y-1.5">
                {plan.by_country.map((c, i) => (
                  <HBar
                    key={c.country}
                    label={c.country}
                    sublabel={c.country_iso || undefined}
                    value={c.bookings}
                    max={countryMax}
                    color={c.country === 'Unknown' ? '#d1d5db' : CHART_COLORS[i % CHART_COLORS.length]}
                    right={<>
                      <span className="text-gray-400">{c.bookings} bk</span>
                      <span className="text-gray-600">{fmtMoney(c.revenue, currency)}</span>
                    </>}
                  />
                ))}
              </div>
            </div>

            {/* Party shape — the closest thing PMS gives us to demographics */}
            <div className="space-y-4">
              <div>
                <p className="text-xs font-semibold text-gray-600 mb-2">Party &amp; stay (live bookings)</p>
                <div className="grid grid-cols-3 gap-2 text-center">
                  {[
                    { label: 'Adults', s: plan.adults },
                    { label: 'Nights', s: plan.nights },
                    { label: 'Lead (d)', s: plan.lead_time_days },
                  ].map(({ label, s }) => (
                    <div key={label} className="border border-gray-200 rounded p-2">
                      <p className="text-[11px] text-gray-500">{label}</p>
                      <p className="text-lg font-semibold">{s.count > 0 ? fmtNum(s.avg, 1) : '--'}</p>
                      <p className="text-[10px] text-gray-400">
                        {s.count > 0 ? `med ${fmtNum(s.median, 1)} · n=${s.count}` : 'no data'}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold text-gray-600 mb-2">Lead time to check-in</p>
                <LeadHistogram buckets={plan.lead_buckets} />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Rooms */}
            <div>
              <p className="text-xs font-semibold text-gray-600 mb-2">Room types</p>
              <div className="space-y-1.5">
                {plan.by_room.map((r, i) => (
                  <HBar
                    key={r.room_type} label={r.room_type} value={r.bookings} max={roomMax}
                    color={CHART_COLORS[i % CHART_COLORS.length]}
                    right={<>
                      <span className="text-gray-400">{r.bookings} bk</span>
                      <span className="text-gray-600">{fmtMoney(r.revenue, currency)}</span>
                    </>}
                  />
                ))}
              </div>
            </div>

            {/* Source + branch */}
            <div className="space-y-4">
              <div>
                <p className="text-xs font-semibold text-gray-600 mb-2">Booking source</p>
                <div className="space-y-1.5">
                  {plan.by_source.map((s, i) => (
                    <HBar
                      key={s.source} label={s.source} value={s.bookings} max={sourceMax}
                      color={CHART_COLORS[i % CHART_COLORS.length]}
                      right={<span className="text-gray-400">{s.bookings} bk</span>}
                    />
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold text-gray-600 mb-2">Branch</p>
                <div className="flex flex-wrap gap-1.5">
                  {plan.by_branch.map(b => (
                    <span key={b.branch} className="inline-block px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700">
                      {b.branch} · {b.bookings}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function BookingMatchesDashboard() {
  // 7 days by default: the window drives how much this page has to scan,
  // and the last week is what the daily read actually asks for.
  const [datePreset, setDatePreset] = useState('7d')
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
  const [campaignInsights, setCampaignInsights] = useState<CampaignInsights | null>(null)
  const [expandedCampaign, setExpandedCampaign] = useState<string | null>(null)
  const [ratePlans, setRatePlans] = useState<RatePlans | null>(null)
  const [ratePlansLoading, setRatePlansLoading] = useState(false)
  const [openPlan, setOpenPlan] = useState<string | null>(null)
  const [showRawTable, setShowRawTable] = useState(false)
  const [matches, setMatches] = useState<BookingMatch[]>([])
  const [listCurrency, setListCurrency] = useState<string>('VND')
  // Two flags, not one: the KPI/chart summary is a single grouped aggregate and
  // lands well before campaign-insights, which walks every matched reservation.
  // Sharing one flag made the cheap half wait for the expensive half.
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [insightsLoading, setInsightsLoading] = useState(false)
  const loading = summaryLoading || insightsLoading
  const [rowsLoading, setRowsLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [runMessage, setRunMessage] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const [downloadError, setDownloadError] = useState<string | null>(null)

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

  // Every endpoint honours the same filters (channel / result / kind /
  // confidence) so the KPI cards and charts reflect exactly what the table shows.
  const buildParams = useCallback(() => {
    const { from, to } = resolveRange()
    if (!from || !to) return null
    const params = new URLSearchParams({ date_from: from, date_to: to })
    if (branchParam) params.set('branches', branchParam)
    if (channel) params.set('channel', channel)
    if (matchResult) params.set('match_result', matchResult)
    if (purchaseKind) params.set('purchase_kind', purchaseKind)
    if (confidenceFilter) params.set('confidence', confidenceFilter)
    return params
  }, [resolveRange, branchParam, channel, matchResult, purchaseKind, confidenceFilter])

  // Charts + KPIs. campaign-insights carries the window-wide reservation stats
  // in `overall`, so there's no separate /insights round trip.
  const fetchData = useCallback(async (signal?: AbortSignal) => {
    const params = buildParams()
    if (!params) return
    setSummaryLoading(true)
    setInsightsLoading(true)
    setRatePlansLoading(true)

    // Both requests are in flight together, but each commits its own state the
    // moment it resolves instead of being held behind Promise.all — the KPI
    // cards and charts appear while campaign-insights is still coming back.
    const load = async (
      path: string,
      apply: (data: any) => void,
      done: (v: boolean) => void,
    ) => {
      try {
        const res = await fetch(`${API_BASE}/api/${path}?${params}`, {
          credentials: 'include', signal,
        }).then(r => r.json())
        if (res.success) apply(res.data)
      } catch (e: any) {
        if (e?.name === 'AbortError') return  // superseded; leave the flag set
      }
      done(false)
    }

    await Promise.all([
      load('booking-matches/summary', setSummary, setSummaryLoading),
      load('booking-matches/campaign-insights', setCampaignInsights, setInsightsLoading),
      // PMS-wide, so it ignores the ads-side filters the other two honour.
      load('booking-matches/rate-plans', setRatePlans, setRatePlansLoading),
    ])
  }, [buildParams])

  // The raw row dump is collapsed by default and nothing above it depends on
  // the rows, so it's only fetched once the user actually opens it.
  const fetchRows = useCallback(async (signal?: AbortSignal) => {
    const params = buildParams()
    if (!params) return
    setRowsLoading(true)
    try {
      const res = await fetch(
        `${API_BASE}/api/booking-matches?${params}`, { credentials: 'include', signal },
      ).then(r => r.json())
      if (res.success) {
        setMatches(res.data.items)
        setListCurrency(res.data.currency || 'VND')
      }
    } catch (e: any) {
      if (e?.name === 'AbortError') return
    }
    setRowsLoading(false)
  }, [buildParams])

  // Aborting on cleanup means a fast filter change cancels the in-flight
  // request instead of racing it — no stale payload overwriting a newer one.
  useEffect(() => {
    const ctrl = new AbortController()
    fetchData(ctrl.signal)
    return () => ctrl.abort()
  }, [fetchData])
  useEffect(() => {
    if (!showRawTable) return
    const ctrl = new AbortController()
    fetchRows(ctrl.signal)
    return () => ctrl.abort()
  }, [showRawTable, fetchRows])

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

  // The table renders at most one API page, and it may not be open at all,
  // so the export re-pulls the whole filtered set page by page instead of
  // dumping `matches`. That way the CSV matches the "N rows" count shown.
  const downloadMatches = useCallback(async () => {
    const params = buildParams()
    if (!params) return
    setDownloading(true)
    setDownloadError(null)
    try {
      const PAGE = 1000  // API caps limit at 1000
      const MAX_ROWS = 50000  // guard against an accidental all-time pull
      const all: BookingMatch[] = []
      let currency = activeCurrency
      let total = 0
      for (let offset = 0; offset < MAX_ROWS; offset += PAGE) {
        const page = new URLSearchParams(params)
        page.set('limit', String(PAGE))
        page.set('offset', String(offset))
        const res = await fetch(
          `${API_BASE}/api/booking-matches?${page}`, { credentials: 'include' },
        ).then(r => r.json())
        if (!res.success) throw new Error(res.error || 'Export failed')
        currency = res.data.currency || currency
        total = res.data.total ?? 0
        all.push(...res.data.items)
        if (res.data.items.length < PAGE || all.length >= total) break
      }
      if (all.length === 0) {
        setDownloadError('Nothing to export for these filters.')
        return
      }
      const { from, to } = resolveRange()
      const scope = selectedBranches.length > 0
        ? selectedBranches.join('-').replace(/\s+/g, '')
        : 'all-branches'
      downloadCsv(
        `booking-matches_${scope}_${from}_${to}.csv`,
        toCsv(all, bookingCsvColumns(currency)),
      )
      if (all.length < total) {
        setDownloadError(`Exported the first ${all.length} of ${total} rows (export cap).`)
      }
    } catch (e: any) {
      setDownloadError(`Export failed: ${e.message}`)
    } finally {
      setDownloading(false)
    }
  }, [buildParams, resolveRange, selectedBranches, activeCurrency])

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
        await Promise.all([fetchData(), showRawTable ? fetchRows() : null])
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
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">Booking from Ads</h1>
            {loading && <span className="text-xs text-gray-400">Loading...</span>}
          </div>
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

      {/* Channel + Branch breakdown — visual */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Channel revenue donut */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Revenue by Channel</h3>
            {summary.by_channel.length > 0 ? (
              <div className="flex items-center">
                <ResponsiveContainer width="55%" height={170}>
                  <PieChart>
                    <Pie
                      data={summary.by_channel.map(c => ({ name: c.channel, value: c.revenue }))}
                      dataKey="value" nameKey="name" cx="50%" cy="50%"
                      innerRadius={42} outerRadius={70} paddingAngle={2}
                    >
                      {summary.by_channel.map(c => (
                        <Cell key={c.channel} fill={CHANNEL_COLOR[c.channel] || '#a68a64'} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v: number, n: string) => [fmtMoney(v, summaryCurrency), n]} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="flex-1 space-y-2">
                  {summary.by_channel.map(c => (
                    <div key={c.channel} className="flex items-center gap-2 text-sm">
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: CHANNEL_COLOR[c.channel] || '#a68a64' }} />
                      <span className="capitalize flex-1">{c.channel}</span>
                      <span className="text-gray-400 text-xs">{c.bookings} bk</span>
                      <span className="font-medium">{fmtMoney(c.revenue, summaryCurrency)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : <p className="text-gray-400 text-sm text-center py-12">No data</p>}
          </div>

          {/* Branch revenue bar list */}
          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Revenue by Branch</h3>
            <div className="space-y-1.5">
              {(() => {
                const rows = [...summary.by_branch].sort((a, b) => b.revenue - a.revenue)
                const max = Math.max(1, ...rows.map(r => r.revenue))
                return rows.map((b, i) => (
                  <HBar
                    key={b.branch} label={b.branch} value={b.revenue} max={max}
                    color={CHART_COLORS[i % CHART_COLORS.length]}
                    right={<>
                      <span className="text-gray-400">{b.bookings} bk</span>
                      <span className="font-medium text-gray-700">{fmtMoney(b.revenue, summaryCurrency)}</span>
                    </>}
                  />
                ))
              })()}
            </div>
          </div>
        </div>
      )}

      {/* Reservation Insights */}
      {campaignInsights && campaignInsights.overall.total_reservations > 0 && (() => {
        const overall = campaignInsights.overall
        const currency = campaignInsights.currency
        return (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard
              label="Lead time (days)"
              avg={overall.lead_time_days.avg}
              median={overall.lead_time_days.median}
              min={overall.lead_time_days.min}
              max={overall.lead_time_days.max}
              count={overall.lead_time_days.count}
              digits={1}
            />
            <StatCard
              label="Nights"
              avg={overall.nights.avg}
              median={overall.nights.median}
              min={overall.nights.min}
              max={overall.nights.max}
              count={overall.nights.count}
              digits={1}
            />
            <StatCard
              label="Adults"
              avg={overall.adults.avg}
              median={overall.adults.median}
              min={overall.adults.min}
              max={overall.adults.max}
              count={overall.adults.count}
              digits={1}
            />
            <StatCard
              label={`ADR (${currency})`}
              avg={overall.adr.avg}
              median={overall.adr.median}
              min={overall.adr.min}
              max={overall.adr.max}
              count={overall.adr.count}
              currency={currency}
              isMoney
            />
          </div>

          <div className="bg-white border border-gray-200 rounded-lg p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-900">Top Rooms Booked</h3>
              <span className="text-xs text-gray-400">{overall.total_reservations} reservations</span>
            </div>
            <div className="space-y-1.5">
              {(() => {
                const rows = [...overall.room_types].sort((a, b) => b.revenue - a.revenue).slice(0, 8)
                const max = Math.max(1, ...rows.map(r => r.revenue))
                return rows.map((rt, i) => (
                  <HBar
                    key={rt.room_type} label={rt.room_type} value={rt.revenue} max={max}
                    color={CHART_COLORS[i % CHART_COLORS.length]}
                    right={<>
                      <span className="text-gray-400">{rt.count} bk</span>
                      <span className="font-medium text-gray-700">{fmtMoney(rt.revenue, currency)}</span>
                    </>}
                  />
                ))
              })()}
            </div>
          </div>
        </div>
        )
      })()}

      {/* Campaign Performance — visual bar list, click to drill in */}
      {campaignInsights && campaignInsights.campaigns.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-sm font-semibold text-gray-900">Campaign Performance</h3>
            <div className="flex items-center gap-3 text-xs">
              <span className="text-gray-500">
                Cancel <span className={cancelColor(campaignInsights.totals.cancel_rate)}>{fmtPct(campaignInsights.totals.cancel_rate)}</span>
              </span>
              <span className="text-gray-500">
                Confirmed <span className="text-emerald-700 font-medium">{fmtPct(campaignInsights.totals.confirmed_share)}</span>
              </span>
            </div>
          </div>
          <p className="text-xs text-gray-400 mb-3">
            Bar length = matched revenue. Click a campaign to see its lead-time, rooms and guest countries.
          </p>
          <div className="space-y-0.5">
            {(() => {
              const max = Math.max(1, ...campaignInsights.campaigns.map(c => c.matched_revenue))
              return campaignInsights.campaigns.map((c, i) => {
                const key = c.campaign_id || `${c.campaign_name}-${i}`
                const open = expandedCampaign === key
                const topActual = c.top_actual_countries[0]
                const leaked = topActual && topActual.country !== c.target_country && topActual.country !== 'Unknown'
                const barColor = CHANNEL_COLOR[c.channel || ''] || CHART_COLORS[i % CHART_COLORS.length]
                const pct = Math.max(1.5, (c.matched_revenue / max) * 100)
                const roomMax = Math.max(1, ...c.top_rooms.map(r => r.revenue))
                return (
                  <div key={key} className="border-b last:border-0 border-gray-100">
                    <button
                      onClick={() => setExpandedCampaign(open ? null : key)}
                      className="w-full text-left py-2 px-1 hover:bg-gray-50 rounded transition-colors"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2 min-w-0">
                          <svg className={`w-3.5 h-3.5 text-gray-400 shrink-0 transition-transform ${open ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" /></svg>
                          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: barColor }} />
                          <span className="text-sm text-gray-800 truncate" title={c.campaign_name}>{c.campaign_name}</span>
                        </div>
                        <span
                          className="text-sm font-medium text-gray-800 whitespace-nowrap"
                          title={`PMS real: ${fmtMoney(c.matched_revenue, campaignInsights.currency)} · Platform-reported: ${fmtMoney(c.ads_revenue, campaignInsights.currency)}`}
                        >{fmtMoney(c.matched_revenue, campaignInsights.currency)}</span>
                      </div>
                      <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden ml-6 mt-1.5">
                        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: barColor }} />
                      </div>
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1.5 ml-6 text-[11px] text-gray-500">
                        <span>{c.bookings} bookings</span>
                        <span className={cancelColor(c.cancel_rate)}>cancel {fmtPct(c.cancel_rate)}</span>
                        <span>lead {fmtNum(c.avg_lead_time, 1)}d</span>
                        <span className="text-emerald-700">conf {fmtPct(c.confirmed_share)}</span>
                        <span>
                          {c.target_country || '—'}<span className="text-gray-300 mx-0.5">→</span>
                          {topActual
                            ? <span className={leaked ? 'text-orange-600 font-medium' : 'text-gray-500'}>{topActual.country}</span>
                            : '—'}
                        </span>
                        {c.adr > 0 && <span>ADR {fmtMoney(c.adr, campaignInsights.currency)}</span>}
                      </div>
                    </button>
                    {open && (
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 px-6 pb-4 pt-2 bg-gray-50/60 rounded-b">
                        <div>
                          <p className="text-xs font-semibold text-gray-600 mb-2">Lead time (days to check-in)</p>
                          <LeadHistogram buckets={c.lead_buckets} />
                        </div>
                        <div>
                          <p className="text-xs font-semibold text-gray-600 mb-2">Top rooms booked</p>
                          <div className="space-y-1.5">
                            {c.top_rooms.map((rt, ri) => (
                              <HBar
                                key={rt.room_type} label={rt.room_type} value={rt.revenue} max={roomMax}
                                color={CHART_COLORS[ri % CHART_COLORS.length]}
                                right={<><span className="text-gray-400">{rt.bookings}</span><span className="text-gray-600">{fmtMoney(rt.revenue, campaignInsights.currency)}</span></>}
                              />
                            ))}
                          </div>
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
                            Green = matched target · Orange = different country (spillover) · Grey = no nationality in PMS
                          </p>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })
            })()}
          </div>
        </div>
      )}

      {/* Target → Actual country flow — stacked bars per target geo */}
      {campaignInsights && campaignInsights.country_flow.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <div className="flex items-center justify-between mb-1">
            <h3 className="text-sm font-semibold text-gray-900">Target → Actual Country</h3>
            <span className="text-xs text-gray-500">
              Leakage <span className="text-orange-600 font-semibold">{fmtPct(campaignInsights.totals.leakage_rate)}</span>
              <span className="text-gray-400"> · of {campaignInsights.totals.country_known} known-country bookings</span>
            </span>
          </div>
          <p className="text-xs text-gray-400 mb-2">
            Each bar is one targeting geo, split by where guests actually came from. Orange = booked from a different country than targeted — high leak means shifting targets to where guests really book.
          </p>
          <div className="flex items-center gap-3 mb-3 text-[11px] text-gray-500">
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: '#34d399' }} /> matched target</span>
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: '#fb923c' }} /> different country</span>
            <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: '#d1d5db' }} /> unknown</span>
          </div>
          <div className="space-y-2.5">
            {(() => {
              // Roll the (target,actual) rows up to one stacked bar per target geo.
              const byTarget: Record<string, { target: string; exact: number; cross: number; nul: number; bookings: number }> = {}
              for (const f of campaignInsights.country_flow) {
                const t = byTarget[f.target] || (byTarget[f.target] = { target: f.target, exact: 0, cross: 0, nul: 0, bookings: 0 })
                t.exact += f.exact; t.cross += f.cross; t.nul += f.null_count; t.bookings += f.bookings
              }
              const rows = Object.values(byTarget).sort((a, b) => b.bookings - a.bookings)
              const max = Math.max(1, ...rows.map(r => r.bookings))
              return rows.map(r => {
                const known = r.exact + r.cross
                const leak = known > 0 ? (r.cross / known) * 100 : 0
                return (
                  <div key={r.target} className="flex items-center gap-3">
                    <span className="text-sm font-medium text-gray-700 w-16 shrink-0">{r.target}</span>
                    <div className="flex-1"><FlowStack exact={r.exact} cross={r.cross} nul={r.nul} max={max} leakage={leak} /></div>
                    <span className="text-xs text-gray-400 w-16 text-right shrink-0">{r.bookings} bk</span>
                  </div>
                )
              })
            })()}
          </div>
        </div>
      )}

      {/* Rate Plans — PMS-wide, click a plan for its guest breakdown */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-gray-900">Rate Plans</h3>
          <span className="text-xs text-gray-400">
            {ratePlansLoading && !ratePlans
              ? 'loading…'
              : ratePlans
                ? <>
                    {ratePlans.total_plans} plans · {ratePlans.total_reservations} reservations
                    {ratePlans.untagged_reservations > 0 && (
                      <span title="No rate plan on the PMS row and none parseable from room_type">
                        {' '}· {ratePlans.untagged_reservations} untagged
                      </span>
                    )}
                  </>
                : null}
          </span>
        </div>
        <p className="text-xs text-gray-400 mb-3">
          Every reservation booked in the window, not just ads-matched ones — this is where CRM and
          direct plans show up. Click a plan for its status, countries and party size.
        </p>
        {ratePlans && ratePlans.plans.length > 0 ? (
          <div className="space-y-1.5">
            {(() => {
              const max = Math.max(1, ...ratePlans.plans.map(p => p.bookings))
              return ratePlans.plans.map((p, i) => {
                const topCountry = p.by_country[0]
                return (
                  <HBar
                    key={p.rate_plan}
                    label={p.rate_plan}
                    sublabel={topCountry ? `${topCountry.country} ${topCountry.bookings}` : undefined}
                    value={p.bookings}
                    max={max}
                    color={CHART_COLORS[i % CHART_COLORS.length]}
                    onClick={() => setOpenPlan(p.rate_plan)}
                    active={openPlan === p.rate_plan}
                    right={<>
                      <span className="text-gray-400">{p.bookings} bk</span>
                      <span className={cancelColor(p.cancel_rate)}>{fmtPct(p.cancel_rate)} canc</span>
                      <span className="font-medium text-gray-700">
                        {fmtMoney(p.revenue_net, ratePlans.currency)}
                      </span>
                    </>}
                  />
                )
              })
            })()}
          </div>
        ) : (
          <p className="text-xs text-gray-400 py-4 text-center">
            {ratePlansLoading ? 'Loading rate plans…' : 'No rate plan on any reservation in this window.'}
          </p>
        )}
      </div>

      {openPlan && ratePlans && (() => {
        const plan = ratePlans.plans.find(p => p.rate_plan === openPlan)
        if (!plan) return null
        return (
          <RatePlanModal
            plan={plan}
            currency={ratePlans.currency}
            onClose={() => setOpenPlan(null)}
          />
        )
      })()}

      {/* Matches Table */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-semibold text-gray-900">Matched Bookings</h3>
            <span className="text-xs text-gray-400">
              {summary?.total_matches ?? 0} rows · {showRawTable ? listCurrency : summaryCurrency}
              {showRawTable && matches.length < (summary?.total_matches ?? 0) && (
                <span className="ml-1">(showing first {matches.length})</span>
              )}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={downloadMatches}
              disabled={downloading || (summary?.total_matches ?? 0) === 0}
              title="Download every row matching the current filters as CSV"
              className="px-2 py-1 border border-gray-300 rounded text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40"
            >
              {downloading ? 'Preparing...' : 'Download CSV'}
            </button>
            <button
              onClick={() => setShowRawTable(v => !v)}
              className="text-xs font-medium text-blue-600 hover:text-blue-700"
            >
              {showRawTable ? 'Hide details ▲' : 'Show raw rows ▼'}
            </button>
          </div>
        </div>
        {downloadError && (
          <div className="px-4 py-2 bg-amber-50 border-b border-amber-200 text-xs text-amber-800">
            {downloadError}
          </div>
        )}
        {showRawTable && (
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
                <th className="text-left px-3 py-2">Reservation ID</th>
                <th className="text-left px-3 py-2">Reservation #</th>
                <th className="text-left px-3 py-2">Guest</th>
                <th className="text-left px-3 py-2">Status</th>
                <th className="text-left px-3 py-2">Check-in</th>
                <th className="text-left px-3 py-2">Check-out</th>
                <th className="text-left px-3 py-2">Room</th>
                <th className="text-left px-3 py-2">Rate Plan</th>
                <th className="text-left px-3 py-2">Source</th>
                <th className="text-left px-3 py-2">Country</th>
                <th className="text-left px-3 py-2">Result</th>
              </tr>
            </thead>
            <tbody>
              {rowsLoading && (
                <tr><td colSpan={20} className="text-center py-8 text-gray-400">Loading...</td></tr>
              )}
              {!rowsLoading && matches.length === 0 && (
                <tr><td colSpan={20} className="text-center py-8 text-gray-400">No matches found</td></tr>
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
                  <td className="px-3 py-2 max-w-[160px] truncate font-mono text-xs" title={m.reservation_ids || ''}>{m.reservation_ids}</td>
                  <td className="px-3 py-2 max-w-[140px] truncate" title={m.reservation_numbers || ''}>{m.reservation_numbers}</td>
                  <td className="px-3 py-2 max-w-[160px] truncate" title={m.guest_names || ''}>{m.guest_names}</td>
                  <td className="px-3 py-2">{m.reservation_statuses}</td>
                  <td className="px-3 py-2 whitespace-nowrap max-w-[120px] truncate" title={m.check_in_dates || ''}>{m.check_in_dates}</td>
                  <td className="px-3 py-2 whitespace-nowrap max-w-[120px] truncate" title={m.check_out_dates || ''}>{m.check_out_dates}</td>
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
        )}
      </div>
    </div>
  )
}
