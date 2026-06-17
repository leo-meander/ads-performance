'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import RecommendationsSummary from '@/components/RecommendationsSummary'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface AssetGroup {
  id: string
  campaign_id: string
  campaign_name: string | null
  name: string
  status: string
  final_urls: string[]
  asset_count: number
}

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

const HEALTH_CHIP: Record<Health, { label: string; cls: string; dot: string }> = {
  action: { label: 'Action', cls: 'bg-red-50 text-red-700 border-red-200', dot: 'bg-red-500' },
  watch: { label: 'Watch', cls: 'bg-amber-50 text-amber-700 border-amber-200', dot: 'bg-amber-500' },
  ok: { label: 'OK', cls: 'bg-green-50 text-green-700 border-green-200', dot: 'bg-green-500' },
  learning: { label: 'Learning', cls: 'bg-gray-100 text-gray-500 border-gray-200', dot: 'bg-gray-400' },
}

function HealthChip({ info }: { info?: HealthInfo }) {
  if (!info) return null
  const m = HEALTH_CHIP[info.health]
  return (
    <span
      title={info.hint}
      className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-0.5 rounded-full border ${m.cls}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${m.dot}`} />
      {m.label}
    </span>
  )
}

export default function PMaxPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [assetGroups, setAssetGroups] = useState<AssetGroup[]>([])
  const [healthMap, setHealthMap] = useState<Record<string, HealthInfo>>({})
  const [loading, setLoading] = useState(true)
  const [expandedCampaign, setExpandedCampaign] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  const fetchData = () => {
    setLoading(true)
    const target = Number(localStorage.getItem('google_roas_target')) || 6
    Promise.all([
      fetch(`${API_BASE}/api/google/campaigns?campaign_type=PERFORMANCE_MAX&limit=100`, { credentials: 'include' }).then(r => r.json()),
      fetch(`${API_BASE}/api/google/asset-groups?limit=200`, { credentials: 'include' }).then(r => r.json()),
      fetch(`${API_BASE}/api/google/overview?days=30&roas_target=${target}`, { credentials: 'include' }).then(r => r.json()),
    ]).then(([campRes, agRes, ovRes]) => {
      if (campRes.success) setCampaigns(campRes.data.campaigns)
      if (agRes.success) setAssetGroups(agRes.data.asset_groups)
      if (ovRes.success) {
        const map: Record<string, HealthInfo> = {}
        for (const c of ovRes.data.campaigns) {
          map[c.id] = { health: c.health, hint: c.hint, roas: c.roas }
        }
        setHealthMap(map)
      }
    }).finally(() => setLoading(false))
  }

  useEffect(() => { fetchData() }, [])

  const toggleCampaignStatus = async (c: Campaign, e: React.MouseEvent) => {
    e.stopPropagation()
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

  const fmtCurrency = (n: number) => `$${n.toLocaleString('en-US', { maximumFractionDigits: 2 })}`

  if (loading) return <div className="p-8 text-gray-500">Loading PMax campaigns...</div>

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/google" className="text-gray-400 hover:text-gray-600">&larr;</Link>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Performance Max Campaigns</h1>
          <p className="text-sm text-gray-500">{campaigns.length} campaigns, {assetGroups.length} asset groups</p>
        </div>
      </div>

      <RecommendationsSummary />

      {campaigns.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400">
          No PMax campaigns found. Sync Google Ads data first.
        </div>
      ) : (
        <div className="space-y-3">
          {campaigns.map((c) => {
            const groups = assetGroups.filter(ag => ag.campaign_id === c.id)
            const isExpanded = expandedCampaign === c.id

            return (
              <div key={c.id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                <button
                  onClick={() => setExpandedCampaign(isExpanded ? null : c.id)}
                  className="w-full flex items-center justify-between p-5 hover:bg-gray-50 transition-colors text-left"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center text-blue-600 font-bold text-sm">
                      PM
                    </div>
                    <div>
                      <Link href={`/google/pmax/${c.id}`} className="font-medium text-gray-900 hover:text-blue-600">
                        {c.name}
                      </Link>
                      <div className="flex items-center gap-3 mt-1">
                        <HealthChip info={healthMap[c.id]} />
                        <span className={`text-xs ${c.status === 'ACTIVE' ? 'text-green-600' : 'text-gray-400'}`}>
                          {c.status}
                        </span>
                        {c.daily_budget && <span className="text-xs text-gray-500">{fmtCurrency(c.daily_budget)}/day</span>}
                        {c.ta && <span className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">{c.ta}</span>}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      onClick={(e) => toggleCampaignStatus(c, e)}
                      disabled={actionLoading === c.id}
                      className={`text-xs px-3 py-1.5 rounded-lg font-medium transition-colors ${
                        c.status === 'ACTIVE'
                          ? 'bg-yellow-50 text-yellow-700 hover:bg-yellow-100'
                          : 'bg-green-50 text-green-700 hover:bg-green-100'
                      } ${actionLoading === c.id ? 'opacity-50' : ''}`}
                    >
                      {actionLoading === c.id ? '...' : c.status === 'ACTIVE' ? 'Pause' : 'Enable'}
                    </button>
                    <span className="text-sm text-gray-500">{groups.length} asset groups</span>
                    <span className="text-gray-400">{isExpanded ? '\u25B2' : '\u25BC'}</span>
                  </div>
                </button>

                {isExpanded && groups.length > 0 && (
                  <div className="border-t border-gray-100 divide-y divide-gray-50">
                    {groups.map(g => (
                      <Link
                        key={g.id}
                        href={`/google/pmax/${c.id}?group=${g.id}`}
                        className="flex items-center justify-between px-5 py-3 pl-16 hover:bg-blue-50 transition-colors"
                      >
                        <div>
                          <p className="text-sm font-medium text-gray-700">{g.name}</p>
                          <p className="text-xs text-gray-400">{g.asset_count} assets</p>
                        </div>
                        <span className={`text-xs ${g.status === 'ACTIVE' ? 'text-green-600' : 'text-gray-400'}`}>
                          {g.status}
                        </span>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
