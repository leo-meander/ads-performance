'use client'

import { useEffect, useMemo, useState } from 'react'
import { Trophy, RefreshCw, Film, Image as ImageIcon, LayoutGrid, Lock, ChevronRight } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface WinAd {
  id: string
  ad_name: string
  account_id: string
  branch_name: string
  combo_id: string | null
  target_audience: string | null
  country: string | null
  spend: number | null
  revenue: number | null
  impressions: number | null
  clicks: number | null
  conversions: number | null
  roas: number | null
  benchmark_roas: number | null
  frozen_at: string | null
}
// One of the ads that FIRST ran in a given month — the audit trail behind the
// "N ads created this month" number. `status` is where it stands now, which is
// not the same question as "did it win this month": an ad is judged the month
// its cumulative evidence clears the bar, so `decided_month` is often later
// than the month it launched.
interface NewAd {
  ad_name: string
  account_id: string
  branch_name: string
  status: 'WIN' | 'LOSE' | 'TEST'
  status_source: 'auto' | 'manual' | 'live' | 'test'
  decided_month: string | null
  first_date: string
  last_date: string | null
  spend: number
  revenue: number
  clicks: number
  conversions: number
  roas: number | null
  benchmark_roas: number | null
}
interface WinMonth {
  month: string
  count: number
  lose_count: number
  tested: number
  win_rate: number | null
  in_progress: boolean
  spend: number
  revenue: number
  conversions: number
  roas: number | null
  new_ads: number
  new_ad_list: NewAd[]
  by_branch: { branch_name: string; count: number }[]
  ads: WinAd[]
}
interface WinData {
  months: WinMonth[]
  total_wins: number
  total_lost: number
  total_tested: number
  overall_win_rate: number | null
  distinct_ads: number
  scope_note: string
  year: number | null
}
interface Account { id: string; account_name: string }

// Which verdict set to show. 'kpi' is the design-team KPI (KOL-named ads and
// Bread excluded); 'all' is the parallel, unfiltered set — every ad, every
// branch — that Mason tracks separately. They are frozen independently on the
// backend (winning_ad_months.scope) against different benchmarks, so the same
// ad can be WIN in one and LOSE in the other. Everything below is identical
// between them except the copy and the branch list.
export type WinScope = 'kpi' | 'all'

const FORMAT_META: Record<string, { label: string; Icon: typeof Film }> = {
  video: { label: 'Video', Icon: Film },
  image: { label: 'Image', Icon: ImageIcon },
  carousel: { label: 'Carousel', Icon: LayoutGrid },
}

// Same derivation the Library table uses: [Image] → image, [Carousel] →
// carousel, everything else → video.
const inferFormat = (adName: string | null): string => {
  const lower = (adName || '').toLowerCase()
  if (lower.includes('[image]')) return 'image'
  if (lower.includes('[carousel]')) return 'carousel'
  return 'video'
}

const nextMonth = (m: string) => {
  const [y, mm] = m.split('-').map(Number)
  return mm === 12 ? `${y + 1}-01` : `${y}-${String(mm + 1).padStart(2, '0')}`
}

// A month the API never returned: nothing was judged in it. `tested: 0` is what
// marks it as a gap rather than a real 0% month, so it renders unclickable —
// there is no detail row to open.
const emptyMonth = (month: string): WinMonth => ({
  month, count: 0, lose_count: 0, tested: 0, win_rate: null, in_progress: false,
  spend: 0, revenue: 0, conversions: 0, roas: null, new_ads: 0, new_ad_list: [],
  by_branch: [], ads: [],
})

// Status pill for an ad in the "created this month" group. WIN/LOSE/TEST is
// the verdict; the source underneath says how firm it is — a live verdict has
// not frozen yet and can still move, which is why it isn't shown as settled.
const STATUS_STYLE: Record<NewAd['status'], string> = {
  WIN: 'bg-green-100 text-green-700 border-green-200',
  LOSE: 'bg-red-100 text-red-700 border-red-200',
  TEST: 'bg-gray-100 text-gray-500 border-gray-200',
}
const STATUS_HINT: Record<NewAd['status_source'], string> = {
  auto: 'Frozen verdict — decided automatically once cumulative evidence cleared the bar.',
  manual: 'Frozen verdict — set by hand for an ad that would never gather enough data on its own.',
  live: 'Not frozen yet: cumulative numbers already score this, but it can still change before the month closes.',
  test: 'Not enough cumulative clicks or bookings yet (needs >2,500 clicks or ≥5 bookings), so it counts toward neither side of the win rate.',
}

const MONTH_LABEL = (m: string) => {
  const [y, mm] = m.split('-')
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${names[Number(mm) - 1] || mm} ${y}`
}

export default function WinningMonthsTab({
  accounts,
  canEdit,
  scope = 'kpi',
}: { accounts: Account[]; canEdit: boolean; scope?: WinScope }) {
  const isAll = scope === 'all'
  const [data, setData] = useState<WinData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [fBranch, setFBranch] = useState('')
  const [selected, setSelected] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [msg, setMsg] = useState('')
  // Collapsed by default — the winners table is the headline; the full
  // created-this-month roster is the follow-up question, not the answer.
  const [showCreated, setShowCreated] = useState(false)

  const load = () => {
    setLoading(true); setError('')
    const p = new URLSearchParams({ scope })
    if (fBranch) p.set('branch_id', fBranch)
    fetch(`${API_BASE}/api/creative/winning-months?${p}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (!d.success) { setError(d.error || 'Failed to load'); return }
        setData(d.data)
        setSelected(prev => (d.data.months.some((m: WinMonth) => m.month === prev) ? prev : d.data.months[0]?.month || ''))
      })
      .catch(() => setError('Failed to load'))
      .finally(() => setLoading(false))
  }
  useEffect(load, [fBranch]) // eslint-disable-line react-hooks/exhaustive-deps

  const recompute = () => {
    setRefreshing(true); setMsg('')
    const p = new URLSearchParams({ scope })
    if (fBranch) p.set('branch_id', fBranch)
    fetch(`${API_BASE}/api/creative/winning-months/recompute?${p}`, { method: 'POST', credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        setMsg(d.success ? `${d.data.awarded} new winner(s) frozen.` : `Error: ${d.error}`)
        if (d.success) load()
      })
      .catch(() => setMsg('Recompute failed'))
      .finally(() => setRefreshing(false))
  }

  // Branches the backend leaves out of this KPI (winning_months_service
  // .EXCLUDED_BRANCHES). Listing one would just render an empty tab — except
  // in the all-ads scope, which covers every branch, Bread included.
  const selectableAccounts = useMemo(
    () => (isAll ? accounts : accounts.filter(a => !/bread/i.test(a.account_name))),
    [accounts, isAll],
  )

  const months = data?.months || []
  const maxCount = Math.max(1, ...months.map(m => m.count))
  // Oldest → newest reads like a trend; the API returns newest first.
  //
  // The API only returns months that produced at least one verdict, so a month
  // where nothing was judged is absent rather than zero. On a timeline that
  // reads as "this month never happened" — fill the gaps back in so the axis
  // stays continuous. Such a month means the ads running then were either
  // still in TEST, or already decided in an earlier month (judged once, ever).
  const chartMonths = useMemo(() => {
    const asc = [...months].reverse()
    if (asc.length < 2) return asc
    const out: WinMonth[] = []
    let cursor = asc[0].month
    for (const m of asc) {
      while (cursor < m.month) { out.push(emptyMonth(cursor)); cursor = nextMonth(cursor) }
      out.push(m)
      cursor = nextMonth(m.month)
    }
    return out
  }, [months])
  const current = months.find(m => m.month === selected) || null

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={fBranch} onChange={e => setFBranch(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="">All Branches</option>
          {selectableAccounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </select>
        {canEdit && (
          <button
            onClick={recompute}
            disabled={refreshing}
            title="Re-run the freeze pass. It can only ADD winners — awards already frozen are never rewritten."
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border border-gray-200 text-gray-600 hover:border-amber-300 hover:text-amber-700 disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} /> Recompute
          </button>
        )}
        {msg && <span className="text-xs text-gray-500">{msg}</span>}
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4 text-xs text-amber-900">
        <div className="font-semibold flex items-center gap-1 mb-2"><Lock className="w-3.5 h-3.5" /> Frozen verdicts</div>
        <ul className="list-disc pl-5 space-y-1">
          <li>Only active ads are evaluated.</li>
          <li>An ad needs <strong>&gt;2,500 clicks</strong> or <strong>≥5 bookings</strong> (cumulative) to be evaluated.</li>
          <li>ROAS above the branch lifetime benchmark = <strong>WIN</strong>. Otherwise = <strong>LOSE</strong>.</li>
          <li>TEST ads are not counted.</li>
          <li>Each ad is judged only once — the WIN/LOSE result is frozen and never re-tested.</li>
          <li><strong>Win Rate</strong> = WIN ads ÷ (WIN + LOSE ads).</li>
          {isAll ? (
            <li>
              <strong>Every ad counts</strong> — nothing is excluded, including
              &ldquo;KOL&rdquo; ads and Bread. The benchmark is each branch&apos;s full blended
              lifetime ROAS, so a verdict here can differ from the KPI tab.
            </li>
          ) : (
            <li>Ads with &ldquo;KOL&rdquo; in the name and Bread are excluded.</li>
          )}
          <li>The report resets each year, but the benchmark remains lifetime.</li>
        </ul>
        {isAll && (
          <p className="mt-2 pt-2 border-t border-amber-200 text-[11px]">
            Tracking view only — the design KPI reported to the team is the
            <strong> Winning by Month</strong> tab. The two are judged separately and
            will not match.
          </p>
        )}
      </div>

      {/* Only the FIRST load blanks the page. Switching branch re-runs the
          same server work, and throwing the chart away to show one word means
          the reader loses their place for the whole round trip — dim the old
          numbers instead and swap them when the new ones land. */}
      {loading && !data && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-500">{error}</p>}

      {!loading && !error && months.length === 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center">
          <Trophy className="w-8 h-8 text-gray-200 mx-auto mb-2" />
          <p className="text-sm text-gray-400">No winning months yet.</p>
          <p className="text-xs text-gray-400 mt-1">
            Needs daily ad metrics (synced from 2026-01-01) and at least one
            {isAll ? ' ad' : ' non-KOL ad'} clearing its month&apos;s benchmark this year.
          </p>
        </div>
      )}

      {months.length > 0 && data && (
        <div className={loading ? 'opacity-50 transition-opacity' : 'transition-opacity'}>
          {/* Monthly counts — the headline number, one bar per month */}
          <div className="bg-white rounded-xl border border-gray-200 p-4 mb-4">
            <div className="flex items-baseline justify-between mb-3">
              <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide">Winning ads per month</h3>
              <p className="text-[11px] text-gray-400">
                {data.total_wins} wins / {data.total_tested} tested
                {data.overall_win_rate != null && <> · {(data.overall_win_rate * 100).toFixed(0)}% win rate</>}
                {' '}· {data.distinct_ads} distinct creatives
              </p>
            </div>
            <div className="flex items-end gap-3 overflow-x-auto pb-1">
              {chartMonths.map(m => {
                const active = m.month === selected
                // A gap is a month the API never returned at all — see
                // emptyMonth, which fills the axis so it stays continuous.
                // Nothing to drill into, so it isn't clickable. A month that
                // judged nothing but DID ship ads is not a gap: it has a
                // created-this-month roster worth opening, which is the whole
                // reason such months get a bucket (see list_winning_months).
                const gap = m.tested === 0 && m.new_ads === 0
                const title = gap
                  ? 'No ad was judged this month — the ads running then were either still in TEST, or had already been decided in an earlier month.'
                  : [
                      ...m.by_branch.map(b => `${b.branch_name}: ${b.count}`),
                      `${m.count} win / ${m.tested} tested${m.win_rate != null ? ` (${(m.win_rate * 100).toFixed(0)}%)` : ''}`,
                      m.in_progress ? 'Still open — losses counted live, so this can still move' : '',
                      // Reference only — new creatives launched, not part of win/tested.
                      `${m.new_ads} ad${m.new_ads === 1 ? '' : 's'} created this month`,
                    ].filter(Boolean).join('\n')
                return (
                  <button
                    key={m.month}
                    onClick={() => { if (!gap) setSelected(m.month) }}
                    disabled={gap}
                    className={`flex flex-col items-center gap-1 min-w-[64px] group ${gap ? 'cursor-default' : ''}`}
                    title={title}
                  >
                    <span className={`text-sm font-bold tabular-nums ${gap ? 'text-gray-300' : active ? 'text-amber-600' : 'text-gray-700'}`}>
                      {gap ? '—' : m.count}
                    </span>
                    <div
                      className={`w-10 rounded-t transition-colors ${
                        gap
                          ? 'bg-gray-100 border border-dashed border-gray-200'
                          : active ? 'bg-amber-500' : 'bg-gray-200 group-hover:bg-amber-200'
                      }`}
                      style={{ height: `${gap ? 6 : Math.max(6, (m.count / maxCount) * 96)}px` }}
                    />
                    <span className={`text-[10px] whitespace-nowrap ${gap ? 'text-gray-300' : active ? 'text-amber-700 font-semibold' : 'text-gray-400'}`}>
                      {MONTH_LABEL(m.month)}
                    </span>
                    {m.win_rate != null && (
                      <span className={`text-[9px] whitespace-nowrap tabular-nums ${active ? 'text-amber-600' : 'text-gray-400'}`}>
                        {(m.win_rate * 100).toFixed(0)}%{m.in_progress ? '*' : ''}
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          {/* The winners of the selected month */}
          {current && (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-100 flex flex-wrap items-center gap-x-4 gap-y-1">
                <h3 className="text-sm font-bold text-gray-900 inline-flex items-center gap-1.5">
                  <Trophy className="w-4 h-4 text-amber-500" /> {MONTH_LABEL(current.month)}
                </h3>
                <span className="text-xs text-gray-500">{current.count} winning ads</span>
                <span
                  className="text-xs text-gray-500"
                  title={current.in_progress ? "Month still open — ads that already crossed the test threshold count as tested now, including losses that haven't frozen yet, so this keeps changing until the month closes" : undefined}
                >
                  {current.win_rate != null
                    ? `${(current.win_rate * 100).toFixed(0)}% win rate (${current.count}/${current.tested} tested)`
                    : 'no tested ads yet'}
                  {current.in_progress && <span className="text-amber-600 font-semibold"> · in progress</span>}
                </span>
                {current.roas !== null && <span className="text-xs text-gray-500">blended {current.roas.toFixed(2)}x</span>}
                <span className="text-xs text-gray-500">{current.conversions} bookings</span>
                <div className="flex flex-wrap gap-1 ml-auto">
                  {current.by_branch.map(b => (
                    <span key={b.branch_name} className="text-[10px] bg-gray-100 text-gray-600 rounded px-1.5 py-0.5">
                      {b.branch_name} · {b.count}
                    </span>
                  ))}
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead><tr className="bg-gray-50 border-b">
                    <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Ad Name</th>
                    <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Branch</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium text-xs" title="Cumulative across every country, TA, and month this ad ran in through the award month — the single number that decided WIN vs the benchmark.">
                      Total ROAS @ award
                    </th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium text-xs">Bookings</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium text-xs">Spend</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium text-xs">Clicks</th>
                  </tr></thead>
                  <tbody>{current.ads.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-6 px-2 text-center text-xs text-gray-400">
                        No ad won this month.
                        {current.new_ads > 0 && ' The ads that launched are listed below.'}
                      </td>
                    </tr>
                  )}{current.ads.map(a => {
                    const fmt = FORMAT_META[inferFormat(a.ad_name)]
                    const Icon = fmt.Icon
                    return (
                      <tr key={a.id} className="border-b border-gray-50 hover:bg-amber-50/40">
                        <td className="py-2 px-2">
                          <p className="text-sm font-medium text-gray-900 max-w-[280px] truncate" title={a.ad_name}>{a.ad_name}</p>
                          <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                            <span className="inline-flex items-center gap-1 text-[10px] text-gray-500 bg-gray-100 rounded px-1.5 py-0.5">
                              <Icon className="w-3 h-3" /> {fmt.label}
                            </span>
                            {/* TA/Country are secondary here — the ROAS column already
                                reflects the total summed across all of them; these are
                                just the dominant values for context, not a breakdown. */}
                            {a.target_audience && (
                              <span className="text-[9px] text-gray-400 bg-gray-50 border border-gray-100 rounded px-1 py-0.5">{a.target_audience}</span>
                            )}
                            {a.country && (
                              <span className="text-[9px] text-gray-400 bg-gray-50 border border-gray-100 rounded px-1 py-0.5">{a.country}</span>
                            )}
                            {/* Straight to the creative's detail drawer — the chip
                                already names it, so landing on a filtered one-row
                                table would just be a click with nothing to choose.
                                `search` stays so the list behind the drawer is that
                                same creative once it's closed. */}
                            {a.combo_id && (
                              <a
                                href={`/creative?search=${encodeURIComponent(a.combo_id)}&combo=${encodeURIComponent(a.combo_id)}`}
                                className="text-[9px] font-mono text-blue-600 bg-blue-50 hover:bg-blue-100 rounded px-1 py-0.5"
                                title="Open this creative's details"
                              >
                                {a.combo_id}
                              </a>
                            )}
                          </div>
                        </td>
                        <td className="py-2 px-2 text-xs text-gray-600">{a.branch_name}</td>
                        <td className="py-2 px-2 text-right text-xs">
                          <span className="font-bold text-green-600">{a.roas != null ? `${a.roas.toFixed(2)}x` : '—'}</span>
                          {a.benchmark_roas != null && <p className="text-[9px] text-gray-400">BM: {a.benchmark_roas.toFixed(2)}x</p>}
                        </td>
                        <td className="py-2 px-2 text-right text-xs tabular-nums">{a.conversions ?? '—'}</td>
                        <td className="py-2 px-2 text-right text-xs tabular-nums">{a.spend != null ? a.spend.toLocaleString(undefined, { maximumFractionDigits: 0 }) : '—'}</td>
                        <td className="py-2 px-2 text-right text-xs tabular-nums">{a.clicks != null ? a.clicks.toLocaleString() : '—'}</td>
                      </tr>
                    )
                  })}</tbody>
                </table>
              </div>

              {/* Every ad that FIRST ran this month — the evidence behind the
                  "N ads created" number. Collapsed by default: the winners
                  above are the headline, this is the "…so where are the other
                  ads?" follow-up. */}
              {current.new_ad_list.length > 0 && (
                <div className="border-t border-gray-100">
                  <button
                    onClick={() => setShowCreated(v => !v)}
                    className="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-gray-50"
                  >
                    <ChevronRight className={`w-3.5 h-3.5 text-gray-400 transition-transform ${showCreated ? 'rotate-90' : ''}`} />
                    <span className="text-xs font-semibold text-gray-700">
                      {current.new_ads} ad{current.new_ads === 1 ? '' : 's'} created in {MONTH_LABEL(current.month)}
                    </span>
                    <span className="text-[11px] text-gray-400">
                      {(['WIN', 'LOSE', 'TEST'] as const)
                        .map(s => ({ s, n: current.new_ad_list.filter(a => a.status === s).length }))
                        .filter(x => x.n > 0)
                        .map(x => `${x.n} ${x.s}`)
                        .join(' · ')}
                    </span>
                    <span className="ml-auto text-[11px] text-gray-400">
                      {showCreated ? 'hide' : 'show'}
                    </span>
                  </button>

                  {showCreated && (
                    <>
                      <p className="px-4 pb-2 text-[11px] text-gray-400">
                        Reference only — these do not feed the win rate above. An ad is judged the month its
                        cumulative evidence clears the bar, so one created here may be decided in a later month.
                      </p>
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead><tr className="bg-gray-50 border-y">
                            <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Ad Name</th>
                            <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Branch</th>
                            <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Status</th>
                            <th className="text-right py-2 px-2 text-gray-500 font-medium text-xs" title="Cumulative across every month this ad has run — the same total the WIN/LOSE rule is judged on.">
                              Total ROAS
                            </th>
                            <th className="text-right py-2 px-2 text-gray-500 font-medium text-xs">Bookings</th>
                            <th className="text-right py-2 px-2 text-gray-500 font-medium text-xs">Spend</th>
                            <th className="text-right py-2 px-2 text-gray-500 font-medium text-xs" title="Cumulative clicks. Needs >2,500 (or ≥5 bookings) to leave TEST.">
                              Clicks
                            </th>
                          </tr></thead>
                          <tbody>{current.new_ad_list.map(a => {
                            const fmt = FORMAT_META[inferFormat(a.ad_name)]
                            const Icon = fmt.Icon
                            return (
                              <tr key={`${a.account_id}-${a.ad_name}`} className="border-b border-gray-50 hover:bg-gray-50/60">
                                <td className="py-2 px-2">
                                  <p className="text-sm text-gray-900 max-w-[280px] truncate" title={a.ad_name}>{a.ad_name}</p>
                                  <span className="inline-flex items-center gap-1 text-[10px] text-gray-500 bg-gray-100 rounded px-1.5 py-0.5 mt-0.5">
                                    <Icon className="w-3 h-3" /> {fmt.label}
                                  </span>
                                </td>
                                <td className="py-2 px-2 text-xs text-gray-600">{a.branch_name}</td>
                                <td className="py-2 px-2">
                                  <span
                                    className={`text-[10px] font-semibold border rounded px-1.5 py-0.5 ${STATUS_STYLE[a.status]}`}
                                    title={STATUS_HINT[a.status_source]}
                                  >
                                    {a.status}
                                    {a.status_source === 'live' && ' (live)'}
                                    {a.status_source === 'manual' && ' (manual)'}
                                  </span>
                                  {/* Only worth showing when it contradicts the month
                                      being viewed — that mismatch IS the explanation. */}
                                  {a.decided_month && a.decided_month !== current.month && (
                                    <p className="text-[9px] text-gray-400 mt-0.5">decided {MONTH_LABEL(a.decided_month)}</p>
                                  )}
                                </td>
                                <td className="py-2 px-2 text-right text-xs">
                                  <span className={a.status === 'WIN' ? 'font-bold text-green-600' : 'text-gray-700'}>
                                    {a.roas != null ? `${a.roas.toFixed(2)}x` : '—'}
                                  </span>
                                  {a.benchmark_roas != null && <p className="text-[9px] text-gray-400">BM: {a.benchmark_roas.toFixed(2)}x</p>}
                                </td>
                                <td className="py-2 px-2 text-right text-xs tabular-nums">{a.conversions}</td>
                                <td className="py-2 px-2 text-right text-xs tabular-nums">{a.spend.toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                                <td className="py-2 px-2 text-right text-xs tabular-nums">{a.clicks.toLocaleString()}</td>
                              </tr>
                            )
                          })}</tbody>
                        </table>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
