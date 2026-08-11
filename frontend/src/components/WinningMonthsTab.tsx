'use client'

import { useEffect, useMemo, useState } from 'react'
import { Trophy, RefreshCw, Film, Image as ImageIcon, LayoutGrid, Lock } from 'lucide-react'

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
  spend: 0, revenue: 0, conversions: 0, roas: null, by_branch: [], ads: [],
})

const MONTH_LABEL = (m: string) => {
  const [y, mm] = m.split('-')
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${names[Number(mm) - 1] || mm} ${y}`
}

export default function WinningMonthsTab({ accounts, canEdit }: { accounts: Account[]; canEdit: boolean }) {
  const [data, setData] = useState<WinData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [fBranch, setFBranch] = useState('')
  const [selected, setSelected] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [msg, setMsg] = useState('')

  const load = () => {
    setLoading(true); setError('')
    const p = new URLSearchParams()
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
    const p = new URLSearchParams()
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
  // .EXCLUDED_BRANCHES). Listing one would just render an empty tab.
  const selectableAccounts = useMemo(
    () => accounts.filter(a => !/bread/i.test(a.account_name)),
    [accounts],
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

      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4 text-xs text-amber-900 flex flex-wrap items-start gap-x-4 gap-y-1">
        <span className="font-semibold inline-flex items-center gap-1"><Lock className="w-3.5 h-3.5" /> Frozen verdicts</span>
        <span>An ad must still be running this month to be a candidate. It wins the month its <strong>cumulative</strong> ROAS (all history to date) clears the branch&apos;s <strong>current</strong> (lifetime-to-date) blended ROAS, once it has enough <strong>cumulative</strong> data: &gt; 2,500 clicks or ≥ 5 bookings, added up across every month it&apos;s run — not any single month&apos;s isolated total. Below that it&apos;s still TEST and isn&apos;t counted at all.</span>
        <span><strong>Win rate</strong> = winning ads ÷ every ad that cleared the test threshold that month (win + lose), not the whole ad list.</span>
        <span>An ad is judged <strong>once, ever</strong>: once it has a win/lose verdict in some month, it&apos;s never re-tested in a later month — the Library&apos;s live verdict keeps moving with the benchmark, these rows don&apos;t.</span>
        <span className="font-semibold">All ads count except ones with &ldquo;KOL&rdquo; in the name (paid amplification of KOL content). Bread is not covered by this KPI.</span>
        <span className="font-semibold">Totals below cover {data?.year ?? 'this year'} only — the year-to-date view resets every January. The benchmark itself stays lifetime, so narrowing the year never re-judges an ad.</span>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-500">{error}</p>}

      {!loading && !error && months.length === 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center">
          <Trophy className="w-8 h-8 text-gray-200 mx-auto mb-2" />
          <p className="text-sm text-gray-400">No winning months yet.</p>
          <p className="text-xs text-gray-400 mt-1">
            Needs daily ad metrics (synced from 2026-01-01) and at least one non-KOL ad clearing its month&apos;s benchmark this year.
          </p>
        </div>
      )}

      {!loading && months.length > 0 && data && (
        <>
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
                // tested === 0 marks a gap month the API never returned — see
                // emptyMonth. Nothing to drill into, so it isn't clickable.
                const gap = m.tested === 0
                const title = gap
                  ? 'No ad was judged this month — the ads running then were either still in TEST, or had already been decided in an earlier month.'
                  : [
                      ...m.by_branch.map(b => `${b.branch_name}: ${b.count}`),
                      `${m.count} win / ${m.tested} tested${m.win_rate != null ? ` (${(m.win_rate * 100).toFixed(0)}%)` : ''}`,
                      m.in_progress ? 'Still open — win rate provisional' : '',
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
                  title={current.in_progress ? "Month still open — win rate will keep changing until it closes" : undefined}
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
                  <tbody>{current.ads.map(a => {
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
                            {a.combo_id && (
                              <a
                                href={`/creative?search=${encodeURIComponent(a.combo_id)}`}
                                className="text-[9px] font-mono text-blue-600 bg-blue-50 hover:bg-blue-100 rounded px-1 py-0.5"
                                title="Open this creative in the Library"
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
            </div>
          )}
        </>
      )}
    </div>
  )
}
