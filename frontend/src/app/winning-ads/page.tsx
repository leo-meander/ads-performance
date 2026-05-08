'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ExternalLink } from 'lucide-react'

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
  canva_url: string
  canva_design_id: string | null
  canva_captured_at: string | null
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
  const [fVerdict, setFVerdict] = useState('')
  const [sortBy, setSortBy] = useState('roas')
  const [backfilling, setBackfilling] = useState(false)
  const [backfillMsg, setBackfillMsg] = useState('')

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

  const runBackfill = async () => {
    setBackfilling(true)
    setBackfillMsg('')
    try {
      const r = await fetch(`${API_BASE}/api/winning-ads/backfill-canva`, {
        method: 'POST',
        credentials: 'include',
      })
      const d = await r.json()
      if (d.success) {
        const c = d.data
        setBackfillMsg(`Scanned ${c.scanned} approvals — captured ${c.captured} new Canva links.`)
        load()
      } else {
        setBackfillMsg(`Error: ${d.error}`)
      }
    } finally {
      setBackfilling(false)
    }
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Winning Ads</h1>
          <p className="text-sm text-gray-500 mt-1">
            Combos with a Canva working file captured (any verdict). Filter by verdict to find what to clone.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <button
            onClick={runBackfill}
            disabled={backfilling}
            className="px-3 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
          >
            {backfilling ? 'Scanning…' : 'Backfill from approvals'}
          </button>
          {backfillMsg && <p className="text-xs text-gray-600">{backfillMsg}</p>}
        </div>
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
          <option value="captured_at">Sort: Captured at</option>
        </select>
        <div className="ml-auto text-xs text-gray-500 self-center">
          {loading ? 'Loading…' : `${total} ad${total === 1 ? '' : 's'} with Canva`}
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
              <th className="text-left px-4 py-3">Canva</th>
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
                <td className="px-4 py-3">
                  <a
                    href={ad.canva_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-purple-700 hover:underline"
                  >
                    Open <ExternalLink className="w-3 h-3" />
                  </a>
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-12 text-center text-gray-500">
                  No combos with a Canva link yet. Click "Backfill from approvals" to scan existing approvals,
                  or submit a new combo for approval with a Canva working file URL.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
