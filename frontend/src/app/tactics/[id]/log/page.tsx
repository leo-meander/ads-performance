'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import {
  ChevronLeft, ChevronRight, Search, ExternalLink, Clock, Calendar,
  Power, PowerOff, TrendingUp, TrendingDown, Bell, AlertCircle, Activity,
} from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
const PAGE_SIZE = 25

type Entry = {
  id: string
  executed_at: string | null
  action: string
  label: string
  kind: 'pause' | 'enable' | 'budget_up' | 'budget_down' | 'alert' | 'other'
  entity_level: string
  entity_name: string
  external_url: string | null
  triggered_by: string
  success: boolean
  error_message: string | null
  before: { status: string | null; daily_budget: number | null }
  after: { status: string | null; daily_budget: number | null }
  metrics: { roas: number | null; ctr: number | null; spend: number | null; cpa: number | null; revenue: number | null }
}

type ChangeLog = {
  tactic_id: string
  tactic_name: string
  account_timezone: string
  total: number
  limit: number
  offset: number
  entries: Entry[]
}

// ---- action icon family ----
function ActionIcon({ kind, success }: { kind: Entry['kind']; success: boolean }) {
  const base = 'w-5 h-5'
  if (!success) return <AlertCircle className={`${base} text-red-500`} />
  switch (kind) {
    case 'enable': return <Power className={`${base} text-emerald-500`} />
    case 'pause': return <PowerOff className={`${base} text-gray-400`} />
    case 'budget_up': return <TrendingUp className={`${base} text-blue-500`} />
    case 'budget_down': return <TrendingDown className={`${base} text-amber-500`} />
    case 'alert': return <Bell className={`${base} text-violet-500`} />
    default: return <Activity className={`${base} text-gray-400`} />
  }
}

function refinedLabel(e: Entry): string {
  if (e.kind === 'budget_up') return 'Budget increased'
  if (e.kind === 'budget_down') return 'Budget decreased'
  return e.label
}

function fmtBudget(v: number | null | undefined): string | null {
  if (v === null || v === undefined) return null
  return v.toLocaleString(undefined, { maximumFractionDigits: 0 })
}

export default function TacticChangeLogPage() {
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const tacticId = params?.id

  const [data, setData] = useState<ChangeLog | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [searchInput, setSearchInput] = useState('')
  const [query, setQuery] = useState('')

  const fetchLog = useCallback(() => {
    if (!tacticId) return
    setLoading(true)
    const qs = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String((page - 1) * PAGE_SIZE),
    })
    if (query) qs.set('q', query)
    fetch(`${API_BASE}/api/tactics/${tacticId}/change-log?${qs.toString()}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setData(d.data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tacticId, page, query])

  useEffect(() => { fetchLog() }, [fetchLog])

  const tz = data?.account_timezone || 'UTC'
  const timeFmt = useMemo(
    () => new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: tz }),
    [tz],
  )
  const dateFmt = useMemo(
    () => new Intl.DateTimeFormat('en-US', { month: '2-digit', day: '2-digit', year: 'numeric', timeZone: tz }),
    [tz],
  )

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  const submitSearch = () => {
    setPage(1)
    setQuery(searchInput.trim())
  }

  // compact pager: 1 .. window .. last
  const pageNumbers = useMemo(() => {
    const out: (number | '…')[] = []
    const add = (n: number) => out.push(n)
    if (totalPages <= 9) {
      for (let i = 1; i <= totalPages; i++) add(i)
    } else {
      const left = Math.max(2, page - 1)
      const right = Math.min(totalPages - 1, page + 1)
      add(1)
      if (left > 2) out.push('…')
      for (let i = left; i <= right; i++) add(i)
      if (right < totalPages - 1) out.push('…')
      add(totalPages)
    }
    return out
  }, [page, totalPages])

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center gap-4">
          <button
            onClick={() => router.push('/tactics')}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm text-gray-700 hover:bg-gray-50"
          >
            <ChevronLeft className="w-4 h-4" /> Back
          </button>
          <div className="flex items-center gap-2 min-w-0">
            <Activity className="w-5 h-5 text-rose-500 flex-shrink-0" />
            <h1 className="text-lg font-semibold text-gray-900 truncate">
              {data?.tactic_name || 'Change Log'}
            </h1>
          </div>
          {data && (
            <span className="ml-auto text-xs text-gray-500">
              {data.total.toLocaleString()} action{data.total === 1 ? '' : 's'} logged
            </span>
          )}
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-6 py-6">
        {/* Search + pagination bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                value={searchInput}
                onChange={e => setSearchInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && submitSearch()}
                placeholder="Search by name"
                className="w-72 pl-9 pr-3 py-2 text-sm border rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-200"
              />
            </div>
            <button
              onClick={submitSearch}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700"
            >
              Submit
            </button>
            {query && (
              <button
                onClick={() => { setSearchInput(''); setQuery(''); setPage(1) }}
                className="text-xs text-gray-500 hover:text-gray-800 underline"
              >
                clear
              </button>
            )}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center gap-1">
              <button
                disabled={page === 1}
                onClick={() => setPage(p => Math.max(1, p - 1))}
                className="p-1.5 rounded-lg border text-gray-500 disabled:opacity-40 hover:bg-gray-50"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              {pageNumbers.map((n, i) =>
                n === '…' ? (
                  <span key={`e${i}`} className="px-2 text-gray-400">…</span>
                ) : (
                  <button
                    key={n}
                    onClick={() => setPage(n)}
                    className={`w-9 h-9 rounded-lg text-sm border ${
                      n === page
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    {n}
                  </button>
                ),
              )}
              <button
                disabled={page === totalPages}
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                className="p-1.5 rounded-lg border text-gray-500 disabled:opacity-40 hover:bg-gray-50"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>

        {/* Table */}
        <div className="bg-white border rounded-xl overflow-hidden">
          <div className="grid grid-cols-[260px_1fr_minmax(280px,1.2fr)] bg-gray-50 border-b text-xs font-semibold text-gray-500 uppercase tracking-wide">
            <div className="px-5 py-3">
              Time
              <div className="font-normal normal-case tracking-normal text-[11px] text-gray-400 mt-0.5">
                Account time zone ({tz})
              </div>
            </div>
            <div className="px-5 py-3 flex items-center">Ad Name</div>
            <div className="px-5 py-3 flex items-center">Action</div>
          </div>

          {loading ? (
            <div className="px-5 py-16 text-center text-gray-400 text-sm">Loading…</div>
          ) : !data || data.entries.length === 0 ? (
            <div className="px-5 py-16 text-center text-gray-400 text-sm">
              {query ? `No actions match "${query}".` : 'No actions logged yet for this tactic.'}
            </div>
          ) : (
            data.entries.map((e, idx) => {
              const dt = e.executed_at ? new Date(e.executed_at) : null
              const bBud = fmtBudget(e.before.daily_budget)
              const aBud = fmtBudget(e.after.daily_budget)
              const showBudget = (e.kind === 'budget_up' || e.kind === 'budget_down') && (bBud || aBud)
              const roas = e.metrics.roas
              const ctr = e.metrics.ctr
              return (
                <div
                  key={e.id}
                  className={`grid grid-cols-[260px_1fr_minmax(280px,1.2fr)] items-center border-b last:border-b-0 ${
                    idx % 2 ? 'bg-gray-50/40' : 'bg-white'
                  } hover:bg-indigo-50/30 transition-colors`}
                >
                  {/* Time */}
                  <div className="px-5 py-3.5 flex items-center gap-4 text-sm text-gray-700">
                    <span className="inline-flex items-center gap-1.5 tabular-nums">
                      <Clock className="w-4 h-4 text-gray-400" />
                      {dt ? timeFmt.format(dt) : '—'}
                    </span>
                    <span className="inline-flex items-center gap-1.5 tabular-nums text-gray-500">
                      <Calendar className="w-4 h-4 text-gray-400" />
                      {dt ? dateFmt.format(dt) : '—'}
                    </span>
                  </div>

                  {/* Ad Name */}
                  <div className="px-5 py-3.5 flex items-center gap-2 min-w-0">
                    <span className="truncate text-sm text-gray-800" title={e.entity_name}>
                      {e.entity_name}
                    </span>
                    {e.external_url && (
                      <a
                        href={e.external_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-gray-400 hover:text-indigo-600 flex-shrink-0"
                        title="Open in Meta Ads Manager"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </a>
                    )}
                  </div>

                  {/* Action */}
                  <div className="px-5 py-3.5">
                    <div className="flex items-center gap-2.5">
                      <ActionIcon kind={e.kind} success={e.success} />
                      <span className={`text-sm font-medium ${e.success ? 'text-gray-800' : 'text-red-600'}`}>
                        {refinedLabel(e)}
                      </span>
                      {showBudget && (
                        <span className="text-xs text-gray-500 tabular-nums">
                          {bBud ?? '?'} → <span className="font-medium text-gray-700">{aBud ?? '?'}</span>
                        </span>
                      )}
                      {e.triggered_by === 'manual' && (
                        <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
                          manual
                        </span>
                      )}
                    </div>
                    {/* metric badges */}
                    {e.success && (roas != null || ctr != null) && (
                      <div className="flex items-center gap-1.5 mt-1.5">
                        {roas != null && (
                          <span className="text-[11px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 tabular-nums">
                            ROAS {roas.toFixed(2)}
                          </span>
                        )}
                        {ctr != null && (
                          <span className="text-[11px] px-1.5 py-0.5 rounded bg-sky-50 text-sky-700 tabular-nums">
                            CTR {(ctr * 100).toFixed(2)}%
                          </span>
                        )}
                      </div>
                    )}
                    {!e.success && e.error_message && (
                      <div className="text-xs text-red-500 mt-1 break-words line-clamp-2" title={e.error_message}>
                        {e.error_message}
                      </div>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
