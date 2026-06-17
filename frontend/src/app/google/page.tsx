'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import RecommendationsSummary from '@/components/RecommendationsSummary'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type Health = 'action' | 'watch' | 'ok' | 'learning'

interface CampaignRow {
  id: string
  name: string
  account_id: string
  branch: string
  currency: string
  campaign_type: string
  campaign_status: string
  ta: string | null
  funnel_stage: string | null
  daily_budget: number | null
  spend: number
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  roas: number
  cpa: number | null
  ctr: number
  health: Health
  budget_limited: boolean
  hint: string
}

interface BranchRow {
  account_id: string
  branch: string
  currency: string
  spend: number
  impressions: number
  clicks: number
  conversions: number
  revenue: number
  roas: number
  cpa: number | null
  ctr: number
  active_campaigns: number
  needs_action: number
}

interface Overview {
  period: { date_from: string; date_to: string; days: number }
  roas_target: number
  summary: { action: number; watch: number; ok: number; learning: number; total: number }
  branches: BranchRow[]
  campaigns: CampaignRow[]
}

const HEALTH_META: Record<Health, { label: string; dot: string; chip: string; row: string }> = {
  action: { label: 'Action needed', dot: 'bg-red-500', chip: 'bg-red-50 text-red-700 border-red-200', row: 'border-l-red-400' },
  watch: { label: 'Watch', dot: 'bg-amber-500', chip: 'bg-amber-50 text-amber-700 border-amber-200', row: 'border-l-amber-400' },
  ok: { label: 'OK', dot: 'bg-green-500', chip: 'bg-green-50 text-green-700 border-green-200', row: 'border-l-green-400' },
  learning: { label: 'Learning', dot: 'bg-gray-400', chip: 'bg-gray-100 text-gray-500 border-gray-200', row: 'border-l-gray-300' },
}

const PERIODS = [7, 14, 30, 90]

const fmtMoney = (n: number, currency: string) =>
  `${currency} ${n.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
const fmtNum = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 0 })

function detailHref(c: CampaignRow) {
  return c.campaign_type === 'PERFORMANCE_MAX'
    ? `/google/pmax/${c.id}`
    : `/google/search/${c.id}`
}

function roasColor(roas: number, target: number, health: Health) {
  if (health === 'learning') return 'text-gray-400'
  if (roas >= target) return 'text-green-600'
  if (roas >= target * 0.6) return 'text-amber-600'
  return 'text-red-600'
}

export default function GoogleOverviewPage() {
  const [data, setData] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [days, setDays] = useState(30)
  const [roasTarget, setRoasTarget] = useState(6)
  const [typeFilter, setTypeFilter] = useState<'ALL' | 'PERFORMANCE_MAX' | 'SEARCH'>('ALL')
  const [statusFilter, setStatusFilter] = useState<Health | null>(null)

  // Restore the saved ROAS target once on mount.
  useEffect(() => {
    const saved = Number(localStorage.getItem('google_roas_target'))
    if (saved && saved > 0) setRoasTarget(saved)
  }, [])

  const fetchData = useCallback((d: number, target: number) => {
    setLoading(true)
    setError(null)
    fetch(`${API_BASE}/api/google/overview?days=${d}&roas_target=${target}`, { credentials: 'include' })
      .then(r => r.json())
      .then(res => {
        if (res.success) setData(res.data)
        else setError(res.error || 'Failed to load overview')
      })
      .catch(() => setError('Network error'))
      .finally(() => setLoading(false))
  }, [])

  // Debounce so typing in the ROAS box doesn't spam the API.
  useEffect(() => {
    const t = setTimeout(() => fetchData(days, roasTarget), 350)
    return () => clearTimeout(t)
  }, [days, roasTarget, fetchData])

  const onRoasChange = (v: number) => {
    setRoasTarget(v)
    if (v > 0) localStorage.setItem('google_roas_target', String(v))
  }

  const summary = data?.summary
  const target = data?.roas_target ?? roasTarget

  const filtered = useMemo(() => {
    if (!data) return []
    return data.campaigns.filter(c => {
      if (typeFilter !== 'ALL' && c.campaign_type !== typeFilter) return false
      if (statusFilter && c.health !== statusFilter) return false
      return true
    })
  }, [data, typeFilter, statusFilter])

  return (
    <div className="p-8 space-y-6">
      {/* Header + controls */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Google Ads Overview</h1>
          <p className="text-sm text-gray-500">
            {data
              ? `${data.period.date_from} → ${data.period.date_to} · triage across all branches`
              : 'Portfolio health at a glance'}
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
            {PERIODS.map(p => (
              <button
                key={p}
                onClick={() => setDays(p)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  days === p ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {p}d
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-xs text-gray-500">
            ROAS target
            <input
              type="number"
              min={0.1}
              step={0.5}
              value={roasTarget}
              onChange={e => onRoasChange(Number(e.target.value))}
              className="w-16 px-2 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-200"
            />
            <span className="text-gray-400">x</span>
          </label>
        </div>
      </div>

      {/* Triage band */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {(['action', 'watch', 'ok', 'learning'] as Health[]).map(h => {
          const meta = HEALTH_META[h]
          const count = summary ? summary[h] : 0
          const active = statusFilter === h
          return (
            <button
              key={h}
              onClick={() => setStatusFilter(active ? null : h)}
              className={`text-left bg-white rounded-xl border p-4 transition-all ${
                active ? 'border-gray-900 ring-1 ring-gray-900' : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="flex items-center gap-2">
                <span className={`w-2.5 h-2.5 rounded-full ${meta.dot}`} />
                <span className="text-xs font-medium text-gray-500">{meta.label}</span>
              </div>
              <p className="text-3xl font-bold text-gray-900 mt-2">{count}</p>
              <p className="text-[11px] text-gray-400 mt-0.5">
                {h === 'action' ? 'Fix these first' : h === 'watch' ? 'Near target' : h === 'ok' ? 'Healthy' : 'Too little data'}
              </p>
            </button>
          )
        })}
      </div>

      <RecommendationsSummary />

      {/* Per-branch KPI cards (currency-safe: never summed across branches) */}
      {data && data.branches.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Branches</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {data.branches.map(b => (
              <div key={b.account_id} className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="flex items-center justify-between">
                  <p className="font-semibold text-gray-900 truncate">{b.branch}</p>
                  {b.needs_action > 0 && (
                    <span className="text-[11px] font-medium bg-red-50 text-red-700 px-2 py-0.5 rounded-full">
                      {b.needs_action} to fix
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-3 gap-2 mt-3">
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-gray-400">Spend</p>
                    <p className="text-sm font-semibold text-gray-900">{fmtMoney(b.spend, b.currency)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-gray-400">Revenue</p>
                    <p className="text-sm font-semibold text-gray-900">{fmtMoney(b.revenue, b.currency)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-gray-400">ROAS</p>
                    <p className={`text-sm font-bold ${b.roas >= target ? 'text-green-600' : b.roas >= target * 0.6 ? 'text-amber-600' : 'text-red-600'}`}>
                      {b.roas.toFixed(2)}x
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-gray-400">Conv.</p>
                    <p className="text-sm font-semibold text-gray-900">{fmtNum(b.conversions)}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-gray-400">CPA</p>
                    <p className="text-sm font-semibold text-gray-900">{b.cpa != null ? fmtMoney(b.cpa, b.currency) : '—'}</p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-wide text-gray-400">Active</p>
                    <p className="text-sm font-semibold text-gray-900">{b.active_campaigns}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Campaign health table */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-700">
            Campaigns
            {statusFilter && (
              <button onClick={() => setStatusFilter(null)} className="ml-2 text-xs font-normal text-blue-600 hover:underline">
                clear filter ({HEALTH_META[statusFilter].label})
              </button>
            )}
          </h2>
          <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
            {(['ALL', 'PERFORMANCE_MAX', 'SEARCH'] as const).map(t => (
              <button
                key={t}
                onClick={() => setTypeFilter(t)}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
                  typeFilter === t ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {t === 'ALL' ? 'All' : t === 'PERFORMANCE_MAX' ? 'PMax' : 'Search'}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Status</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Campaign</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">Branch</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">Spend</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">Conv.</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">ROAS</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">CPA</th>
                <th className="text-right px-4 py-3 text-gray-500 font-medium">CTR</th>
                <th className="text-left px-4 py-3 text-gray-500 font-medium">What to optimize</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr><td colSpan={9} className="px-5 py-10 text-center text-gray-400">Loading…</td></tr>
              ) : error ? (
                <tr><td colSpan={9} className="px-5 py-10 text-center text-red-500">{error}</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={9} className="px-5 py-10 text-center text-gray-400">No campaigns match this filter.</td></tr>
              ) : (
                filtered.map(c => {
                  const meta = HEALTH_META[c.health]
                  return (
                    <tr key={c.id} className={`hover:bg-gray-50 border-l-4 ${meta.row}`}>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-1 rounded-full border ${meta.chip}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${meta.dot}`} />
                          {meta.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 max-w-[260px]">
                        <Link href={detailHref(c)} className="text-blue-600 hover:underline font-medium block truncate">
                          {c.name}
                        </Link>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">
                            {c.campaign_type === 'PERFORMANCE_MAX' ? 'PMax' : 'Search'}
                          </span>
                          {c.ta && <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{c.ta}</span>}
                          {c.campaign_status !== 'ACTIVE' && (
                            <span className="text-[10px] text-gray-400">{c.campaign_status}</span>
                          )}
                          {c.budget_limited && (
                            <span className="text-[10px] bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded">budget capped</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-gray-600 truncate max-w-[140px]">{c.branch}</td>
                      <td className="px-4 py-3 text-right text-gray-700">{fmtMoney(c.spend, c.currency)}</td>
                      <td className="px-4 py-3 text-right text-gray-700">{fmtNum(c.conversions)}</td>
                      <td className={`px-4 py-3 text-right font-bold ${roasColor(c.roas, target, c.health)}`}>
                        {c.health === 'learning' && c.conversions === 0 ? '—' : `${c.roas.toFixed(2)}x`}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-700">{c.cpa != null ? fmtMoney(c.cpa, c.currency) : '—'}</td>
                      <td className="px-4 py-3 text-right text-gray-700">{c.ctr.toFixed(2)}%</td>
                      <td className="px-4 py-3 text-gray-500 text-xs max-w-[320px]">{c.hint}</td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-xs text-gray-400">
        Health is graded on ROAS vs your {target}x target, conversion volume, and budget pacing.
        ROAS is currency-safe; branch totals are never summed across currencies.
      </p>
    </div>
  )
}
