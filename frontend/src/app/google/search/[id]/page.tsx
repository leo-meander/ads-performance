'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import RecBadge from '@/components/RecBadge'
import GoogleInsightsSection from '@/components/GoogleInsightsSection'
import Link from 'next/link'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface CampaignDetail {
  id: string
  name: string
  status: string
  daily_budget: number | null
  ta: string | null
  funnel_stage: string | null
}

interface AdGroup {
  id: string
  name: string
  status: string
  country: string | null
}

interface GoogleAd {
  id: string
  name: string
  status: string
  ad_type: string
  headlines: string[]
  descriptions: string[]
}

interface MetricRow {
  date: string
  spend: number
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  roas: number
  ctr: number
  cpa: number | null
}

export default function SearchCampaignDetail() {
  const { id } = useParams<{ id: string }>()
  const [campaign, setCampaign] = useState<CampaignDetail | null>(null)
  const [adGroups, setAdGroups] = useState<AdGroup[]>([])
  const [ads, setAds] = useState<Record<string, GoogleAd[]>>({})
  const [metrics, setMetrics] = useState<MetricRow[]>([])
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [adGroupActionLoading, setAdGroupActionLoading] = useState<string | null>(null)
  const [adActionLoading, setAdActionLoading] = useState<string | null>(null)
  const [editingBudget, setEditingBudget] = useState(false)
  const [budgetValue, setBudgetValue] = useState('')

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/google/campaigns/${id}`, { credentials: 'include' }).then(r => r.json()),
      fetch(`${API_BASE}/api/google/campaigns/${id}/ad-groups`, { credentials: 'include' }).then(r => r.json()),
      fetch(`${API_BASE}/api/google/campaigns/${id}/metrics`, { credentials: 'include' }).then(r => r.json()),
    ]).then(([campRes, agRes, metRes]) => {
      if (campRes.success) setCampaign(campRes.data)
      if (agRes.success) setAdGroups(agRes.data.ad_groups)
      if (metRes.success) setMetrics(metRes.data.metrics)
    }).finally(() => setLoading(false))
  }, [id])

  const toggleStatus = async () => {
    if (!campaign) return
    const action = campaign.status === 'ACTIVE' ? 'pause' : 'enable'
    if (!confirm(`${action === 'pause' ? 'Pause' : 'Enable'} campaign "${campaign.name}"?`)) return
    setActionLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/google/campaigns/${id}/${action}`, {
        method: 'POST', credentials: 'include',
      }).then(r => r.json())
      if (res.success) setCampaign(prev => prev ? { ...prev, status: res.data.status } : prev)
      else alert(res.error || 'Action failed')
    } catch { alert('Network error') }
    finally { setActionLoading(false) }
  }

  const saveBudget = async () => {
    const val = parseFloat(budgetValue)
    if (!val || val <= 0) { alert('Enter a valid budget'); return }
    setActionLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/google/campaigns/${id}/budget`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ daily_budget: val }),
      }).then(r => r.json())
      if (res.success) {
        setCampaign(prev => prev ? { ...prev, daily_budget: res.data.daily_budget } : prev)
        setEditingBudget(false)
      } else alert(res.error || 'Failed to update budget')
    } catch { alert('Network error') }
    finally { setActionLoading(false) }
  }

  const toggleAdGroupStatus = async (ag: AdGroup, e: React.MouseEvent) => {
    e.stopPropagation()
    const action = ag.status === 'ACTIVE' ? 'pause' : 'enable'
    if (!confirm(`${action === 'pause' ? 'Pause' : 'Enable'} ad group "${ag.name}"?`)) return
    setAdGroupActionLoading(ag.id)
    try {
      const res = await fetch(`${API_BASE}/api/google/ad-groups/${ag.id}/${action}`, {
        method: 'POST', credentials: 'include',
      }).then(r => r.json())
      if (res.success) {
        setAdGroups(prev => prev.map(g => g.id === ag.id ? { ...g, status: res.data.status } : g))
      } else alert(res.error || 'Action failed')
    } catch { alert('Network error') }
    finally { setAdGroupActionLoading(null) }
  }

  const toggleAdStatus = async (ad: GoogleAd) => {
    const action = ad.status === 'ACTIVE' ? 'pause' : 'enable'
    if (!confirm(`${action === 'pause' ? 'Pause' : 'Enable'} ad "${ad.name}"?`)) return
    setAdActionLoading(ad.id)
    try {
      const res = await fetch(`${API_BASE}/api/google/ads/${ad.id}/${action}`, {
        method: 'POST', credentials: 'include',
      }).then(r => r.json())
      if (res.success) {
        setAds(prev => {
          const updated = { ...prev }
          for (const groupId of Object.keys(updated)) {
            updated[groupId] = updated[groupId].map(a => a.id === ad.id ? { ...a, status: res.data.status } : a)
          }
          return updated
        })
      } else alert(res.error || 'Action failed')
    } catch { alert('Network error') }
    finally { setAdActionLoading(null) }
  }

  const loadAds = async (adGroupId: string) => {
    if (expandedGroup === adGroupId) {
      setExpandedGroup(null)
      return
    }
    if (!ads[adGroupId]) {
      try {
        const res = await fetch(`${API_BASE}/api/google/ad-groups/${adGroupId}/ads`, { credentials: 'include' }).then(r => r.json())
        if (res.success) {
          setAds(prev => ({ ...prev, [adGroupId]: res.data.ads }))
        }
      } catch { /* ignore */ }
    }
    setExpandedGroup(adGroupId)
  }

  const fmt = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })

  if (loading) return <div className="p-8 text-gray-500">Loading campaign detail...</div>
  if (!campaign) return <div className="p-8 text-red-500">Campaign not found</div>

  const totalSpend = metrics.reduce((s, m) => s + m.spend, 0)
  const totalRevenue = metrics.reduce((s, m) => s + m.revenue, 0)
  const totalConversions = metrics.reduce((s, m) => s + m.conversions, 0)
  const totalClicks = metrics.reduce((s, m) => s + m.clicks, 0)

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/google/search" className="text-gray-400 hover:text-gray-600">&larr;</Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{campaign.name}</h1>
            <div className="flex items-center gap-3 mt-1 flex-wrap">
              <span className="text-xs bg-green-50 text-green-700 px-2 py-0.5 rounded-full font-medium">SEARCH</span>
              <RecBadge campaignId={campaign.id} />
              <span className={`text-xs font-medium ${campaign.status === 'ACTIVE' ? 'text-green-600' : 'text-gray-400'}`}>
                {campaign.status}
              </span>
              {!editingBudget && campaign.daily_budget && (
                <button onClick={() => { setEditingBudget(true); setBudgetValue(String(campaign.daily_budget)) }}
                  className="text-xs text-gray-500 hover:text-blue-600 cursor-pointer">
                  ${fmt(campaign.daily_budget)}/day
                </button>
              )}
              {editingBudget && (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-gray-500">$</span>
                  <input type="number" value={budgetValue} onChange={e => setBudgetValue(e.target.value)}
                    className="w-24 text-xs border rounded px-2 py-1" autoFocus />
                  <button onClick={saveBudget} disabled={actionLoading}
                    className="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-700 disabled:opacity-50">Save</button>
                  <button onClick={() => setEditingBudget(false)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
                </div>
              )}
            </div>
          </div>
        </div>
        <button
          onClick={toggleStatus}
          disabled={actionLoading}
          className={`text-sm px-4 py-2 rounded-lg font-medium transition-colors ${
            campaign.status === 'ACTIVE'
              ? 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100 border border-yellow-200'
              : 'bg-green-50 text-green-700 hover:bg-green-100 border border-green-200'
          } ${actionLoading ? 'opacity-50' : ''}`}
        >
          {actionLoading ? '...' : campaign.status === 'ACTIVE' ? 'Pause Campaign' : 'Enable Campaign'}
        </button>
      </div>

      {/* KPI Summary */}
      <div className="grid grid-cols-5 gap-4">
        <div className="bg-white rounded-xl border p-4">
          <p className="text-xs text-gray-500">Spend</p>
          <p className="text-xl font-bold">${fmt(totalSpend)}</p>
        </div>
        <div className="bg-white rounded-xl border p-4">
          <p className="text-xs text-gray-500">Clicks</p>
          <p className="text-xl font-bold">{fmt(totalClicks)}</p>
        </div>
        <div className="bg-white rounded-xl border p-4">
          <p className="text-xs text-gray-500">Conversions</p>
          <p className="text-xl font-bold">{totalConversions}</p>
        </div>
        <div className="bg-white rounded-xl border p-4">
          <p className="text-xs text-gray-500">Revenue</p>
          <p className="text-xl font-bold">${fmt(totalRevenue)}</p>
        </div>
        <div className="bg-white rounded-xl border p-4">
          <p className="text-xs text-gray-500">ROAS</p>
          <p className="text-xl font-bold">{totalSpend > 0 ? (totalRevenue / totalSpend).toFixed(2) : '0'}x</p>
        </div>
      </div>

      {/* Ad Groups */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="p-5 border-b border-gray-100">
          <h2 className="font-semibold text-gray-900">Ad Groups ({adGroups.length})</h2>
        </div>
        <div className="divide-y divide-gray-100">
          {adGroups.length === 0 ? (
            <div className="p-8 text-center text-gray-400">No ad groups found</div>
          ) : (
            adGroups.map(ag => (
              <div key={ag.id}>
                <button
                  onClick={() => loadAds(ag.id)}
                  className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 text-left"
                >
                  <div>
                    <p className="font-medium text-gray-900">{ag.name}</p>
                    {ag.country && <span className="text-xs text-gray-500">Country: {ag.country}</span>}
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={(e) => toggleAdGroupStatus(ag, e)}
                      disabled={adGroupActionLoading === ag.id}
                      className={`text-xs px-2.5 py-1 rounded-lg font-medium transition-colors ${
                        ag.status === 'ACTIVE'
                          ? 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100'
                          : 'bg-green-50 text-green-700 hover:bg-green-100'
                      } ${adGroupActionLoading === ag.id ? 'opacity-50' : ''}`}
                    >
                      {adGroupActionLoading === ag.id ? '...' : ag.status === 'ACTIVE' ? 'Pause' : 'Enable'}
                    </button>
                    <span className={`text-xs font-medium ${ag.status === 'ACTIVE' ? 'text-green-600' : 'text-gray-400'}`}>
                      {ag.status}
                    </span>
                    <span className="text-gray-400 text-xs">{expandedGroup === ag.id ? '\u25B2' : '\u25BC'}</span>
                  </div>
                </button>

                {/* Expanded ads section */}
                {expandedGroup === ag.id && (
                  <div className="border-t border-gray-100 bg-gray-50 px-5 py-4">
                    {!ads[ag.id] ? (
                      <p className="text-sm text-gray-400">Loading ads...</p>
                    ) : ads[ag.id].length === 0 ? (
                      <p className="text-sm text-gray-400">No ads in this ad group</p>
                    ) : (
                      <div className="space-y-3">
                        {ads[ag.id].map(ad => (
                          <div key={ad.id} className="bg-white rounded-lg border border-gray-200 p-4">
                            <div className="flex items-center justify-between mb-3">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-medium text-gray-900">{ad.name}</span>
                                <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{ad.ad_type}</span>
                                <span className={`text-xs font-medium ${ad.status === 'ACTIVE' ? 'text-green-600' : 'text-gray-400'}`}>
                                  {ad.status}
                                </span>
                              </div>
                              <button
                                onClick={() => toggleAdStatus(ad)}
                                disabled={adActionLoading === ad.id}
                                className={`text-xs px-2.5 py-1 rounded-lg font-medium transition-colors ${
                                  ad.status === 'ACTIVE'
                                    ? 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100'
                                    : 'bg-green-50 text-green-700 hover:bg-green-100'
                                } ${adActionLoading === ad.id ? 'opacity-50' : ''}`}
                              >
                                {adActionLoading === ad.id ? '...' : ad.status === 'ACTIVE' ? 'Pause' : 'Enable'}
                              </button>
                            </div>
                            {ad.headlines.length > 0 && (
                              <div className="mb-2">
                                <p className="text-[10px] font-semibold text-gray-400 uppercase mb-1">Headlines</p>
                                <div className="flex flex-wrap gap-1">
                                  {ad.headlines.map((h, i) => (
                                    <span key={i} className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded">{h}</span>
                                  ))}
                                </div>
                              </div>
                            )}
                            {ad.descriptions.length > 0 && (
                              <div>
                                <p className="text-[10px] font-semibold text-gray-400 uppercase mb-1">Descriptions</p>
                                {ad.descriptions.map((d, i) => (
                                  <p key={i} className="text-xs text-gray-600 mb-0.5">{d}</p>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Insights — realtime GAQL */}
      <GoogleInsightsSection campaignId={campaign.id} campaignType="SEARCH" />

      {/* Daily Metrics Table */}
      {metrics.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="p-5 border-b border-gray-100">
            <h2 className="font-semibold text-gray-900">Daily Metrics</h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-5 py-3 text-gray-500 font-medium">Date</th>
                  <th className="text-right px-5 py-3 text-gray-500 font-medium">Spend</th>
                  <th className="text-right px-5 py-3 text-gray-500 font-medium">Imp.</th>
                  <th className="text-right px-5 py-3 text-gray-500 font-medium">Clicks</th>
                  <th className="text-right px-5 py-3 text-gray-500 font-medium">CTR</th>
                  <th className="text-right px-5 py-3 text-gray-500 font-medium">Conv.</th>
                  <th className="text-right px-5 py-3 text-gray-500 font-medium">Revenue</th>
                  <th className="text-right px-5 py-3 text-gray-500 font-medium">ROAS</th>
                  <th className="text-right px-5 py-3 text-gray-500 font-medium">CPA</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {metrics.map(m => (
                  <tr key={m.date} className="hover:bg-gray-50">
                    <td className="px-5 py-3 text-gray-700">{m.date}</td>
                    <td className="px-5 py-3 text-right">${fmt(m.spend)}</td>
                    <td className="px-5 py-3 text-right">{fmt(m.impressions)}</td>
                    <td className="px-5 py-3 text-right">{fmt(m.clicks)}</td>
                    <td className="px-5 py-3 text-right">{m.ctr.toFixed(2)}%</td>
                    <td className="px-5 py-3 text-right">{m.conversions}</td>
                    <td className="px-5 py-3 text-right">${fmt(m.revenue)}</td>
                    <td className="px-5 py-3 text-right font-medium">{m.roas.toFixed(2)}x</td>
                    <td className="px-5 py-3 text-right">{m.cpa ? `$${fmt(m.cpa)}` : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
