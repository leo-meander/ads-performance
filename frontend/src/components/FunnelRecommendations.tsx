'use client'

import Link from 'next/link'
import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Globe,
  Layers,
  RefreshCw,
  Sparkles,
  Target,
  TrendingDown,
  Users,
} from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface FunnelStageSnap {
  key: string
  label: string
  value: number
  is_bottleneck_in?: boolean
  is_bottleneck_out?: boolean
}

interface Contributor {
  kind: 'ad' | 'landing_page' | 'campaign'
  id: string
  name: string
  url?: string
  account_name?: string
  platform?: string
  impressions?: number
  clicks?: number
  ctr?: number
  spend?: number
  in?: number
  out?: number
  rate?: number
}

interface Recommendation {
  rec_id: string
  severity: 'critical' | 'warning' | 'info'
  score: number
  breakdown_dim: 'overall' | 'channel' | 'country' | 'funnel' | 'ta'
  dimension_label: string
  dimension_value: {
    platform?: string | null
    country?: string | null
    funnel_stage?: string | null
    ta?: string | null
    key?: string
  }
  from_stage: string
  to_stage: string
  transition_name: string
  root_cause: string
  hint: string
  metric_label: string
  current_volume_in: number
  current_volume_out: number
  current_conversion_rate: number | null
  prev_conversion_rate: number | null
  conversion_rate_change: number | null
  current_drop_off: number | null
  prev_drop_off: number | null
  drop_off_change: number | null
  funnel_snapshot: FunnelStageSnap[]
  deep_link_target: 'creative' | 'landing_page' | 'country'
  deep_link_url: string
  top_contributors: Contributor[]
}

interface RecPayload {
  period: { from: string; to: string }
  prev_period: { from: string; to: string }
  overall_funnel: FunnelStageSnap[]
  recommendations: Recommendation[]
  summary: {
    total: number
    by_severity: Record<string, number>
    by_transition: Record<string, number>
    worst_transition: string | null
    worst_dimension: string | null
  }
}

interface Props {
  branches: string  // comma-separated
  platform: string
  dateFrom: string
  dateTo: string
}

const DIM_ICONS: Record<string, JSX.Element> = {
  overall: <Sparkles className="w-3.5 h-3.5" />,
  channel: <Layers className="w-3.5 h-3.5" />,
  country: <Globe className="w-3.5 h-3.5" />,
  funnel: <Target className="w-3.5 h-3.5" />,
  ta: <Users className="w-3.5 h-3.5" />,
}

const DIM_LABELS: Record<string, string> = {
  overall: 'Overall',
  channel: 'Channel',
  country: 'Country',
  funnel: 'Funnel',
  ta: 'Target Audience',
}

const SEVERITY_STYLES: Record<string, { card: string; badge: string; label: string }> = {
  critical: {
    card: 'border-red-200 bg-red-50/30',
    badge: 'bg-red-600 text-white',
    label: 'Critical',
  },
  warning: {
    card: 'border-amber-200 bg-amber-50/30',
    badge: 'bg-amber-500 text-white',
    label: 'Warning',
  },
  info: {
    card: 'border-blue-200 bg-blue-50/30',
    badge: 'bg-blue-500 text-white',
    label: 'Info',
  },
}

function pctText(v: number | null | undefined, signed = false): string {
  if (v === null || v === undefined) return '--'
  const pct = v * 100
  const formatted = pct.toFixed(1) + '%'
  if (!signed) return formatted
  if (pct > 0) return `+${formatted}`
  return formatted
}

function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(n)
}

export default function FunnelRecommendations({ branches, platform, dateFrom, dateTo }: Props) {
  const [payload, setPayload] = useState<RecPayload | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeDim, setActiveDim] = useState<string>('all')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [refreshTick, setRefreshTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo })
    if (platform) params.set('platform', platform)
    if (branches) params.set('branches', branches)
    fetch(`${API_BASE}/api/dashboard/funnel-recommendations?${params}`, {
      credentials: 'include',
    })
      .then((r) => r.json())
      .then((res) => {
        if (cancelled) return
        if (res.success) setPayload(res.data)
        else setError(res.error || 'Failed to load')
      })
      .catch((e) => {
        if (cancelled) return
        setError(String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [branches, platform, dateFrom, dateTo, refreshTick])

  const filtered = useMemo(() => {
    if (!payload) return []
    if (activeDim === 'all') return payload.recommendations
    return payload.recommendations.filter((r) => r.breakdown_dim === activeDim)
  }, [payload, activeDim])

  const dimCounts = useMemo(() => {
    const m: Record<string, number> = { all: 0, overall: 0, channel: 0, country: 0, funnel: 0, ta: 0 }
    if (!payload) return m
    for (const r of payload.recommendations) {
      m.all += 1
      m[r.breakdown_dim] = (m[r.breakdown_dim] || 0) + 1
    }
    return m
  }, [payload])

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
      <div className="flex items-start justify-between mb-1">
        <div>
          <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-indigo-500" />
            Funnel Recommendations
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Last 7 days bottlenecks by Channel × Country × Funnel × TA. Click a card to drill into the root-cause page.
          </p>
        </div>
        <button
          onClick={() => setRefreshTick((t) => t + 1)}
          className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
          title="Refresh"
          disabled={loading}
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Summary strip */}
      {payload && (
        <div className="flex flex-wrap items-center gap-2 mt-3 mb-4">
          <span className="text-xs text-gray-500">
            {payload.period.from} → {payload.period.to} vs {payload.prev_period.from} → {payload.prev_period.to}
          </span>
          {payload.summary.total > 0 ? (
            <>
              <span className="px-2 py-0.5 rounded-md bg-red-100 text-red-700 text-xs font-medium">
                {payload.summary.by_severity.critical || 0} critical
              </span>
              <span className="px-2 py-0.5 rounded-md bg-amber-100 text-amber-800 text-xs font-medium">
                {payload.summary.by_severity.warning || 0} warning
              </span>
              <span className="px-2 py-0.5 rounded-md bg-blue-100 text-blue-700 text-xs font-medium">
                {payload.summary.by_severity.info || 0} info
              </span>
              {payload.summary.worst_transition && (
                <span className="text-xs text-gray-500 ml-2">
                  Worst leak: <span className="font-semibold text-gray-700">{payload.summary.worst_transition}</span>
                  {payload.summary.worst_dimension && (
                    <> @ <span className="font-semibold text-gray-700">{payload.summary.worst_dimension}</span></>
                  )}
                </span>
              )}
            </>
          ) : (
            <span className="text-xs text-emerald-600 font-medium">All funnel transitions look healthy.</span>
          )}
        </div>
      )}

      {/* Dim tabs */}
      <div className="flex flex-wrap items-center gap-1 mb-4 border-b border-gray-100 pb-2">
        {(['all', 'overall', 'channel', 'country', 'funnel', 'ta'] as const).map((dim) => (
          <button
            key={dim}
            onClick={() => setActiveDim(dim)}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              activeDim === dim
                ? 'bg-indigo-100 text-indigo-700'
                : 'text-gray-500 hover:bg-gray-50'
            }`}
          >
            {dim !== 'all' && DIM_ICONS[dim]}
            {dim === 'all' ? 'All' : DIM_LABELS[dim]}
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${activeDim === dim ? 'bg-indigo-200 text-indigo-800' : 'bg-gray-100 text-gray-500'}`}>
              {dimCounts[dim] || 0}
            </span>
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-gray-400 py-6 text-center">Analyzing funnel...</p>}
      {error && <p className="text-sm text-red-500 py-6 text-center">Error: {error}</p>}
      {!loading && !error && filtered.length === 0 && payload && (
        <p className="text-sm text-emerald-600 py-6 text-center">
          No bottlenecks detected in this view. Try the All tab or switch dimensions.
        </p>
      )}

      <div className="space-y-3">
        {filtered.map((rec) => (
          <RecCard
            key={rec.rec_id}
            rec={rec}
            expanded={expandedId === rec.rec_id}
            onToggle={() => setExpandedId(expandedId === rec.rec_id ? null : rec.rec_id)}
          />
        ))}
      </div>
    </div>
  )
}

function RecCard({ rec, expanded, onToggle }: { rec: Recommendation; expanded: boolean; onToggle: () => void }) {
  const sev = SEVERITY_STYLES[rec.severity] || SEVERITY_STYLES.info
  const ctaLabel = {
    creative: 'Open Creative Library',
    landing_page: 'Open Landing Pages',
    country: 'Open Country Dashboard',
  }[rec.deep_link_target]

  // Find the from/to indices to draw the bottleneck arrow inside the mini-funnel
  const fromIdx = rec.funnel_snapshot.findIndex((s) => s.is_bottleneck_in)
  const toIdx = rec.funnel_snapshot.findIndex((s) => s.is_bottleneck_out)

  return (
    <div className={`rounded-lg border ${sev.card} transition-colors`}>
      <button
        onClick={onToggle}
        className="w-full text-left p-4 flex items-start gap-3 hover:bg-black/[0.015]"
      >
        <span className={`text-[10px] uppercase tracking-wider font-bold rounded px-1.5 py-0.5 mt-0.5 shrink-0 ${sev.badge}`}>
          {sev.label}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold text-gray-800">{rec.transition_name}</span>
            <ArrowRight className="w-3 h-3 text-gray-400" />
            <span className="text-gray-600">{rec.root_cause}</span>
            <span className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 px-2 py-0.5 bg-white rounded border border-gray-200">
              {DIM_ICONS[rec.breakdown_dim] || DIM_ICONS.overall}
              {rec.dimension_label}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-3 mt-1.5 text-xs text-gray-600">
            <span>
              {rec.metric_label}:{' '}
              <span className="font-semibold text-gray-800">{pctText(rec.current_conversion_rate)}</span>
              {rec.prev_conversion_rate !== null && (
                <span className="text-gray-400 ml-1">
                  (was {pctText(rec.prev_conversion_rate)})
                </span>
              )}
            </span>
            {rec.conversion_rate_change !== null && (
              <span
                className={`inline-flex items-center gap-0.5 font-medium ${
                  rec.conversion_rate_change < 0 ? 'text-red-600' : 'text-emerald-600'
                }`}
              >
                <TrendingDown className="w-3 h-3" />
                {pctText(rec.conversion_rate_change, true)}
              </span>
            )}
            <span className="text-gray-400">
              · {fmtNum(rec.current_volume_in)} → {fmtNum(rec.current_volume_out)}
            </span>
          </div>
        </div>
        <div className="text-gray-400 shrink-0 mt-1">
          {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-gray-200/70 p-4 space-y-4">
          <p className="text-sm text-gray-700">
            <AlertTriangle className="w-4 h-4 text-amber-500 inline mr-1.5 -mt-0.5" />
            {rec.hint}
          </p>

          {/* Mini funnel bar */}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold mb-1.5">
              Slice funnel
            </div>
            <div className="flex items-center gap-1">
              {rec.funnel_snapshot.map((s, i) => {
                const isBottleneck = i === fromIdx || i === toIdx
                const isBetween = i === fromIdx + 1
                return (
                  <div key={s.key} className="flex items-center gap-1 min-w-0 flex-1">
                    <div
                      className={`flex-1 min-w-0 rounded px-2 py-1.5 text-xs ${
                        isBottleneck
                          ? 'bg-red-100 text-red-800 font-semibold border border-red-200'
                          : 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      <div className="truncate text-[10px] uppercase tracking-wide opacity-70">{s.label}</div>
                      <div className="text-sm font-bold">{fmtNum(s.value)}</div>
                    </div>
                    {i < rec.funnel_snapshot.length - 1 && (
                      <ArrowRight
                        className={`w-3 h-3 shrink-0 ${
                          isBetween && i === fromIdx ? 'text-red-500' : 'text-gray-300'
                        }`}
                      />
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {/* Top contributors */}
          {rec.top_contributors && rec.top_contributors.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold mb-1.5">
                Top contributors (worst first)
              </div>
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 text-gray-500">
                    <tr>
                      <th className="text-left py-2 px-3 font-medium">Name</th>
                      <th className="text-right py-2 px-3 font-medium">Volume in</th>
                      <th className="text-right py-2 px-3 font-medium">Volume out</th>
                      <th className="text-right py-2 px-3 font-medium">{rec.metric_label}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rec.top_contributors.map((c) => {
                      const inVal = c.kind === 'ad' ? c.impressions : c.in
                      const outVal = c.kind === 'ad' ? c.clicks : c.out
                      const rate = c.kind === 'ad' ? c.ctr : c.rate
                      return (
                        <tr key={`${c.kind}-${c.id}`} className="border-t border-gray-100 hover:bg-gray-50">
                          <td className="py-2 px-3 text-gray-800">
                            <div className="font-medium truncate max-w-[280px]" title={c.name}>{c.name}</div>
                            {c.account_name && (
                              <div className="text-[10px] text-gray-400 truncate">{c.account_name}</div>
                            )}
                            {c.url && (
                              <a
                                href={c.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-[10px] text-blue-500 hover:underline truncate block"
                              >
                                {c.url}
                              </a>
                            )}
                          </td>
                          <td className="py-2 px-3 text-right text-gray-700">{fmtNum(inVal || 0)}</td>
                          <td className="py-2 px-3 text-right text-gray-700">{fmtNum(outVal || 0)}</td>
                          <td className="py-2 px-3 text-right">
                            <span className="font-semibold text-red-600">{pctText(rate ?? null)}</span>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-2">
            <Link
              href={rec.deep_link_url}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700"
            >
              {ctaLabel}
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}
