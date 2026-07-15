'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  Legend, ResponsiveContainer,
} from 'recharts'
import { ArrowLeft, AlertTriangle } from 'lucide-react'
import { API_BASE } from '@/lib/api'

type PageRow = {
  slug: string
  spend: number
  revenue: number
  conversions: number
  sessions: number
  roas: number | null
  conv_rate_pct: number | null
  avg_scroll_pct: number
  rage_clicks: number
  quickback_clicks: number
  low_confidence: boolean
}

type VersionAgg = {
  sessions: number
  conversions: number
  conv_rate_pct: number | null
  page_count: number
  pages: PageRow[]
}

type BranchData = {
  domain: string
  branch: string
  v1: VersionAgg
  v2: VersionAgg
}

function fmt(n: number | null | undefined, d = 0) {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString('en-US', { maximumFractionDigits: d })
}
function fmtCR(n: number | null | undefined) {
  if (n === null || n === undefined) return '—'
  return `${Number(n).toFixed(2)}%`
}
function fmtROAS(n: number | null | undefined) {
  if (n === null || n === undefined) return '—'
  return `${Number(n).toFixed(2)}x`
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className="text-lg font-medium text-gray-900">{value}</p>
    </div>
  )
}

function VersionCard({
  version, agg, color,
}: { version: string; agg: VersionAgg; color: 'blue' | 'emerald' }) {
  const borderColor = color === 'blue' ? 'border-blue-500' : 'border-emerald-500'
  const labelColor = color === 'blue' ? 'text-blue-600' : 'text-emerald-600'
  return (
    <div className={`bg-white border border-gray-200 border-t-2 ${borderColor} rounded-xl p-4`}>
      <p className={`text-xs font-semibold uppercase tracking-wider mb-3 ${labelColor}`}>
        {version}
      </p>
      <div className="grid grid-cols-3 gap-2 mb-3">
        <StatCard label="Sessions" value={fmt(agg.sessions)} />
        <StatCard label="Conversions" value={fmt(agg.conversions)} />
        <StatCard label="Conv. rate" value={fmtCR(agg.conv_rate_pct)} />
      </div>
      <p className="text-xs text-gray-400">{agg.page_count} pages tracked</p>
    </div>
  )
}

function DeltaBadge({ v1cr, v2cr }: { v1cr: number | null; v2cr: number | null }) {
  if (v1cr === null || v2cr === null) return null
  const d = v2cr - v1cr
  const cls = d >= 0
    ? 'bg-emerald-100 text-emerald-700'
    : 'bg-red-100 text-red-700'
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded ${cls}`}>
      {d >= 0 ? '+' : ''}{d.toFixed(2)}pp
    </span>
  )
}

function PagesTable({ v1, v2 }: { v1: VersionAgg; v2: VersionAgg }) {
  const rows = [
    ...v2.pages.map(p => ({ ...p, ver: 'v2' })),
    ...v1.pages.map(p => ({ ...p, ver: 'v1' })),
  ]
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="text-left py-2 px-3 text-xs text-gray-400 font-normal">Ver.</th>
            <th className="text-left py-2 px-3 text-xs text-gray-400 font-normal">Slug</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">Sessions</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">Conv.</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">Conv. rate</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">ROAS</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">Scroll%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => (
            <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="py-2 px-3">
                <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                  p.ver === 'v2'
                    ? 'bg-emerald-100 text-emerald-700'
                    : 'bg-blue-100 text-blue-700'
                }`}>
                  {p.ver === 'v2' ? 'V2' : 'V1'}
                </span>
              </td>
              <td className="py-2 px-3 max-w-[200px] truncate text-gray-700" title={p.slug}>
                {p.slug || '(root)'}
                {p.low_confidence && (
                  <AlertTriangle className="inline w-3 h-3 text-amber-400 ml-1" />
                )}
              </td>
              <td className="py-2 px-3 text-right text-gray-700">{fmt(p.sessions)}</td>
              <td className="py-2 px-3 text-right text-gray-700">{fmt(p.conversions)}</td>
              <td className="py-2 px-3 text-right text-gray-700">{fmtCR(p.conv_rate_pct)}</td>
              <td className="py-2 px-3 text-right text-gray-700">{fmtROAS(p.roas)}</td>
              <td className="py-2 px-3 text-right text-gray-700">
                {p.avg_scroll_pct ? `${p.avg_scroll_pct.toFixed(1)}%` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function OverviewChart({ branches }: { branches: BranchData[] }) {
  const data = branches.map(b => ({
    name: b.branch.replace('Meander ', ''),
    'Version 1': b.v1.conv_rate_pct !== null ? parseFloat(b.v1.conv_rate_pct.toFixed(2)) : 0,
    'Version 2': b.v2.conv_rate_pct !== null ? parseFloat(b.v2.conv_rate_pct.toFixed(2)) : 0,
  }))
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5">
      <p className="text-sm font-medium text-gray-700 mb-4">Conv. rate by branch — V1 vs V2 (all-time)</p>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
          <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#888' }} axisLine={false} tickLine={false} />
          <YAxis
            tickFormatter={v => `${v}%`}
            tick={{ fontSize: 11, fill: '#aaa' }}
            axisLine={false}
            tickLine={false}
            width={42}
          />
          <Tooltip
            formatter={(val: number) => [`${val.toFixed(2)}%`, '']}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
          />
          <Legend
            iconType="square"
            iconSize={10}
            wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
          />
          <Bar dataKey="Version 1" fill="#2a78d6" radius={[3, 3, 0, 0]} maxBarSize={32} />
          <Bar dataKey="Version 2" fill="#1baf7a" radius={[3, 3, 0, 0]} maxBarSize={32} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function VersionOverviewPage() {
  const [branches, setBranches] = useState<BranchData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState(0)

  useEffect(() => {
    fetch(`${API_BASE}/api/landing-pages/version-overview`, { credentials: 'include' })
      .then(r => r.json())
      .then(res => {
        if (res.success) setBranches(res.data)
        else setError(res.error)
      })
      .catch(() => setError('Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Link href="/landing-pages" className="text-gray-400 hover:text-gray-600">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Landing Page Version Overview</h1>
          <p className="text-sm text-gray-500">Version 1 vs Version 2 — all-time, by branch</p>
        </div>
      </div>

      {loading && (
        <div className="text-sm text-gray-400 py-12 text-center">Loading…</div>
      )}
      {error && (
        <div className="text-sm text-red-500 py-4">{error}</div>
      )}

      {!loading && !error && branches.length > 0 && (
        <>
          <div className="mb-6">
            <OverviewChart branches={branches} />
          </div>

          {/* Branch tabs */}
          <div className="flex gap-2 flex-wrap mb-4">
            {branches.map((b, i) => (
              <button
                key={b.domain}
                onClick={() => setActiveTab(i)}
                className={`px-4 py-1.5 rounded-lg text-sm border transition-colors ${
                  i === activeTab
                    ? 'bg-blue-50 border-blue-200 text-blue-700 font-medium'
                    : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {b.branch}
              </button>
            ))}
          </div>

          {branches[activeTab] && (() => {
            const b = branches[activeTab]
            return (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <VersionCard version="Version 1" agg={b.v1} color="blue" />
                  <div className="relative">
                    <VersionCard version="Version 2" agg={b.v2} color="emerald" />
                    <div className="absolute top-4 right-4">
                      <DeltaBadge v1cr={b.v1.conv_rate_pct} v2cr={b.v2.conv_rate_pct} />
                    </div>
                  </div>
                </div>

                <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-100">
                    <p className="text-xs text-gray-400">
                      All pages — native ad currency (mixed). ⚠ = low session count (&lt;10).
                    </p>
                  </div>
                  <PagesTable v1={b.v1} v2={b.v2} />
                </div>
              </div>
            )
          })()}
        </>
      )}
    </div>
  )
}
