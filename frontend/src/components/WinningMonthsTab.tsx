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
  distinct_ads: number
  scope_note: string
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

  const months = data?.months || []
  const maxCount = Math.max(1, ...months.map(m => m.count))
  // Oldest → newest reads like a trend; the API returns newest first.
  const chartMonths = useMemo(() => [...months].reverse(), [months])
  const current = months.find(m => m.month === selected) || null

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={fBranch} onChange={e => setFBranch(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="">All Branches</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
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
        <span className="font-semibold inline-flex items-center gap-1"><Lock className="w-3.5 h-3.5" /> Frozen awards</span>
        <span>An ad wins a month when its ROAS <strong>that month</strong> clears the branch&apos;s blended ROAS for the same month (and it has enough data: &gt; 4,500 clicks or ≥ 5 bookings).</span>
        <span>Once awarded it stays a winner forever — the Library&apos;s live verdict keeps moving with the benchmark, these rows don&apos;t.</span>
        <span className="font-semibold">Only ads with &ldquo;CRTV&rdquo; in the name are counted.</span>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && <p className="text-sm text-red-500">{error}</p>}

      {!loading && !error && months.length === 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center">
          <Trophy className="w-8 h-8 text-gray-200 mx-auto mb-2" />
          <p className="text-sm text-gray-400">No winning months yet.</p>
          <p className="text-xs text-gray-400 mt-1">
            Needs daily ad metrics (synced from 2026-05-01) and at least one CRTV ad clearing its month&apos;s benchmark.
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
                {data.total_wins} awards · {data.distinct_ads} distinct creatives
              </p>
            </div>
            <div className="flex items-end gap-3 overflow-x-auto pb-1">
              {chartMonths.map(m => {
                const active = m.month === selected
                return (
                  <button
                    key={m.month}
                    onClick={() => setSelected(m.month)}
                    className="flex flex-col items-center gap-1 min-w-[64px] group"
                    title={m.by_branch.map(b => `${b.branch_name}: ${b.count}`).join('\n')}
                  >
                    <span className={`text-sm font-bold tabular-nums ${active ? 'text-amber-600' : 'text-gray-700'}`}>{m.count}</span>
                    <div
                      className={`w-10 rounded-t transition-colors ${active ? 'bg-amber-500' : 'bg-gray-200 group-hover:bg-amber-200'}`}
                      style={{ height: `${Math.max(6, (m.count / maxCount) * 96)}px` }}
                    />
                    <span className={`text-[10px] whitespace-nowrap ${active ? 'text-amber-700 font-semibold' : 'text-gray-400'}`}>
                      {MONTH_LABEL(m.month)}
                    </span>
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
                    <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">TA</th>
                    <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Country</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium text-xs">ROAS @ award</th>
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
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <span className="inline-flex items-center gap-1 text-[10px] text-gray-500 bg-gray-100 rounded px-1.5 py-0.5">
                              <Icon className="w-3 h-3" /> {fmt.label}
                            </span>
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
                        <td className="py-2 px-2"><span className="text-xs px-1.5 py-0.5 rounded bg-gray-100">{a.target_audience || '—'}</span></td>
                        <td className="py-2 px-2 text-xs text-gray-600">{a.country || '—'}</td>
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
