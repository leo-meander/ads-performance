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

export default function SearchCampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [healthMap, setHealthMap] = useState<Record<string, HealthInfo>>({})
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/google/campaigns?campaign_type=SEARCH&limit=100`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (data.success) setCampaigns(data.data.campaigns)
      })
      .finally(() => setLoading(false))

    // Health is graded by the overview endpoint; map it onto each row.
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

  const fmtCurrency = (n: number) => `$${n.toLocaleString('en-US', { maximumFractionDigits: 2 })}`

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
                    <td className="px-5 py-3 text-gray-600">{c.daily_budget ? fmtCurrency(c.daily_budget) : '-'}</td>
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
    </div>
  )
}
