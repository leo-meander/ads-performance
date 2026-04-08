'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { ArrowLeft } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface CampaignDetail {
  id: string
  account_name: string | null
  currency: string
  platform: string
  platform_campaign_id: string
  name: string
  status: string
  objective: string | null
  daily_budget: number | null
  lifetime_budget: number | null
  start_date: string | null
  end_date: string | null
}

interface MetricRow {
  date: string
  spend: number
  impressions: number
  clicks: number
  ctr: number
  conversions: number
  revenue: number
  roas: number
  cpa: number | null
  cpc: number | null
}

const STATUS_COLORS: Record<string, string> = {
  ACTIVE: 'bg-green-100 text-green-700',
  PAUSED: 'bg-yellow-100 text-yellow-700',
  ARCHIVED: 'bg-gray-100 text-gray-500',
}

const CURRENCY_SYMBOLS: Record<string, string> = {
  VND: '₫',
  TWD: 'NT$',
  JPY: '¥',
  USD: '$',
}

function fmtMoney(n: number, currency: string): string {
  const symbol = CURRENCY_SYMBOLS[currency] || currency
  const formatted = new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(n)
  return `${formatted} ${symbol}`
}

function formatNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toFixed(n % 1 === 0 ? 0 : 2)
}

export default function CampaignDetailPage() {
  const params = useParams()
  const campaignId = params.id as string

  const [campaign, setCampaign] = useState<CampaignDetail | null>(null)
  const [metrics, setMetrics] = useState<MetricRow[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/campaigns/${campaignId}`).then(r => r.json()),
      fetch(`${API_BASE}/api/campaigns/${campaignId}/metrics`).then(r => r.json()),
    ])
      .then(([campRes, metricsRes]) => {
        if (campRes.success) setCampaign(campRes.data)
        if (metricsRes.success) setMetrics(metricsRes.data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [campaignId])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading campaign...</div>
      </div>
    )
  }

  if (!campaign) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-500">Campaign not found.</p>
        <Link href="/campaigns" className="text-blue-600 hover:underline text-sm mt-2 inline-block">
          Back to campaigns
        </Link>
      </div>
    )
  }

  // Compute summary from metrics
  const totalSpend = metrics.reduce((s, r) => s + r.spend, 0)
  const totalRevenue = metrics.reduce((s, r) => s + r.revenue, 0)
  const totalClicks = metrics.reduce((s, r) => s + r.clicks, 0)
  const totalImpressions = metrics.reduce((s, r) => s + r.impressions, 0)
  const totalConversions = metrics.reduce((s, r) => s + r.conversions, 0)
  const avgRoas = totalSpend > 0 ? totalRevenue / totalSpend : 0
  const avgCtr = totalImpressions > 0 ? totalClicks / totalImpressions : 0

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <Link
          href="/campaigns"
          className="inline-flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 mb-3"
        >
          <ArrowLeft className="w-4 h-4" /> Back to campaigns
        </Link>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{campaign.name}</h1>
            <p className="text-sm text-gray-500 mt-1">
              {campaign.account_name} &middot; {campaign.platform_campaign_id}
            </p>
          </div>
          <span className={`text-xs px-3 py-1.5 rounded-full font-medium ${STATUS_COLORS[campaign.status] || 'bg-gray-100 text-gray-500'}`}>
            {campaign.status}
          </span>
        </div>
      </div>

      {/* Campaign Info */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs text-gray-500">Objective</p>
          <p className="text-sm font-medium text-gray-900 mt-1">{campaign.objective || '--'}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs text-gray-500">Daily Budget</p>
          <p className="text-sm font-medium text-gray-900 mt-1">
            {campaign.daily_budget ? fmtMoney(campaign.daily_budget, campaign.currency) : '--'}
          </p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs text-gray-500">Start Date</p>
          <p className="text-sm font-medium text-gray-900 mt-1">{campaign.start_date || '--'}</p>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4">
          <p className="text-xs text-gray-500">End Date</p>
          <p className="text-sm font-medium text-gray-900 mt-1">{campaign.end_date || '--'}</p>
        </div>
      </div>

      {/* KPI Summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4 mb-6">
        {[
          { label: 'Spend', value: fmtMoney(totalSpend, campaign.currency) },
          { label: 'Revenue', value: fmtMoney(totalRevenue, campaign.currency) },
          { label: 'ROAS', value: `${avgRoas.toFixed(2)}x` },
          { label: 'Clicks', value: formatNum(totalClicks) },
          { label: 'CTR', value: `${(avgCtr * 100).toFixed(2)}%` },
          { label: 'Conversions', value: String(totalConversions) },
          { label: 'Impressions', value: formatNum(totalImpressions) },
        ].map((kpi) => (
          <div key={kpi.label} className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-xs text-gray-500">{kpi.label}</p>
            <p className="text-lg font-bold text-gray-900 mt-1">{kpi.value}</p>
          </div>
        ))}
      </div>

      {metrics.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
          No metrics data available for this campaign.
        </div>
      ) : (
        <>
          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Spend & Revenue */}
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">Spend vs Revenue ({campaign.currency})</h2>
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={metrics}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => formatNum(v)} />
                  <Tooltip formatter={(v: number) => fmtMoney(v, campaign.currency)} />
                  <Legend />
                  <Area type="monotone" dataKey="spend" name="Spend" stroke="#ef4444" fill="#fef2f2" strokeWidth={2} />
                  <Area type="monotone" dataKey="revenue" name="Revenue" stroke="#10b981" fill="#ecfdf5" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* ROAS */}
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">ROAS</h2>
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={metrics}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v.toFixed(1)}x`} />
                  <Tooltip formatter={(v: number) => `${v.toFixed(2)}x`} />
                  <Area type="monotone" dataKey="roas" name="ROAS" stroke="#3b82f6" fill="#eff6ff" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Clicks & Conversions */}
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">Clicks & Conversions</h2>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={metrics}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="clicks" name="Clicks" fill="#8b5cf6" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="conversions" name="Conversions" fill="#f59e0b" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* CTR */}
            <div className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">CTR (%)</h2>
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={metrics.map(r => ({ ...r, ctr_pct: r.ctr * 100 }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `${v.toFixed(1)}%`} />
                  <Tooltip formatter={(v: number) => `${v.toFixed(2)}%`} />
                  <Area type="monotone" dataKey="ctr_pct" name="CTR" stroke="#ec4899" fill="#fdf2f8" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Metrics Table */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Daily Metrics</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-left py-2 px-2 text-gray-500 font-medium">Date</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium">Spend</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium">Revenue</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium">ROAS</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium">Impressions</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium">Clicks</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium">CTR</th>
                    <th className="text-right py-2 px-2 text-gray-500 font-medium">Conversions</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics.map((r) => (
                    <tr key={r.date} className="border-b border-gray-50 hover:bg-gray-50">
                      <td className="py-2 px-2 text-gray-900">{r.date}</td>
                      <td className="py-2 px-2 text-right text-gray-700">{fmtMoney(r.spend, campaign.currency)}</td>
                      <td className="py-2 px-2 text-right text-gray-700">{fmtMoney(r.revenue, campaign.currency)}</td>
                      <td className="py-2 px-2 text-right">
                        <span className={r.roas >= 1 ? 'text-green-600' : 'text-red-600'}>
                          {r.roas.toFixed(2)}x
                        </span>
                      </td>
                      <td className="py-2 px-2 text-right text-gray-700">{formatNum(r.impressions)}</td>
                      <td className="py-2 px-2 text-right text-gray-700">{r.clicks}</td>
                      <td className="py-2 px-2 text-right text-gray-700">{(r.ctr * 100).toFixed(2)}%</td>
                      <td className="py-2 px-2 text-right text-gray-700">{r.conversions}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
