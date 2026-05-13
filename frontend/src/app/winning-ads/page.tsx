'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'

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
  roas: number | null
  conversions: number | null
  cost_per_purchase: number | null
  ctr: number | null
  copy_id: string
  headline: string
  cta: string | null
  material_id: string
  material_type: string
  file_url: string
}

interface Account { id: string; account_name: string; platform: string }

const TA_LIST = ['Solo', 'Couple', 'Friend', 'Group', 'Business']
const VERDICT_LIST = ['WIN', 'TEST', 'LOSE']
const VERDICT_COLORS: Record<string, string> = {
  WIN: 'bg-green-100 text-green-700',
  TEST: 'bg-yellow-100 text-yellow-700',
  LOSE: 'bg-red-100 text-red-700',
}

export default function WinningAdsPage() {
  const [items, setItems] = useState<WinningAd[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [fBranch, setFBranch] = useState('')
  const [fTA, setFTA] = useState('')
  const [fCountry, setFCountry] = useState('')
  const [fVerdict, setFVerdict] = useState('WIN')
  const [sortBy, setSortBy] = useState('roas')

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) setAccounts(d.data.filter((a: Account) => a.platform === 'meta'))
      })
  }, [])

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams({ sort_by: sortBy, sort_dir: 'desc', limit: '100' })
    if (fBranch) params.set('branch_id', fBranch)
    if (fTA) params.set('target_audience', fTA)
    if (fCountry) params.set('country', fCountry)
    if (fVerdict) params.set('verdict', fVerdict)

    fetch(`${API_BASE}/api/winning-ads?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          setItems(d.data.items || [])
          setTotal(d.data.total || 0)
        }
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [fBranch, fTA, fCountry, fVerdict, sortBy])

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Winning Ads</h1>
        <p className="text-sm text-gray-500 mt-1">
          Combos sorted by ROAS. Filter by verdict, TA, branch, or country.
        </p>
      </div>

      <div className="flex flex-wrap gap-3 mb-4 bg-white p-4 rounded-lg border border-gray-200">
        <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={fBranch} onChange={e => setFBranch(e.target.value)}>
          <option value="">All branches</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </select>
        <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={fVerdict} onChange={e => setFVerdict(e.target.value)}>
          <option value="">All verdicts</option>
          {VERDICT_LIST.map(v => <option key={v} value={v}>{v}</option>)}
        </select>
        <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={fTA} onChange={e => setFTA(e.target.value)}>
          <option value="">All TAs</option>
          {TA_LIST.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <input
          className="border border-gray-300 rounded px-3 py-2 text-sm w-24"
          placeholder="Country"
          value={fCountry}
          onChange={e => setFCountry(e.target.value.toUpperCase())}
          maxLength={2}
        />
        <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={sortBy} onChange={e => setSortBy(e.target.value)}>
          <option value="roas">Sort: ROAS</option>
          <option value="spend">Sort: Spend</option>
          <option value="conversions">Sort: Conversions</option>
          <option value="ctr">Sort: CTR</option>
        </select>
        <div className="ml-auto text-xs text-gray-500 self-center">
          {loading ? 'Loading…' : `${total} ad${total === 1 ? '' : 's'}`}
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 text-gray-600 text-xs uppercase tracking-wide">
            <tr>
              <th className="text-left px-4 py-3">Ad</th>
              <th className="text-left px-4 py-3">Verdict</th>
              <th className="text-left px-4 py-3">Branch</th>
              <th className="text-left px-4 py-3">TA</th>
              <th className="text-left px-4 py-3">Country</th>
              <th className="text-right px-4 py-3">ROAS</th>
              <th className="text-right px-4 py-3">Spend</th>
              <th className="text-right px-4 py-3">Conv</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.map(ad => (
              <tr key={ad.combo_id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <Link href={`/winning-ads/${ad.material_id}`} className="text-blue-600 hover:underline font-medium">
                    {ad.ad_name || ad.combo_id}
                  </Link>
                  <div className="text-xs text-gray-500 mt-0.5 line-clamp-1">{ad.headline}</div>
                </td>
                <td className="px-4 py-3">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${VERDICT_COLORS[ad.verdict] || 'bg-gray-100 text-gray-700'}`}>
                    {ad.verdict}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-700">{ad.branch_name || '—'}</td>
                <td className="px-4 py-3 text-gray-700">{ad.target_audience || '—'}</td>
                <td className="px-4 py-3 text-gray-700">{ad.country || '—'}</td>
                <td className="px-4 py-3 text-right font-mono text-green-700">
                  {ad.roas != null ? ad.roas.toFixed(2) : '—'}
                </td>
                <td className="px-4 py-3 text-right font-mono text-gray-700">
                  {ad.spend != null ? ad.spend.toLocaleString() : '—'}
                </td>
                <td className="px-4 py-3 text-right font-mono text-gray-700">{ad.conversions ?? '—'}</td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-12 text-center text-gray-500">
                  No combos match the current filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
