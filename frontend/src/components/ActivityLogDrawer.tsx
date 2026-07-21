'use client'

import { useEffect, useRef, useState } from 'react'
import {
  Activity,
  Bot,
  Rocket,
  Layers,
  Globe2,
  Megaphone,
  RefreshCw,
  AlertTriangle,
  Sparkles,
  UserPlus,
  ChevronDown,
  ChevronRight,
  X,
  Clock,
  Plus,
} from 'lucide-react'
import { apiFetch } from '@/lib/api'
import ManualEntryModal from '@/components/dashboard/activity/ManualEntryModal'

type Branch = { name: string; currency: string }
type CountryOption = { code: string; name: string; adset_count?: number }

type ChangeLogItem = {
  id: string
  occurred_at: string
  category: string
  source: 'auto' | 'manual'
  title: string
  description: string | null
  branch: string | null
  platform: string | null
  campaign_name: string | null
  ad_set_name: string | null
  author_name: string | null
  before_value: Record<string, unknown> | null
  after_value: Record<string, unknown> | null
}

const CATEGORY_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  ad_mutation:             { label: 'Ad Mutation',     color: 'bg-blue-100 text-blue-700',   icon: <Activity className="w-3 h-3" /> },
  ad_creation:             { label: 'Ad Creation',     color: 'bg-emerald-100 text-emerald-700', icon: <Rocket className="w-3 h-3" /> },
  automation_rule_applied: { label: 'Automation',      color: 'bg-indigo-100 text-indigo-700',  icon: <Bot className="w-3 h-3" /> },
  landing_page:            { label: 'Landing Page',    color: 'bg-purple-100 text-purple-700',  icon: <Layers className="w-3 h-3" /> },
  external_seasonality:    { label: 'Seasonality',     color: 'bg-amber-100 text-amber-700',    icon: <Globe2 className="w-3 h-3" /> },
  external_competitor:     { label: 'Competitor',      color: 'bg-rose-100 text-rose-700',      icon: <Megaphone className="w-3 h-3" /> },
  external_algorithm:      { label: 'Algorithm',       color: 'bg-sky-100 text-sky-700',        icon: <RefreshCw className="w-3 h-3" /> },
  tracking_integrity:      { label: 'Tracking',        color: 'bg-red-100 text-red-700',        icon: <AlertTriangle className="w-3 h-3" /> },
  recommendation_applied:  { label: 'Recommendation',  color: 'bg-violet-100 text-violet-700',  icon: <Sparkles className="w-3 h-3" /> },
  other:                   { label: 'Other',            color: 'bg-gray-100 text-gray-600',      icon: <UserPlus className="w-3 h-3" /> },
}

function catMeta(cat: string) {
  return CATEGORY_META[cat] ?? CATEGORY_META.other
}

type DayGroup = {
  dateKey: string   // YYYY-MM-DD
  label: string
  items: ChangeLogItem[]
  categoryCounts: Record<string, number>
}

function groupByDay(items: ChangeLogItem[]): DayGroup[] {
  const map = new Map<string, ChangeLogItem[]>()
  for (const item of items) {
    const d = item.occurred_at.slice(0, 10)
    if (!map.has(d)) map.set(d, [])
    map.get(d)!.push(item)
  }
  // sort descending
  const keys = [...map.keys()].sort((a, b) => b.localeCompare(a))
  return keys.map((k) => {
    const dayItems = map.get(k)!
    const categoryCounts: Record<string, number> = {}
    for (const it of dayItems) {
      categoryCounts[it.category] = (categoryCounts[it.category] ?? 0) + 1
    }
    const d = new Date(k + 'T12:00:00')
    const today = new Date(); today.setHours(0,0,0,0)
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
    const dMid = new Date(k + 'T00:00:00')
    let label = d.toLocaleDateString('vi-VN', { weekday: 'short', day: 'numeric', month: 'short' })
    if (dMid >= today) label = `Hôm nay — ${label}`
    else if (dMid >= yesterday) label = `Hôm qua — ${label}`
    return { dateKey: k, label, items: dayItems, categoryCounts }
  })
}

function DayCard({ group }: { group: DayGroup }) {
  const [open, setOpen] = useState(false)
  const topCats = Object.entries(group.categoryCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 4)

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <button
        onClick={() => setOpen((p) => !p)}
        className="w-full flex items-center justify-between px-3 py-2.5 bg-white hover:bg-gray-50 text-left gap-2"
      >
        <div className="flex items-center gap-2 min-w-0">
          {open ? <ChevronDown className="w-3.5 h-3.5 text-gray-400 shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400 shrink-0" />}
          <span className="text-xs font-medium text-gray-700 truncate">{group.label}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {topCats.map(([cat, count]) => {
            const m = catMeta(cat)
            return (
              <span key={cat} className={`inline-flex items-center gap-0.5 text-[10px] font-medium rounded-full px-1.5 py-0.5 ${m.color}`}>
                {m.icon}
                {count}
              </span>
            )
          })}
          <span className="text-[10px] text-gray-400 ml-1">{group.items.length} changes</span>
        </div>
      </button>

      {open && (
        <div className="divide-y divide-gray-100 border-t border-gray-100">
          {group.items.map((item) => {
            const m = catMeta(item.category)
            const time = new Date(item.occurred_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })
            return (
              <div key={item.id} className="px-3 py-2 bg-gray-50/50">
                <div className="flex items-start gap-2">
                  <span className={`inline-flex items-center gap-1 text-[10px] rounded-full px-1.5 py-0.5 shrink-0 mt-0.5 ${m.color}`}>
                    {m.icon}
                    <span>{m.label}</span>
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs text-gray-800 leading-snug">{item.title}</p>
                    {item.description && (
                      <p className="text-[10px] text-gray-500 mt-0.5 leading-snug">{item.description}</p>
                    )}
                    <div className="flex flex-wrap gap-x-2 gap-y-0.5 mt-1">
                      {item.branch && <span className="text-[10px] text-gray-400">{item.branch}</span>}
                      {item.platform && <span className="text-[10px] text-gray-400">{item.platform}</span>}
                      {item.campaign_name && <span className="text-[10px] text-gray-400 truncate max-w-[140px]">{item.campaign_name}</span>}
                    </div>
                    {/* before/after diff */}
                    {(item.before_value || item.after_value) && (() => {
                      const keys = Array.from(new Set([
                        ...Object.keys(item.before_value ?? {}),
                        ...Object.keys(item.after_value ?? {}),
                      ])).filter((k) => JSON.stringify(item.before_value?.[k]) !== JSON.stringify(item.after_value?.[k]))
                      if (keys.length === 0) return null
                      return (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {keys.slice(0, 3).map((k) => (
                            <span key={k} className="text-[10px] bg-white border border-gray-200 rounded px-1.5 py-0.5 inline-flex gap-1">
                              <span className="text-gray-400">{k}:</span>
                              {item.before_value?.[k] != null && (
                                <span className="line-through text-red-500 font-mono">{String(item.before_value[k])}</span>
                              )}
                              {item.after_value?.[k] != null && (
                                <span className="text-emerald-600 font-mono">{String(item.after_value[k])}</span>
                              )}
                            </span>
                          ))}
                        </div>
                      )
                    })()}
                  </div>
                  <span className="text-[10px] text-gray-400 shrink-0">{time}</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

const PRESETS = [
  { label: '7 ngày', days: 7 },
  { label: '14 ngày', days: 14 },
  { label: '30 ngày', days: 30 },
]

function toDateStr(d: Date) {
  return d.toISOString().slice(0, 10)
}

function addDays(d: Date, n: number) {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}

type Props = {
  open: boolean
  onClose: () => void
}

export default function ActivityLogDrawer({ open, onClose }: Props) {
  const today = new Date()
  const [preset, setPreset] = useState(7)
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [useCustom, setUseCustom] = useState(false)
  const [items, setItems] = useState<ChangeLogItem[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const backdropRef = useRef<HTMLDivElement>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [branches, setBranches] = useState<Branch[]>([])
  const [countries, setCountries] = useState<CountryOption[]>([])
  const [categoryFilter, setCategoryFilter] = useState<string[]>([])

  const dateFrom = useCustom && customFrom ? customFrom : toDateStr(addDays(today, -(preset - 1)))
  const dateTo   = useCustom && customTo   ? customTo   : toDateStr(today)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo, limit: '200' })
    categoryFilter.forEach((c) => params.append('category', c))
    apiFetch<{ items: ChangeLogItem[]; total: number }>(`/api/dashboard/country/changelog?${params}`)
      .then((res) => {
        if (res.success && res.data) {
          setItems(res.data.items)
          setTotal(res.data.total)
        }
      })
      .finally(() => setLoading(false))
  }, [open, dateFrom, dateTo, refreshKey, categoryFilter])

  useEffect(() => {
    if (!open) return
    if (branches.length === 0) {
      apiFetch<Branch[]>('/api/branches').then((r) => { if (r.success && r.data) setBranches(r.data) }).catch(() => {})
    }
    if (countries.length === 0) {
      apiFetch<CountryOption[]>('/api/dashboard/country/countries').then((r) => { if (r.success && r.data) setCountries(r.data) }).catch(() => {})
    }
  }, [open])

  const groups = groupByDay(items)

  // close on backdrop click
  function handleBackdrop(e: React.MouseEvent) {
    if (e.target === backdropRef.current) onClose()
  }

  if (!open) return null

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdrop}
      className="fixed inset-0 z-50 flex justify-end"
      style={{ background: 'rgba(0,0,0,0.18)' }}
    >
      <div
        className="w-[420px] max-w-full h-full bg-white shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 shrink-0">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-gray-500" />
            <span className="text-sm font-semibold text-gray-800">Activity Log</span>
            {!loading && total > 0 && (
              <span className="text-xs text-gray-400">{total} entries</span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setModalOpen(true)}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              <Plus className="w-3.5 h-3.5" />
              Add entry
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Category chips */}
        <div className="px-4 pt-2.5 pb-2 border-b border-gray-100 shrink-0 flex flex-wrap gap-1.5">
          {Object.entries(CATEGORY_META).map(([key, m]) => {
            const active = categoryFilter.includes(key)
            return (
              <button
                key={key}
                onClick={() => setCategoryFilter((prev) =>
                  prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]
                )}
                className={`inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border transition-colors ${
                  active ? `${m.color} border-current` : 'bg-white border-gray-200 text-gray-500 hover:bg-gray-50'
                }`}
              >
                {m.icon}
                {m.label}
              </button>
            )
          })}
          {categoryFilter.length > 0 && (
            <button onClick={() => setCategoryFilter([])} className="text-[11px] text-gray-400 underline ml-0.5">
              Clear
            </button>
          )}
        </div>

        {/* Date filter */}
        <div className="px-4 py-3 border-b border-gray-100 shrink-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            {PRESETS.map((p) => (
              <button
                key={p.days}
                onClick={() => { setPreset(p.days); setUseCustom(false) }}
                className={`text-xs px-2.5 py-1 rounded-full border transition-colors ${
                  !useCustom && preset === p.days
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'border-gray-200 text-gray-600 hover:border-indigo-300'
                }`}
              >
                {p.label}
              </button>
            ))}
            <div className="flex items-center gap-1 ml-1">
              <input
                type="date"
                value={customFrom}
                onChange={(e) => { setCustomFrom(e.target.value); setUseCustom(true) }}
                className="text-xs border border-gray-200 rounded px-1.5 py-1 text-gray-700"
              />
              <span className="text-gray-400 text-xs">→</span>
              <input
                type="date"
                value={customTo}
                onChange={(e) => { setCustomTo(e.target.value); setUseCustom(true) }}
                className="text-xs border border-gray-200 rounded px-1.5 py-1 text-gray-700"
              />
            </div>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
          {loading && (
            <div className="flex items-center justify-center py-12 text-sm text-gray-400">
              Loading...
            </div>
          )}
          {!loading && groups.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 gap-2 text-gray-400">
              <Clock className="w-8 h-8 opacity-30" />
              <span className="text-sm">Không có activity nào trong khoảng này</span>
            </div>
          )}
          {!loading && groups.map((g) => (
            <DayCard key={g.dateKey} group={g} />
          ))}
          {!loading && total > 200 && (
            <p className="text-center text-xs text-gray-400 py-2">
              Hiển thị 200 / {total} entries. Hãy thu hẹp date range để xem thêm.
            </p>
          )}
        </div>
      </div>

      {modalOpen && (
        <ManualEntryModal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          onCreated={() => {
            setRefreshKey((k) => k + 1)
            setModalOpen(false)
          }}
          defaultCountry={null}
          defaultBranch={null}
          branches={branches}
          countries={countries}
        />
      )}
    </div>
  )
}
