'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Sparkles, ExternalLink } from 'lucide-react'
import { fmtMoney } from '@/lib/recHighlights'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface WinningAd {
  combo_id: string
  ad_name: string | null
  branch_id: string
  branch_name: string | null
  target_audience: string | null
  country: string | null
  verdict: string
  spend: number | null
  currency: string | null
  roas: number | null
  conversions: number | null
  headline: string | null
  cta: string | null
  material_id: string | null
  file_url: string | null
  // Live delivery state, matched by (branch, ad_name). `preview_url` opens
  // Meta's own render of the ad; prefixed `live_` so it is never read as the
  // WIN/LOSE verdict beside it.
  preview_url: string | null
  live_status: string | null
  live_active_count: number
  live_ad_count: number
}

interface Account { id: string; account_name: string }

const VERDICT_LIST = ['WIN', 'TEST', 'LOSE']
const VERDICT_COLORS: Record<string, string> = {
  WIN: 'bg-green-100 text-green-700',
  TEST: 'bg-yellow-100 text-yellow-700',
  LOSE: 'bg-red-100 text-red-700',
}

/**
 * Browse individual winning creatives and turn one into an AI brief.
 *
 * Deliberately lean: TA / country / visual-tag filters were removed because
 * TA and country are secondary context here — the ad's totals are what matter
 * — and the visual-tag row only produced results once vision tagging had run.
 * The underlying /creative/search endpoint still supports all of them if a
 * future screen needs that depth.
 */
export default function WinningAdsListTab({ accounts }: { accounts: Account[] }) {
  const [items, setItems] = useState<WinningAd[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [fBranch, setFBranch] = useState('')
  const [fVerdict, setFVerdict] = useState('')
  const [sortBy, setSortBy] = useState('roas')
  const [keyword, setKeyword] = useState('')

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams({ sort_by: sortBy, limit: '100' })
    if (fBranch) params.set('branch_id', fBranch)
    if (fVerdict) params.set('verdict', fVerdict)
    if (keyword.trim()) params.set('q', keyword.trim())

    fetch(`${API_BASE}/api/creative/search?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          setItems(d.data.items || [])
          setTotal(d.data.total || 0)
        }
      })
      .finally(() => setLoading(false))
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [fBranch, fVerdict, sortBy])

  // "Reuse" a winning ad → jump to the AI Brief pre-filtered to its branch + TA.
  // TA is no longer shown in the table but is still the most useful seed for a
  // brief, so it stays in the link.
  const briefHref = (ad: WinningAd) => {
    const p = new URLSearchParams()
    if (ad.branch_id) p.set('branch_id', ad.branch_id)
    if (ad.target_audience) p.set('ta', ad.target_audience)
    return `/winning-ads/brief?${p}`
  }

  return (
    <div>
      <div className="flex flex-wrap gap-3 mb-4 bg-white p-4 rounded-lg border border-gray-200">
        <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={fBranch} onChange={e => setFBranch(e.target.value)}>
          <option value="">All branches</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </select>
        <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={fVerdict} onChange={e => setFVerdict(e.target.value)}>
          <option value="">All verdicts</option>
          {VERDICT_LIST.map(v => <option key={v} value={v}>{v}</option>)}
        </select>
        <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={sortBy} onChange={e => setSortBy(e.target.value)}>
          <option value="roas">Sort: ROAS</option>
          <option value="spend">Sort: Spend</option>
          <option value="conversions">Sort: Conversions</option>
        </select>
        <form className="flex gap-1" onSubmit={e => { e.preventDefault(); load() }}>
          <input
            className="border border-gray-300 rounded px-3 py-2 text-sm w-52"
            placeholder="Keyword (headline / body / ad name)"
            value={keyword}
            onChange={e => setKeyword(e.target.value)}
          />
          <button type="submit" className="px-3 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50">
            Search
          </button>
        </form>
        <div className="text-xs text-gray-500 self-center ml-auto">
          {loading ? 'Loading…' : `${total} ad${total === 1 ? '' : 's'}`}
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
            <tr>
              <th className="text-left px-4 py-3">Ad</th>
              <th className="text-left px-4 py-3">Branch</th>
              <th className="text-right px-4 py-3">ROAS</th>
              <th className="text-right px-4 py-3">Spend</th>
              <th className="text-right px-4 py-3">Conv</th>
              <th className="text-right px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.map(ad => (
              <tr key={ad.combo_id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    {ad.material_id ? (
                      <Link href={`/winning-ads/${ad.material_id}`} className="text-blue-600 hover:underline font-medium">
                        {ad.ad_name || ad.combo_id}
                      </Link>
                    ) : (
                      <span className="font-medium text-gray-900">{ad.ad_name || ad.combo_id}</span>
                    )}
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${VERDICT_COLORS[ad.verdict] || 'bg-gray-100 text-gray-700'}`}>
                      {ad.verdict}
                    </span>
                    {/* Meta's render of the live ad. Hidden when it has been
                        archived/deleted there, rather than shown dead. */}
                    {ad.preview_url && (
                      <a
                        href={ad.preview_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-[10px] text-blue-600 hover:underline bg-blue-50 rounded px-1.5 py-0.5"
                        title={ad.live_ad_count > 1
                          ? `Preview on Meta — ${ad.live_active_count} of ${ad.live_ad_count} ads with this name are still running`
                          : (ad.live_active_count > 0 ? 'Preview on Meta — still running' : 'Preview on Meta — not running now')}
                      >
                        <ExternalLink className="w-3 h-3" /> Preview
                      </a>
                    )}
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5 line-clamp-1">{ad.headline}</div>
                </td>
                <td className="px-4 py-3 text-gray-700">{ad.branch_name || '—'}</td>
                <td className="px-4 py-3 text-right font-mono text-green-700">
                  {ad.roas != null ? ad.roas.toFixed(2) : '—'}
                </td>
                <td className="px-4 py-3 text-right font-mono text-gray-700">
                  {ad.spend != null ? fmtMoney(ad.spend, ad.currency || undefined) : '—'}
                </td>
                <td className="px-4 py-3 text-right font-mono text-gray-700">{ad.conversions ?? '—'}</td>
                <td className="px-4 py-3 text-right">
                  <Link
                    href={briefHref(ad)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-purple-600 text-white rounded hover:bg-purple-700"
                  >
                    <Sparkles className="w-3 h-3" /> Brief
                  </Link>
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-gray-500">
                  No ads match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
