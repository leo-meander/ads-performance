'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Activity,
  Bot,
  Plus,
  RefreshCw,
  Megaphone,
  Rocket,
  ExternalLink,
  AlertTriangle,
  UserPlus,
  Layers,
  Globe2,
  Filter,
  Sparkles,
} from 'lucide-react'
import { apiFetch } from '@/lib/api'
import MetricTrendChart, { TrendRow, TrendMarker } from '@/components/dashboard/MetricTrendChart'

export type ChangeLogItem = {
  id: string
  occurred_at: string
  created_at: string
  category: string
  source: 'auto' | 'manual'
  triggered_by: string
  title: string
  description: string | null
  country: string | null
  branch: string | null
  platform: string | null
  account_id: string | null
  account_name: string | null
  campaign_id: string | null
  campaign_name: string | null
  ad_set_id: string | null
  ad_set_name: string | null
  ad_id: string | null
  ad_name: string | null
  before_value: Record<string, unknown> | null
  after_value: Record<string, unknown> | null
  metrics_snapshot: Record<string, number> | null
  source_url: string | null
  author_user_id: string | null
  author_name: string | null
  action_log_id: string | null
  rule_id: string | null
}

type ListResponse = {
  items: ChangeLogItem[]
  total: number
  limit: number
  offset: number
  period: { from: string; to: string }
}

// Marker colour per activity category, used for the dots overlaid on the trend.
const CATEGORY_MARKER_COLOR: Record<string, string> = {
  ad_creation: '#10b981',
  automation_rule_applied: '#6366f1',
  landing_page: '#a855f7',
  external_seasonality: '#f59e0b',
  external_competitor: '#f43f5e',
  external_algorithm: '#0ea5e9',
  tracking_integrity: '#ef4444',
  recommendation_applied: '#8b5cf6',
}

const CATEGORY_META: Record<string, { label: string; color: string; icon: JSX.Element }> = {
  ad_mutation: { label: 'Ad Mutation', color: 'bg-blue-100 text-blue-700', icon: <Activity className="w-3.5 h-3.5" /> },
  ad_creation: { label: 'Ad Creation', color: 'bg-emerald-100 text-emerald-700', icon: <Rocket className="w-3.5 h-3.5" /> },
  automation_rule_applied: { label: 'Automation Rule', color: 'bg-indigo-100 text-indigo-700', icon: <Bot className="w-3.5 h-3.5" /> },
  landing_page: { label: 'Landing Page', color: 'bg-purple-100 text-purple-700', icon: <Layers className="w-3.5 h-3.5" /> },
  external_seasonality: { label: 'Seasonality', color: 'bg-amber-100 text-amber-700', icon: <Globe2 className="w-3.5 h-3.5" /> },
  external_competitor: { label: 'Competitor', color: 'bg-rose-100 text-rose-700', icon: <Megaphone className="w-3.5 h-3.5" /> },
  external_algorithm: { label: 'Algorithm', color: 'bg-sky-100 text-sky-700', icon: <RefreshCw className="w-3.5 h-3.5" /> },
  tracking_integrity: { label: 'Tracking', color: 'bg-red-100 text-red-700', icon: <AlertTriangle className="w-3.5 h-3.5" /> },
  recommendation_applied: { label: 'Recommendation', color: 'bg-violet-100 text-violet-700', icon: <Sparkles className="w-3.5 h-3.5" /> },
  other: { label: 'Other', color: 'bg-gray-100 text-gray-700', icon: <UserPlus className="w-3.5 h-3.5" /> },
}

const CATEGORY_FILTERS = Object.keys(CATEGORY_META)

function relativeTime(iso: string): string {
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d ago`
  return d.toLocaleDateString('vi-VN')
}

function fmtDateHeader(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleDateString('vi-VN', {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function fmtNum(n: number): string {
  if (n === 0) return '0'
  if (Math.abs(n) >= 1000) return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(n)
  return n.toFixed(2)
}

function DiffBlock({ before, after }: { before: Record<string, unknown> | null; after: Record<string, unknown> | null }) {
  if (!before && !after) return null
  const keys = Array.from(new Set([...Object.keys(before || {}), ...Object.keys(after || {})]))
  if (keys.length === 0) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {keys.map((k) => {
        const b = before?.[k]
        const a = after?.[k]
        const changed = JSON.stringify(b) !== JSON.stringify(a)
        if (!changed) return null
        return (
          <span key={k} className="inline-flex items-center gap-1 text-xs bg-gray-50 border border-gray-200 rounded-md px-2 py-0.5">
            <span className="text-gray-500">{k}:</span>
            {b !== undefined && b !== null && (
              <span className="line-through text-red-500 font-mono">{String(b)}</span>
            )}
            {a !== undefined && a !== null && (
              <span className="text-emerald-600 font-mono">{String(a)}</span>
            )}
          </span>
        )
      })}
    </div>
  )
}

function SnapshotChips({ snap }: { snap: Record<string, number> | null }) {
  if (!snap) return null
  const items: { label: string; val: string }[] = []
  if (snap.days !== undefined) items.push({ label: `Last ${snap.days}d`, val: '' })
  if (snap.spend !== undefined) items.push({ label: 'Spend', val: fmtNum(snap.spend) })
  if (snap.conversions !== undefined) items.push({ label: 'Conv', val: fmtNum(snap.conversions) })
  if (snap.roas !== undefined) items.push({ label: 'ROAS', val: snap.roas.toFixed(2) })
  if (snap.cpa !== undefined) items.push({ label: 'CPA', val: fmtNum(snap.cpa) })
  if (snap.ctr !== undefined) items.push({ label: 'CTR', val: `${(snap.ctr * 100).toFixed(2)}%` })
  if (items.length === 0) return null
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      <span className="text-xs text-gray-400 self-center">baseline:</span>
      {items.map((i, idx) => (
        <span key={idx} className="text-xs bg-gray-50 border border-gray-200 rounded-md px-2 py-0.5">
          <span className="text-gray-500">{i.label}</span>
          {i.val && <span className="ml-1 font-mono text-gray-800">{i.val}</span>}
        </span>
      ))}
    </div>
  )
}

export type ActivityLogPanelProps = {
  country: string
  branches: string
  platform: string
  dateFrom: string
  dateTo: string
  canEdit?: boolean
  onAddManual?: () => void
  // Trigger re-fetch from parent (incremented when a manual entry is added).
  refreshKey?: number
  // Daily metric series (already fetched by the parent dashboard) rendered as
  // the trend chart at the top of this panel, with activity markers overlaid.
  trend?: TrendRow[]
  prevTrend?: TrendRow[]
  currency?: string
}

export default function ActivityLogPanel({
  country,
  branches,
  platform,
  dateFrom,
  dateTo,
  canEdit = false,
  onAddManual,
  refreshKey,
  trend = [],
  prevTrend = [],
  currency = 'VND',
}: ActivityLogPanelProps) {
  const [items, setItems] = useState<ChangeLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<string[]>([])
  const [sourceFilter, setSourceFilter] = useState<'all' | 'auto' | 'manual'>('all')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const entryRefs = useRef<Record<string, HTMLLIElement | null>>({})

  const LIMIT = 50

  const load = useCallback(async (reset: boolean) => {
    setLoading(true)
    setError(null)
    const params = new URLSearchParams({
      date_from: dateFrom,
      date_to: dateTo,
      limit: String(LIMIT),
      offset: String(reset ? 0 : offset),
    })
    if (country) params.set('country', country)
    if (branches) params.set('branches', branches)
    if (platform) params.set('platform', platform)
    if (sourceFilter !== 'all') params.set('source', sourceFilter)
    categoryFilter.forEach((c) => params.append('category', c))
    try {
      const res = await apiFetch<ListResponse>(`/api/dashboard/country/changelog?${params.toString()}`)
      if (!res.success || !res.data) {
        setError(res.error || 'Failed to load change log')
        setItems([])
        setTotal(0)
        return
      }
      if (reset) {
        setItems(res.data.items)
        setOffset(res.data.items.length)
      } else {
        setItems((prev) => [...prev, ...res.data!.items])
        setOffset((prev) => prev + res.data!.items.length)
      }
      setTotal(res.data.total)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Network error'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [country, branches, platform, dateFrom, dateTo, categoryFilter, sourceFilter, offset])

  // Reset when filters change or refreshKey bumps.
  useEffect(() => {
    setOffset(0)
    load(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [country, branches, platform, dateFrom, dateTo, categoryFilter, sourceFilter, refreshKey])

  const toggleCategory = (c: string) => {
    setCategoryFilter((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]))
  }

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Group items by day for the timeline.
  const grouped = useMemo(() => {
    const out: { day: string; items: ChangeLogItem[] }[] = []
    let cur: { day: string; items: ChangeLogItem[] } | null = null
    for (const it of items) {
      const day = it.occurred_at.slice(0, 10)
      if (!cur || cur.day !== day) {
        cur = { day, items: [] }
        out.push(cur)
      }
      cur.items.push(it)
    }
    return out
  }, [items])

  // Markers: one per day bucketed by item count, overlaid on the trend chart so
  // the user sees WHEN changes happened alongside performance. Multiple changes
  // on a day collapse into a single badged marker.
  const markers = useMemo<TrendMarker[]>(() => {
    const byDay: Record<string, { count: number; firstCategory: string; firstId: string }> = {}
    for (const it of items) {
      const day = it.occurred_at.slice(0, 10)
      if (!byDay[day]) {
        byDay[day] = { count: 0, firstCategory: it.category, firstId: it.id }
      }
      byDay[day].count += 1
    }
    return Object.entries(byDay).map(([day, info]) => ({
      day,
      count: info.count,
      firstId: info.firstId,
      color: CATEGORY_MARKER_COLOR[info.firstCategory] || '#3b82f6',
    }))
  }, [items])

  const scrollToEntry = (id: string) => {
    const el = entryRefs.current[id]
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setExpanded((prev) => {
        const next = new Set(prev)
        next.add(id)
        return next
      })
    }
  }

  const hasMore = items.length < total

  return (
    <div className="bg-white rounded-xl border border-gray-200">
      {/* Metric trends with activity markers overlaid (combined view) */}
      {trend.length > 1 && (
        <div className="px-6 pt-5 pb-2">
          <MetricTrendChart
            bare
            data={trend}
            prevData={prevTrend}
            currency={currency}
            markers={markers}
            onMarkerClick={scrollToEntry}
            title="Metric Trends"
          />
          {markers.length > 0 && (
            <p className="text-[11px] text-gray-400 mt-1">
              ● Dots mark days with logged activity — click one to jump to it below.
            </p>
          )}
        </div>
      )}

      {/* Activity header */}
      <div className="px-6 py-4 border-t flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-sm font-semibold text-gray-700">Activity Log</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            {total} change{total === 1 ? '' : 's'} in selected period
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 text-xs">
            <Filter className="w-3 h-3 text-gray-400" />
            {(['all', 'auto', 'manual'] as const).map((v) => (
              <button
                key={v}
                onClick={() => setSourceFilter(v)}
                className={`px-2 py-1 rounded-md border transition-colors ${
                  sourceFilter === v
                    ? 'bg-blue-50 border-blue-300 text-blue-700'
                    : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {v === 'all' ? 'All' : v === 'auto' ? 'Auto' : 'Manual'}
              </button>
            ))}
          </div>
          {canEdit && (
            <button
              onClick={onAddManual}
              className="inline-flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-700"
            >
              <Plus className="w-3.5 h-3.5" />
              Add manual entry
            </button>
          )}
        </div>
      </div>

      {/* Category chips */}
      <div className="px-6 pt-3 pb-2 flex flex-wrap gap-1.5">
        {CATEGORY_FILTERS.map((c) => {
          const meta = CATEGORY_META[c]
          const active = categoryFilter.includes(c)
          return (
            <button
              key={c}
              onClick={() => toggleCategory(c)}
              className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md border transition-colors ${
                active ? `${meta.color} border-current` : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50'
              }`}
            >
              {meta.icon}
              {meta.label}
            </button>
          )
        })}
        {categoryFilter.length > 0 && (
          <button
            onClick={() => setCategoryFilter([])}
            className="text-xs text-gray-500 underline ml-1"
          >
            Clear
          </button>
        )}
      </div>

      {/* Timeline */}
      <div className="px-6 py-4 space-y-5">
        {loading && items.length === 0 && (
          <div className="text-center py-8 text-gray-400 text-sm">Loading…</div>
        )}
        {error && (
          <div className="text-center py-6 text-sm text-red-500">{error}</div>
        )}
        {!loading && !error && items.length === 0 && (
          <div className="text-center py-12 text-gray-400 text-sm">
            No changes recorded in this period.
          </div>
        )}
        {grouped.map((group) => (
          <div key={group.day}>
            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              {fmtDateHeader(group.day)}
            </h3>
            <ul className="space-y-2">
              {group.items.map((it) => {
                const meta = CATEGORY_META[it.category] || CATEGORY_META.other
                const isExpanded = expanded.has(it.id)
                return (
                  <li
                    key={it.id}
                    ref={(el) => { entryRefs.current[it.id] = el }}
                    className="border border-gray-200 rounded-lg p-3 hover:bg-gray-50 transition-colors cursor-pointer"
                    onClick={() => toggleExpanded(it.id)}
                  >
                    <div className="flex items-start gap-3">
                      <div className={`flex-shrink-0 mt-0.5 p-1.5 rounded-md ${meta.color}`}>
                        {meta.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <span className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded font-medium ${
                                it.source === 'auto'
                                  ? 'bg-blue-50 text-blue-600 border border-blue-100'
                                  : 'bg-amber-50 text-amber-700 border border-amber-100'
                              }`}>
                                {it.source.toUpperCase()}
                              </span>
                              <span className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded font-medium ${meta.color}`}>
                                {meta.label}
                              </span>
                              {it.country && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 font-medium">
                                  {it.country}
                                </span>
                              )}
                              {it.branch && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
                                  {it.branch}
                                </span>
                              )}
                              {it.platform && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 uppercase">
                                  {it.platform}
                                </span>
                              )}
                            </div>
                            <div className="text-sm font-medium text-gray-900 mt-1">{it.title}</div>
                            {(it.campaign_name || it.ad_set_name || it.ad_name) && (
                              <div className="text-xs text-gray-500 mt-0.5 truncate">
                                {[it.campaign_name, it.ad_set_name, it.ad_name].filter(Boolean).join(' › ')}
                              </div>
                            )}
                          </div>
                          <div className="text-xs text-gray-400 whitespace-nowrap">
                            {relativeTime(it.occurred_at)}
                          </div>
                        </div>

                        {(it.before_value || it.after_value) && (
                          <DiffBlock before={it.before_value} after={it.after_value} />
                        )}

                        {isExpanded && (
                          <div className="mt-2 text-xs text-gray-600 space-y-1">
                            {it.description && <div>{it.description}</div>}
                            {it.author_name && (
                              <div className="text-gray-500">By {it.author_name}</div>
                            )}
                            {it.source_url && (
                              <a
                                href={it.source_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-blue-600 hover:underline"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <ExternalLink className="w-3 h-3" /> Source
                              </a>
                            )}
                            <SnapshotChips snap={it.metrics_snapshot} />
                          </div>
                        )}
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}

        {hasMore && (
          <div className="text-center pt-2">
            <button
              onClick={() => load(false)}
              disabled={loading}
              className="px-4 py-2 text-xs rounded-md border border-gray-200 bg-white hover:bg-gray-50 text-gray-700"
            >
              {loading ? 'Loading…' : `Load more (${total - items.length} remaining)`}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
