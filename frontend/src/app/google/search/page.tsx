'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import RecommendationsSummary from '@/components/RecommendationsSummary'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Campaign {
  id: string
  name: string
  status: string
  daily_budget: number | null
  ta: string | null
  funnel_stage: string | null
}

type Health = 'action' | 'watch' | 'ok' | 'learning'

interface HealthInfo {
  health: Health
  hint: string
  roas: number
}

interface AdGroupRow {
  ad_group_id: string
  ad_group_name: string
  ad_group_status: string
  campaign_id: string
  campaign_name: string
  branch: string
  currency: string
  spend: number
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  roas: number | null
  ctr: number | null
  cpa: number | null
}

const HEALTH_CHIP: Record<Health, { label: string; cls: string; dot: string }> = {
  action: { label: 'Action', cls: 'bg-red-50 text-red-700 border-red-200', dot: 'bg-red-500' },
  watch: { label: 'Watch', cls: 'bg-amber-50 text-amber-700 border-amber-200', dot: 'bg-amber-500' },
  ok: { label: 'OK', cls: 'bg-green-50 text-green-700 border-green-200', dot: 'bg-green-500' },
  learning: { label: 'Learning', cls: 'bg-gray-100 text-gray-500 border-gray-200', dot: 'bg-gray-400' },
}

function HealthChip({ info }: { info?: HealthInfo }) {
  if (!info) return <span className="text-gray-300">—</span>
  const m = HEALTH_CHIP[info.health]
  return (
    <span
      title={info.hint}
      className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-1 rounded-full border ${m.cls}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${m.dot}`} />
      {m.label}
    </span>
  )
}

function RoasCell({ roas }: { roas: number | null }) {
  if (roas === null) return <span className="text-gray-300">—</span>
  const target = Number(typeof window !== 'undefined' ? localStorage.getItem('google_roas_target') : null) || 6
  const color = roas >= target ? 'text-green-600' : roas >= target * 0.8 ? 'text-amber-600' : 'text-red-600'
  return <span className={`font-semibold ${color}`}>{roas.toFixed(2)}x</span>
}

type Tab = 'campaigns' | 'adgroups'

export default function SearchCampaignsPage() {
  const [tab, setTab] = useState<Tab>('campaigns')

  // Campaigns tab state
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [healthMap, setHealthMap] = useState<Record<string, HealthInfo>>({})
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  // Ad Groups tab state
  const [adGroups, setAdGroups] = useState<AdGroupRow[]>([])
  const [agLoading, setAgLoading] = useState(false)
  const [nameFilter, setNameFilter] = useState('Brand')
  const [days, setDays] = useState(30)
  const [sortCol, setSortCol] = useState<keyof AdGroupRow>('roas')
  const [sortAsc, setSortAsc] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/api/google/campaigns?campaign_type=SEARCH&limit=100`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setCampaigns(data.data.campaigns) })
      .finally(() => setLoading(false))

    const target = Number(localStorage.getItem('google_roas_target')) || 6
    fetch(`${API_BASE}/api/google/overview?days=30&roas_target=${target}`, { credentials: 'include' })
      .then(r => r.json())
      .then(res => {
        if (!res.success) return
        const map: Record<string, HealthInfo> = {}
        for (const c of res.data.campaigns) {
          map[c.id] = { health: c.health, hint: c.hint, roas: c.roas }
        }
        setHealthMap(map)
      })
      .catch(() => {})
  }, [])

  const loadAdGroups = () => {
    setAgLoading(true)
    const params = new URLSearchParams({ name_filter: nameFilter, days: String(days) })
    fetch(`${API_BASE}/api/google/ad-groups/comparison?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(res => { if (res.success) setAdGroups(res.data.ad_groups) })
      .catch(() => {})
      .finally(() => setAgLoading(false))
  }

  useEffect(() => {
    if (tab === 'adgroups') loadAdGroups()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  const toggleCampaignStatus = async (c: Campaign) => {
    const action = c.status === 'ACTIVE' ? 'pause' : 'enable'
    if (!confirm(`${action === 'pause' ? 'Pause' : 'Enable'} campaign "${c.name}"?`)) return
    setActionLoading(c.id)
    try {
      const res = await fetch(`${API_BASE}/api/google/campaigns/${c.id}/${action}`, {
        method: 'POST', credentials: 'include',
      }).then(r => r.json())
      if (res.success) {
        setCampaigns(prev => prev.map(p => p.id === c.id ? { ...p, status: res.data.status } : p))
      } else {
        alert(res.error || 'Action failed')
      }
    } catch { alert('Network error') }
    finally { setActionLoading(null) }
  }

  const fmtCurrency = (n: number, currency: string) => {
    const sym = currency === 'VND' ? '₫' : currency === 'JPY' ? '¥' : currency === 'TWD' ? 'NT$' : '$'
    return `${sym}${n.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
  }

  const sortedAdGroups = [...adGroups].sort((a, b) => {
    const va = a[sortCol] ?? (sortAsc ? Infinity : -Infinity)
    const vb = b[sortCol] ?? (sortAsc ? Infinity : -Infinity)
    if (typeof va === 'string' && typeof vb === 'string') return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va)
    return sortAsc ? (va as number) - (vb as number) : (vb as number) - (va as number)
  })

  const handleSort = (col: keyof AdGroupRow) => {
    if (sortCol === col) setSortAsc(v => !v)
    else { setSortCol(col); setSortAsc(false) }
  }

  const SortTh = ({ col, label }: { col: keyof AdGroupRow; label: string }) => (
    <th
      className="text-left px-4 py-3 text-gray-500 font-medium cursor-pointer hover:text-gray-700 select-none whitespace-nowrap"
      onClick={() => handleSort(col)}
    >
      {label} {sortCol === col ? (sortAsc ? '↑' : '↓') : ''}
    </th>
  )

  if (loading) return <div className="p-8 text-gray-500">Loading Search campaigns...</div>

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/google" className="text-gray-400 hover:text-gray-600">&larr;</Link>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Search Campaigns</h1>
          <p className="text-sm text-gray-500">{campaigns.length} campaigns</p>
        </div>
      </div>

      <RecommendationsSummary />

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        {(['campaigns', 'adgroups'] as Tab[]).map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'campaigns' ? 'Campaigns' : 'Ad Group Comparison'}
          </button>
        ))}
      </div>

      {/* Campaigns Tab */}
      {tab === 'campaigns' && (
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-5 py-3 text-gray-500 font-medium">Campaign Name</th>
                  <th className="text-left px-5 py-3 text-gray-500 font-medium">Health</th>
                  <th className="text-left px-5 py-3 text-gray-500 font-medium">Status</th>
                  <th className="text-left px-5 py-3 text-gray-500 font-medium">Budget</th>
                  <th className="text-left px-5 py-3 text-gray-500 font-medium">TA</th>
                  <th className="text-left px-5 py-3 text-gray-500 font-medium">Funnel</th>
                  <th className="text-center px-5 py-3 text-gray-500 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {campaigns.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-5 py-10 text-center text-gray-400">
                      No Search campaigns found
                    </td>
                  </tr>
                ) : (
                  campaigns.map(c => (
                    <tr key={c.id} className="hover:bg-gray-50">
                      <td className="px-5 py-3">
                        <Link href={`/google/search/${c.id}`} className="text-blue-600 hover:underline font-medium">
                          {c.name}
                        </Link>
                      </td>
                      <td className="px-5 py-3"><HealthChip info={healthMap[c.id]} /></td>
                      <td className="px-5 py-3">
                        <span className={`text-xs font-medium ${c.status === 'ACTIVE' ? 'text-green-600' : 'text-gray-400'}`}>
                          {c.status}
                        </span>
                      </td>
                      <td className="px-5 py-3 text-gray-600">
                        {c.daily_budget ? `$${c.daily_budget.toLocaleString('en-US', { maximumFractionDigits: 2 })}` : '-'}
                      </td>
                      <td className="px-5 py-3 text-gray-600">{c.ta || '-'}</td>
                      <td className="px-5 py-3 text-gray-600">{c.funnel_stage || '-'}</td>
                      <td className="px-5 py-3 text-center">
                        <button
                          onClick={() => toggleCampaignStatus(c)}
                          disabled={actionLoading === c.id}
                          className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${
                            c.status === 'ACTIVE'
                              ? 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100'
                              : 'bg-green-50 text-green-700 hover:bg-green-100'
                          } ${actionLoading === c.id ? 'opacity-50' : ''}`}
                        >
                          {actionLoading === c.id ? '...' : c.status === 'ACTIVE' ? 'Pause' : 'Enable'}
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Ad Groups Comparison Tab */}
      {tab === 'adgroups' && (
        <div className="space-y-4">
          {/* Filter bar */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-600 whitespace-nowrap">Ad group name contains:</label>
              <input
                type="text"
                value={nameFilter}
                onChange={e => setNameFilter(e.target.value)}
                className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Brand"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-600">Period:</label>
              <select
                value={days}
                onChange={e => setDays(Number(e.target.value))}
                className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value={7}>Last 7 days</option>
                <option value={14}>Last 14 days</option>
                <option value={30}>Last 30 days</option>
                <option value={60}>Last 60 days</option>
              </select>
            </div>
            <button
              onClick={loadAdGroups}
              disabled={agLoading}
              className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {agLoading ? 'Loading…' : 'Apply'}
            </button>
            <span className="text-sm text-gray-400 ml-auto">{sortedAdGroups.length} ad groups</span>
          </div>

          <div className="bg-white rounded-xl border border-gray-200">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <SortTh col="branch" label="Branch" />
                    <SortTh col="ad_group_name" label="Ad Group" />
                    <SortTh col="campaign_name" label="Campaign" />
                    <th className="text-left px-4 py-3 text-gray-500 font-medium">Status</th>
                    <SortTh col="spend" label="Spend" />
                    <SortTh col="conversions" label="Conv." />
                    <SortTh col="roas" label="ROAS" />
                    <SortTh col="ctr" label="CTR" />
                    <SortTh col="cpa" label="CPA" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {agLoading ? (
                    <tr>
                      <td colSpan={9} className="px-4 py-10 text-center text-gray-400">Loading…</td>
                    </tr>
                  ) : sortedAdGroups.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="px-4 py-10 text-center text-gray-400">
                        No ad groups found matching &quot;{nameFilter}&quot;
                      </td>
                    </tr>
                  ) : (
                    sortedAdGroups.map(ag => (
                      <tr key={ag.ad_group_id} className="hover:bg-gray-50">
                        <td className="px-4 py-3 font-medium text-gray-800 whitespace-nowrap">{ag.branch}</td>
                        <td className="px-4 py-3 text-gray-700 max-w-[200px] truncate" title={ag.ad_group_name}>
                          {ag.ad_group_name}
                        </td>
                        <td className="px-4 py-3 text-gray-500 max-w-[180px] truncate" title={ag.campaign_name}>
                          <Link href={`/google/search/${ag.campaign_id}`} className="hover:text-blue-600 hover:underline">
                            {ag.campaign_name}
                          </Link>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-xs font-medium ${ag.ad_group_status === 'ACTIVE' ? 'text-green-600' : 'text-gray-400'}`}>
                            {ag.ad_group_status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-700 whitespace-nowrap">
                          {ag.spend > 0 ? fmtCurrency(ag.spend, ag.currency) : <span className="text-gray-300">—</span>}
                        </td>
                        <td className="px-4 py-3 text-gray-700">
                          {ag.conversions > 0 ? ag.conversions.toFixed(1) : <span className="text-gray-300">—</span>}
                        </td>
                        <td className="px-4 py-3"><RoasCell roas={ag.roas} /></td>
                        <td className="px-4 py-3 text-gray-600">
                          {ag.ctr !== null ? `${ag.ctr.toFixed(2)}%` : <span className="text-gray-300">—</span>}
                        </td>
                        <td className="px-4 py-3 text-gray-600 whitespace-nowrap">
                          {ag.cpa !== null ? fmtCurrency(ag.cpa, ag.currency) : <span className="text-gray-300">—</span>}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
