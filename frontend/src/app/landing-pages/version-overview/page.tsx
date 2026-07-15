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
  add_to_cart: number
  roas: number | null
  conv_rate_pct: number | null
  atc_rate_pct: number | null
  avg_scroll_pct: number
  rage_clicks: number
  quickback_clicks: number
  low_confidence: boolean
}

type VersionAgg = {
  sessions: number
  conversions: number
  conv_rate_pct: number | null
  avg_roas: number | null
  avg_scroll_pct: number | null
  atc_rate_pct: number | null
  page_count: number
  pages: PageRow[]
}

type BranchData = {
  domain: string
  branch: string
  versions: Record<string, VersionAgg>
}

type ApiResponse = {
  branches: BranchData[]
  version_labels: string[]
}

// Palette: up to 6 versions
const VERSION_COLORS = ['#2a78d6', '#1baf7a', '#e67e22', '#9b59b6', '#e74c3c', '#1abc9c']

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

function DeltaBadge({ a, b }: { a: number | null; b: number | null }) {
  if (a === null || b === null) return null
  const d = b - a
  const cls = d >= 0 ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded ${cls}`}>
      {d >= 0 ? '+' : ''}{d.toFixed(2)}pp
    </span>
  )
}

function VersionCard({
  label, agg, color, baseAgg,
}: { label: string; agg: VersionAgg; color: string; baseAgg: VersionAgg | null }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4" style={{ borderTopWidth: 2, borderTopColor: color }}>
      <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color }}>
        {label}
      </p>
      <div className="grid grid-cols-3 gap-2 mb-2">
        <StatCard label="Sessions" value={fmt(agg.sessions)} />
        <StatCard label="Conversions" value={fmt(agg.conversions)} />
        <div className="bg-gray-50 rounded-lg p-3">
          <p className="text-xs text-gray-500 mb-1">Conv. rate</p>
          <div className="flex items-center gap-1.5 flex-wrap">
            <p className="text-lg font-medium text-gray-900">{fmtCR(agg.conv_rate_pct)}</p>
            {baseAgg && <DeltaBadge a={baseAgg.conv_rate_pct} b={agg.conv_rate_pct} />}
          </div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 mb-3">
        <StatCard label="ROAS" value={fmtROAS(agg.avg_roas)} />
        <StatCard label="ATC rate" value={fmtCR(agg.atc_rate_pct)} />
        <StatCard label="Avg scroll" value={agg.avg_scroll_pct !== null ? `${agg.avg_scroll_pct?.toFixed(1)}%` : '—'} />
      </div>
      <p className="text-xs text-gray-400">{agg.page_count} pages tracked</p>
    </div>
  )
}

function PagesTable({ branch, selectedVersions, versionColors }: {
  branch: BranchData
  selectedVersions: string[]
  versionColors: Record<string, string>
}) {
  const rows = selectedVersions.flatMap(v =>
    (branch.versions[v]?.pages ?? []).map(p => ({ ...p, ver: v }))
  )
  if (rows.length === 0) return <p className="text-sm text-gray-400 px-4 py-4">No pages.</p>
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
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">ATC%</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">Scroll%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => {
            const color = versionColors[p.ver] ?? '#888'
            return (
              <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="py-2 px-3">
                  <span className="text-xs font-medium px-1.5 py-0.5 rounded text-white" style={{ backgroundColor: color }}>
                    {p.ver.replace('Version ', 'V')}
                  </span>
                </td>
                <td className="py-2 px-3 max-w-[200px] truncate text-gray-700" title={p.slug}>
                  {p.slug || '(root)'}
                  {p.low_confidence && <AlertTriangle className="inline w-3 h-3 text-amber-400 ml-1" />}
                </td>
                <td className="py-2 px-3 text-right text-gray-700">{fmt(p.sessions)}</td>
                <td className="py-2 px-3 text-right text-gray-700">{fmt(p.conversions)}</td>
                <td className="py-2 px-3 text-right text-gray-700">{fmtCR(p.conv_rate_pct)}</td>
                <td className="py-2 px-3 text-right text-gray-700">{fmtROAS(p.roas)}</td>
                <td className="py-2 px-3 text-right text-gray-700">{fmtCR(p.atc_rate_pct)}</td>
                <td className="py-2 px-3 text-right text-gray-700">
                  {p.avg_scroll_pct ? `${p.avg_scroll_pct.toFixed(1)}%` : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function OverviewChart({ branches, selectedVersions, versionColors }: {
  branches: BranchData[]
  selectedVersions: string[]
  versionColors: Record<string, string>
}) {
  const data = branches.map(b => {
    const row: Record<string, string | number> = { name: b.branch.replace('Meander ', '') }
    for (const v of selectedVersions) {
      const cr = b.versions[v]?.conv_rate_pct
      row[v] = cr !== null && cr !== undefined ? parseFloat(cr.toFixed(2)) : 0
    }
    return row
  })
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5">
      <p className="text-sm font-medium text-gray-700 mb-4">Conv. rate by branch (all-time)</p>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" vertical={false} />
          <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#888' }} axisLine={false} tickLine={false} />
          <YAxis
            tickFormatter={v => `${v}%`}
            tick={{ fontSize: 11, fill: '#aaa' }}
            axisLine={false} tickLine={false} width={42}
          />
          <Tooltip
            formatter={(val: number) => [`${val.toFixed(2)}%`, '']}
            contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
          />
          <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
          {selectedVersions.map(v => (
            <Bar key={v} dataKey={v} fill={versionColors[v]} radius={[3, 3, 0, 0]} maxBarSize={32} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function VersionOverviewPage() {
  const [data, setData] = useState<ApiResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState(0)
  const [selectedVersions, setSelectedVersions] = useState<string[]>([])

  useEffect(() => {
    fetch(`${API_BASE}/api/landing-pages/version-overview`, { credentials: 'include' })
      .then(r => r.json())
      .then(res => {
        if (res.success) {
          setData(res.data)
          // Default: select first 2 versions
          const labels: string[] = res.data.version_labels ?? []
          setSelectedVersions(labels.slice(0, 2))
        } else {
          setError(res.error)
        }
      })
      .catch(() => setError('Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  const versionColors: Record<string, string> = {}
  ;(data?.version_labels ?? []).forEach((v, i) => {
    versionColors[v] = VERSION_COLORS[i % VERSION_COLORS.length]
  })

  function toggleVersion(v: string) {
    setSelectedVersions(prev => {
      if (prev.includes(v)) {
        if (prev.length <= 1) return prev // keep at least 1
        return prev.filter(x => x !== v)
      }
      return [...prev, v]
    })
  }

  const baseVersion = selectedVersions[0] ?? null

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="flex items-center gap-3 mb-6">
        <Link href="/landing-pages" className="text-gray-400 hover:text-gray-600">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Landing Page Version Overview</h1>
          <p className="text-sm text-gray-500">Compare versions — all-time, by branch</p>
        </div>
      </div>

      {loading && <div className="text-sm text-gray-400 py-12 text-center">Loading…</div>}
      {error && <div className="text-sm text-red-500 py-4">{error}</div>}

      {!loading && !error && data && data.branches.length > 0 && (
        <>
          {/* Version selector */}
          {data.version_labels.length > 2 && (
            <div className="mb-4 flex items-center gap-2 flex-wrap">
              <span className="text-xs text-gray-500">Compare:</span>
              {data.version_labels.map(v => {
                const active = selectedVersions.includes(v)
                return (
                  <button
                    key={v}
                    onClick={() => toggleVersion(v)}
                    className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                      active ? 'text-white border-transparent' : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50'
                    }`}
                    style={active ? { backgroundColor: versionColors[v], borderColor: versionColors[v] } : {}}
                  >
                    {v}
                  </button>
                )
              })}
            </div>
          )}

          <div className="mb-6">
            <OverviewChart
              branches={data.branches}
              selectedVersions={selectedVersions}
              versionColors={versionColors}
            />
          </div>

          {/* Branch tabs */}
          <div className="flex gap-2 flex-wrap mb-4">
            {data.branches.map((b, i) => (
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

          {data.branches[activeTab] && (() => {
            const b = data.branches[activeTab]
            const versionsToShow = selectedVersions.filter(v => b.versions[v])
            const base = b.versions[baseVersion ?? ''] ?? null
            return (
              <div className="space-y-4">
                <div className={`grid gap-4`} style={{ gridTemplateColumns: `repeat(${versionsToShow.length}, 1fr)` }}>
                  {versionsToShow.map((v, idx) => (
                    <VersionCard
                      key={v}
                      label={v}
                      agg={b.versions[v]}
                      color={versionColors[v]}
                      baseAgg={idx === 0 ? null : base}
                    />
                  ))}
                </div>

                <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-100">
                    <p className="text-xs text-gray-400">
                      All pages — native ad currency (mixed). ⚠ = low session count (&lt;10).
                    </p>
                  </div>
                  <PagesTable
                    branch={b}
                    selectedVersions={versionsToShow}
                    versionColors={versionColors}
                  />
                </div>
              </div>
            )
          })()}
        </>
      )}
    </div>
  )
}
