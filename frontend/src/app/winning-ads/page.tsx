'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Sparkles } from 'lucide-react'
import { fmtMoney } from '@/lib/recHighlights'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface FigmaCreative {
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
}

interface Account { id: string; account_name: string; platform: string }

const TA_LIST = ['Solo', 'Couple', 'Friend', 'Group', 'Business']
const VERDICT_LIST = ['WIN', 'TEST', 'LOSE']
const VERDICT_COLORS: Record<string, string> = {
  WIN: 'bg-green-100 text-green-700',
  TEST: 'bg-yellow-100 text-yellow-700',
  LOSE: 'bg-red-100 text-red-700',
}

// Visual-tag vocabulary (mirrors creative_vision_tagger.TAG_VOCAB).
const TAG_FILTERS: { category: string; label: string; values: string[] }[] = [
  { category: 'emotional_angle', label: 'Emotion', values: ['aspirational', 'calm', 'urgency', 'informational', 'playful', 'luxe', 'other'] },
  { category: 'scene_type', label: 'Scene', values: ['room', 'exterior', 'food', 'activity', 'aerial', 'abstract', 'mixed'] },
  { category: 'human_presence', label: 'People', values: ['solo', 'couple', 'group', 'none'] },
  { category: 'color_palette', label: 'Palette', values: ['warm', 'cool', 'neutral', 'high_contrast', 'pastel', 'dark', 'other'] },
]

export default function FigmaCreativesPage() {
  const [items, setItems] = useState<FigmaCreative[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [fBranch, setFBranch] = useState('')
  const [fTA, setFTA] = useState('')
  const [fCountry, setFCountry] = useState('')
  const [fVerdict, setFVerdict] = useState('') // all verdicts by default
  const [sortBy, setSortBy] = useState('roas')
  const [keyword, setKeyword] = useState('')
  const [tagSel, setTagSel] = useState<Record<string, string>>({})

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) setAccounts(d.data.filter((a: Account) => a.platform === 'meta'))
      })
  }, [])

  const load = () => {
    setLoading(true)
    // Lists every winning ad for the scoped filters (no source restriction).
    const params = new URLSearchParams({ sort_by: sortBy, limit: '100', match: 'all' })
    if (fBranch) params.set('branch_id', fBranch)
    if (fTA) params.set('target_audience', fTA)
    if (fCountry) params.set('country', fCountry)
    if (fVerdict) params.set('verdict', fVerdict)
    if (keyword.trim()) params.set('q', keyword.trim())
    Object.entries(tagSel).forEach(([cat, val]) => {
      if (val) params.append('tags', `${cat}:${val}`)
    })

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
  useEffect(() => { load() }, [fBranch, fTA, fCountry, fVerdict, sortBy, tagSel])

  const activeTagCount = Object.values(tagSel).filter(Boolean).length

  // "Reuse" a winning ad → jump to the AI Brief pre-filtered to its branch + TA.
  const briefHref = (ad: FigmaCreative) => {
    const p = new URLSearchParams()
    if (ad.branch_id) p.set('branch_id', ad.branch_id)
    if (ad.target_audience) p.set('ta', ad.target_audience)
    return `/winning-ads/brief?${p}`
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Winning Ads</h1>
          <p className="text-sm text-gray-500 mt-1">
            Your branches&apos; winning ads. Click “Brief” to turn one into an AI creative brief.
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/winning-ads/brief"
            className="inline-flex items-center gap-1.5 px-3 py-2 text-sm bg-purple-600 text-white rounded hover:bg-purple-700"
          >
            <Sparkles className="w-4 h-4" /> AI Brief
          </Link>
        </div>
      </div>

      {/* Base filters */}
      <div className="flex flex-wrap gap-3 mb-3 bg-white p-4 rounded-lg border border-gray-200">
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
        </select>
        <form
          className="flex gap-1"
          onSubmit={e => { e.preventDefault(); load() }}
        >
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
          {loading ? 'Loading…' : `${total} winning ad${total === 1 ? '' : 's'}`}
        </div>
      </div>

      {/* Visual-tag filters */}
      <div className="flex flex-wrap items-center gap-3 mb-4 bg-white p-4 rounded-lg border border-gray-200">
        <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Visual tags</span>
        {TAG_FILTERS.map(tf => (
          <select
            key={tf.category}
            className="border border-gray-300 rounded px-3 py-2 text-sm"
            value={tagSel[tf.category] || ''}
            onChange={e => setTagSel(prev => ({ ...prev, [tf.category]: e.target.value }))}
          >
            <option value="">{tf.label}: any</option>
            {tf.values.map(v => <option key={v} value={v}>{tf.label}: {v}</option>)}
          </select>
        ))}
        {activeTagCount > 0 && (
          <button
            onClick={() => setTagSel({})}
            className="text-xs text-blue-600 hover:underline"
          >
            Clear {activeTagCount} tag{activeTagCount === 1 ? '' : 's'}
          </button>
        )}
        <span className="text-xs text-gray-400 ml-auto">All selected tags must match (AND)</span>
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
              <th className="text-right px-4 py-3"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.map(ad => (
              <tr key={ad.combo_id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  {ad.material_id ? (
                    <Link href={`/winning-ads/${ad.material_id}`} className="text-blue-600 hover:underline font-medium">
                      {ad.ad_name || ad.combo_id}
                    </Link>
                  ) : (
                    <span className="font-medium text-gray-900">{ad.ad_name || ad.combo_id}</span>
                  )}
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
                <td colSpan={9} className="px-4 py-12 text-center text-gray-500">
                  No winning ads match the current filters.
                  {activeTagCount > 0 && ' Try fewer visual tags, or check that materials have been vision-tagged.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
