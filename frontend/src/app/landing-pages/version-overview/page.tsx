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
  page_id: string
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
  engaged_sessions: number
  engagement_rate: number
  bounce_rate: number
  begin_checkout: number
  avg_session_duration_sec: number
  low_confidence: boolean
}

type VersionAgg = {
  sessions: number
  conversions: number
  conv_rate_pct: number | null
  avg_roas: number | null
  avg_scroll_pct: number | null
  atc_rate_pct: number | null
  engagement_rate: number | null
  bounce_rate: number | null
  begin_checkout_rate: number | null
  avg_session_duration_sec: number | null
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

const VERSION_COLORS = ['#2a78d6', '#1baf7a', '#e67e22', '#9b59b6', '#e74c3c', '#1abc9c']

function fmt(n: number | null | undefined, d = 0) {
  if (n === null || n === undefined) return '—'
  return n.toLocaleString('en-US', { maximumFractionDigits: d })
}
function fmtPct(n: number | null | undefined, decimals = 2) {
  if (n === null || n === undefined) return '—'
  return `${(Number(n) * (Math.abs(Number(n)) <= 1 ? 100 : 1)).toFixed(decimals)}%`
}
function fmtRawPct(n: number | null | undefined) {
  if (n === null || n === undefined) return '—'
  return `${Number(n).toFixed(2)}%`
}
function fmtROAS(n: number | null | undefined) {
  if (n === null || n === undefined) return '—'
  return `${Number(n).toFixed(2)}x`
}
function fmtDuration(sec: number | null | undefined) {
  if (!sec) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function StatCard({ label, value, delta }: { label: string; value: string; delta?: React.ReactNode }) {
  return (
    <div className="bg-gray-50 rounded-lg p-3">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <div className="flex items-center gap-1.5 flex-wrap">
        <p className="text-base font-medium text-gray-900">{value}</p>
        {delta}
      </div>
    </div>
  )
}

function DeltaBadge({ base, compare, unit = '%', decimals = 2, higherIsBetter = true }: {
  base: number | null; compare: number | null; unit?: string; decimals?: number; higherIsBetter?: boolean
}) {
  if (base === null || compare === null || base === 0) return null
  const d = compare - base
  const positive = higherIsBetter ? d >= 0 : d <= 0
  const cls = positive ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${cls}`}>
      {d >= 0 ? '+' : ''}{d.toFixed(decimals)}{unit}
    </span>
  )
}

function RelDelta({ base, compare, higherIsBetter = true }: {
  base: number | null; compare: number | null; higherIsBetter?: boolean
}) {
  if (!base || !compare) return null
  const pct = ((compare - base) / Math.abs(base)) * 100
  const positive = higherIsBetter ? pct >= 0 : pct <= 0
  const cls = positive ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'
  return (
    <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${cls}`}>
      {pct >= 0 ? '+' : ''}{pct.toFixed(0)}%
    </span>
  )
}

function VersionCard({ label, agg, color, baseAgg }: {
  label: string; agg: VersionAgg; color: string; baseAgg: VersionAgg | null
}) {
  const b = baseAgg
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4" style={{ borderTopWidth: 2, borderTopColor: color }}>
      <p className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color }}>{label}</p>

      {/* Row 1: traffic */}
      <div className="grid grid-cols-3 gap-2 mb-2">
        <StatCard label="Sessions" value={fmt(agg.sessions)}
          delta={b && <RelDelta base={b.sessions} compare={agg.sessions} />} />
        <StatCard label="Conversions" value={fmt(agg.conversions)}
          delta={b && <RelDelta base={b.conversions} compare={agg.conversions} />} />
        <StatCard
          label="Conv. rate"
          value={fmtRawPct(agg.conv_rate_pct)}
          delta={b && <DeltaBadge base={b.conv_rate_pct} compare={agg.conv_rate_pct} />}
        />
      </div>

      {/* Row 2: revenue + engagement */}
      <div className="grid grid-cols-3 gap-2 mb-2">
        <StatCard label="ROAS" value={fmtROAS(agg.avg_roas)}
          delta={b && <DeltaBadge base={b.avg_roas} compare={agg.avg_roas} unit="x" decimals={2} />} />
        <StatCard
          label="Engagement"
          value={fmtPct(agg.engagement_rate)}
          delta={b && <DeltaBadge base={b.engagement_rate ? b.engagement_rate * 100 : null} compare={agg.engagement_rate ? agg.engagement_rate * 100 : null} />}
        />
        <StatCard
          label="Bounce rate"
          value={fmtPct(agg.bounce_rate)}
          delta={b && <DeltaBadge base={b.bounce_rate ? b.bounce_rate * 100 : null} compare={agg.bounce_rate ? agg.bounce_rate * 100 : null} higherIsBetter={false} />}
        />
      </div>

      {/* Row 3: funnel */}
      <div className="grid grid-cols-2 gap-2 mb-3">
        <StatCard label="ATC rate" value={fmtRawPct(agg.atc_rate_pct)}
          delta={b && <DeltaBadge base={b.atc_rate_pct} compare={agg.atc_rate_pct} />} />
        <StatCard label="Avg scroll" value={agg.avg_scroll_pct !== null ? `${agg.avg_scroll_pct?.toFixed(1)}%` : '—'}
          delta={b && <DeltaBadge base={b.avg_scroll_pct} compare={agg.avg_scroll_pct} />} />
      </div>

      <p className="text-xs text-gray-400">{agg.page_count} pages · avg session {fmtDuration(agg.avg_session_duration_sec)}</p>
    </div>
  )
}

const VERSION_OPTIONS = ['Version 1', 'Version 2', 'Version 3', 'Version 4']

function VerBadge({ pageId, ver, versionColors, allVersions, onChanged }: {
  pageId: string
  ver: string
  versionColors: Record<string, string>
  allVersions: string[]
  onChanged: (pageId: string, newVer: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const color = versionColors[ver] ?? '#888'
  const options = Array.from(new Set([...allVersions, ...VERSION_OPTIONS]))

  async function pick(v: string) {
    setOpen(false)
    if (v === ver) return
    setSaving(true)
    try {
      await fetch(`${API_BASE}/api/landing-pages/${pageId}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ver: v }),
      })
      onChanged(pageId, v)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen(o => !o)}
        disabled={saving}
        className="text-xs font-medium px-1.5 py-0.5 rounded text-white cursor-pointer hover:opacity-80 transition-opacity disabled:opacity-50"
        style={{ backgroundColor: color }}
        title="Click to change version"
      >
        {ver.replace('Version ', 'V')}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-1 z-20 bg-white border border-gray-200 rounded shadow-lg py-1 min-w-[90px]">
            {options.map(v => (
              <button
                key={v}
                onClick={() => pick(v)}
                className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-50 flex items-center gap-2"
              >
                <span
                  className="inline-block w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: versionColors[v] ?? '#888' }}
                />
                {v.replace('Version ', 'V')}
                {v === ver && <span className="ml-auto text-gray-400">✓</span>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function PagesTable({ branch, selectedVersions, versionColors, allVersions, onVerChanged }: {
  branch: BranchData
  selectedVersions: string[]
  versionColors: Record<string, string>
  allVersions: string[]
  onVerChanged: (pageId: string, newVer: string) => void
}) {
  const rows = selectedVersions.flatMap(v =>
    (branch.versions[v]?.pages ?? []).map(p => ({ ...p, ver: v }))
  )
  if (!rows.length) return <p className="text-sm text-gray-400 px-4 py-4">No pages.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="text-left py-2 px-3 text-xs text-gray-400 font-normal">Ver.</th>
            <th className="text-left py-2 px-3 text-xs text-gray-400 font-normal">Slug</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">Sessions</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">Conv%</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">ROAS</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">Engage%</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">Bounce%</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">ATC%</th>
            <th className="text-right py-2 px-3 text-xs text-gray-400 font-normal">Scroll%</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p, i) => (
            <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
              <td className="py-2 px-3">
                <VerBadge
                  pageId={p.page_id}
                  ver={p.ver}
                  versionColors={versionColors}
                  allVersions={allVersions}
                  onChanged={onVerChanged}
                />
              </td>
              <td className="py-2 px-3 max-w-[180px] truncate text-gray-700" title={p.slug}>
                {p.slug || '(root)'}
                {p.low_confidence && <AlertTriangle className="inline w-3 h-3 text-amber-400 ml-1" />}
              </td>
              <td className="py-2 px-3 text-right text-gray-700">{fmt(p.sessions)}</td>
              <td className="py-2 px-3 text-right text-gray-700">{fmtRawPct(p.conv_rate_pct)}</td>
              <td className="py-2 px-3 text-right text-gray-700">{fmtROAS(p.roas)}</td>
              <td className="py-2 px-3 text-right text-gray-700">{fmtPct(p.engagement_rate)}</td>
              <td className="py-2 px-3 text-right text-gray-700">{fmtPct(p.bounce_rate)}</td>
              <td className="py-2 px-3 text-right text-gray-700">{fmtRawPct(p.atc_rate_pct)}</td>
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

function OverviewChart({ branches, selectedVersions, versionColors }: {
  branches: BranchData[]; selectedVersions: string[]; versionColors: Record<string, string>
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
          <YAxis tickFormatter={v => `${v}%`} tick={{ fontSize: 11, fill: '#aaa' }} axisLine={false} tickLine={false} width={42} />
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
          setSelectedVersions((res.data.version_labels ?? []).slice(0, 2))
        } else {
          setError(res.error)
        }
      })
      .catch(() => setError('Failed to load'))
      .finally(() => setLoading(false))
  }, [])

  function handleVerChanged(pageId: string, newVer: string) {
    setData(prev => {
      if (!prev) return prev
      const branches = prev.branches.map(b => {
        let movedPage: PageRow | undefined
        // remove page from whichever bucket currently holds it
        const versions: typeof b.versions = {}
        for (const [vLabel, agg] of Object.entries(b.versions)) {
          const found = agg.pages.find(p => p.page_id === pageId)
          if (found) movedPage = found
          const pages = agg.pages.filter(p => p.page_id !== pageId)
          versions[vLabel] = { ...agg, pages, page_count: pages.length }
        }
        // add page to target version bucket
        if (movedPage) {
          const existing = versions[newVer]
          if (existing) {
            versions[newVer] = { ...existing, pages: [...existing.pages, movedPage], page_count: existing.page_count + 1 }
          } else {
            // create a stub bucket (metrics will be stale until refresh, but UI shows it moved)
            versions[newVer] = { ...Object.values(b.versions)[0], pages: [movedPage], page_count: 1 }
          }
        }
        return { ...b, versions }
      })
      const allVersions = Array.from(new Set([...prev.version_labels, newVer])).sort()
      return { ...prev, branches, version_labels: allVersions }
    })
    setSelectedVersions(prev => prev.includes(newVer) ? prev : [...prev, newVer])
  }

  const versionColors: Record<string, string> = {}
  ;(data?.version_labels ?? []).forEach((v, i) => {
    versionColors[v] = VERSION_COLORS[i % VERSION_COLORS.length]
  })

  function toggleVersion(v: string) {
    setSelectedVersions(prev =>
      prev.includes(v)
        ? prev.length > 1 ? prev.filter(x => x !== v) : prev
        : [...prev, v]
    )
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
          {/* Version selector — only show when >2 versions exist */}
          {data.version_labels.length > 2 && (
            <div className="mb-4 flex items-center gap-2 flex-wrap">
              <span className="text-xs text-gray-500 mr-1">Compare:</span>
              {data.version_labels.map(v => {
                const active = selectedVersions.includes(v)
                return (
                  <button
                    key={v}
                    onClick={() => toggleVersion(v)}
                    className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                      active ? 'text-white border-transparent' : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50'
                    }`}
                    style={active ? { backgroundColor: versionColors[v] } : {}}
                  >
                    {v}
                  </button>
                )
              })}
            </div>
          )}

          <div className="mb-6">
            <OverviewChart branches={data.branches} selectedVersions={selectedVersions} versionColors={versionColors} />
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
            const base = baseVersion ? b.versions[baseVersion] ?? null : null
            return (
              <div className="space-y-4">
                <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${versionsToShow.length}, 1fr)` }}>
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
                      All pages — native ad currency. ⚠ = low session count (&lt;10). Engagement/Bounce from GA4.
                    </p>
                  </div>
                  <PagesTable
                    branch={b}
                    selectedVersions={versionsToShow}
                    versionColors={versionColors}
                    allVersions={data.version_labels}
                    onVerChanged={handleVerChanged}
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
