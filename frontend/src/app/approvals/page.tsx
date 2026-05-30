'use client'

import { Fragment, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { Plus, Send, Layers, Search, AlertTriangle, ChevronRight, ChevronDown } from 'lucide-react'
import { useAuth } from '@/components/AuthContext'
import ApprovalStatusBadge from '@/components/ApprovalStatusBadge'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Approval {
  id: string
  batch_id: string | null
  combo_id: string
  combo_name: string | null
  combo_id_display: string | null
  round: number
  status: string
  submitted_by: string | null
  submitter_name: string | null
  submitted_at: string | null
  deadline: string | null
  resolved_at: string | null
  reviewers: { reviewer_name: string; status: string }[]
}

// A row in the rendered table:
//  - 'single': all standalone rounds of ONE combo, newest round as head, older
//    rounds collapsed into history (a re-submit after needs-revision/reject adds
//    a new round row — we fold them so the list shows one line per combo).
//  - 'batch': N child approvals reviewed all-or-nothing in one batch.
interface Row {
  kind: 'single' | 'batch'
  key: string
  members: Approval[]
}

// any REJECTED → REJECTED; any NEEDS_REVISION → NEEDS_REVISION;
// all APPROVED → APPROVED; all LAUNCHED → LAUNCHED; else PENDING_APPROVAL
function rollupStatus(statuses: string[]): string {
  if (statuses.some(s => s === 'REJECTED')) return 'REJECTED'
  if (statuses.some(s => s === 'NEEDS_REVISION')) return 'NEEDS_REVISION'
  if (statuses.length > 0 && statuses.every(s => s === 'LAUNCHED')) return 'LAUNCHED'
  if (statuses.length > 0 && statuses.every(s => s === 'APPROVED' || s === 'LAUNCHED')) return 'APPROVED'
  return 'PENDING_APPROVAL'
}

function groupRows(approvals: Approval[]): Row[] {
  const batches = new Map<string, Approval[]>()
  const combos = new Map<string, Approval[]>()
  const rows: Row[] = []
  for (const a of approvals) {
    if (a.batch_id) {
      const existing = batches.get(a.batch_id)
      if (existing) {
        existing.push(a)
      } else {
        const members: Approval[] = [a]
        batches.set(a.batch_id, members)
        // Reserve the row position at first sighting to keep submit order.
        rows.push({ kind: 'batch', key: a.batch_id, members })
      }
    } else {
      // Fold every standalone round of the same combo into one row.
      const existing = combos.get(a.combo_id)
      if (existing) {
        existing.push(a)
      } else {
        const members: Approval[] = [a]
        combos.set(a.combo_id, members)
        rows.push({ kind: 'single', key: a.combo_id, members })
      }
    }
  }
  // Newest round first inside each combo group → head is the current round.
  for (const row of rows) {
    if (row.kind === 'single' && row.members.length > 1) {
      row.members.sort((x, y) => (y.round || 0) - (x.round || 0))
    }
  }
  return rows
}

const startOfDay = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()

// Turn an absolute deadline into a human-scannable label relative to today.
// Only PENDING items get urgency tones — a past deadline on an already-resolved
// combo is just history, not a fire to put out.
function deadlineMeta(deadline: string | null, status: string) {
  if (!deadline) return { date: null as Date | null, overdue: false, label: '', tone: 'muted' as const }
  const d = new Date(deadline)
  const days = Math.round((startOfDay(d) - startOfDay(new Date())) / 86400000)
  const pending = status === 'PENDING_APPROVAL'
  const overdue = pending && days < 0
  let label: string
  let tone: 'red' | 'amber' | 'muted'
  if (overdue) { label = `${-days}d overdue`; tone = 'red' }
  else if (pending && days === 0) { label = 'Due today'; tone = 'amber' }
  else if (pending && days === 1) { label = 'Due tomorrow'; tone = 'amber' }
  else if (pending && days > 0 && days <= 3) { label = `Due in ${days}d`; tone = 'amber' }
  else { label = d.toLocaleDateString(); tone = 'muted' }
  return { date: d, overdue, label, tone }
}

// Sort actionable work to the top: overdue first (most overdue leading), then
// pending by nearest deadline, then everything else by recency.
function urgencyRank(status: string, overdue: boolean): number {
  if (overdue) return 0
  if (status === 'PENDING_APPROVAL') return 1
  if (status === 'NEEDS_REVISION') return 2
  if (status === 'APPROVED') return 3
  return 4
}

export default function ApprovalsPage() {
  const { user } = useAuth()
  const [tab, setTab] = useState<'all' | 'pending'>('all')
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('')
  const [search, setSearch] = useState('')
  const [resending, setResending] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggleExpand = (key: string) =>
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const handleResend = async (approvalId: string) => {
    if (resending) return
    setResending(approvalId)
    try {
      const r = await fetch(`${API_BASE}/api/approvals/${approvalId}/resend-request`, {
        method: 'POST',
        credentials: 'include',
      })
      const raw = await r.text()
      let data: { success?: boolean; error?: string; data?: { queued_count?: number; skipped?: unknown[] } } = {}
      try { data = JSON.parse(raw) } catch { /* non-JSON response */ }

      if (r.ok && data.success) {
        const queued = data.data?.queued_count ?? 0
        const skipped = data.data?.skipped?.length ?? 0
        alert(`Resent to ${queued} reviewer${queued !== 1 ? 's' : ''}${skipped > 0 ? ` — ${skipped} skipped` : ''}.`)
      } else {
        const reason = data.error || (data as { detail?: string }).detail || raw.slice(0, 200) || 'no body'
        alert(`Failed (HTTP ${r.status}): ${reason}`)
      }
    } catch (e) {
      alert(`Network error: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setResending(null)
    }
  }

  // Fetch the full set for the active tab; status/overdue/search filtering is
  // done client-side so the summary counts stay stable and filtering is instant.
  useEffect(() => {
    setLoading(true)
    const endpoint = tab === 'pending' ? '/api/approvals/pending' : '/api/approvals'
    fetch(`${API_BASE}${endpoint}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setApprovals(data.data.items || []) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tab])

  const isReviewer = user?.roles?.includes('reviewer') || user?.roles?.includes('admin')

  // Pre-compute per-row status + urgency once; reused for counts, filter, sort.
  const rows = useMemo(() => {
    return groupRows(approvals).map(row => {
      const head = row.members[0]
      const isBatch = row.kind === 'batch'
      const status = isBatch ? rollupStatus(row.members.map(m => m.status)) : head.status
      const dl = deadlineMeta(head.deadline, status)
      return { row, head, isBatch, status, dl }
    })
  }, [approvals])

  const counts = useMemo(() => {
    const c = { all: rows.length, OVERDUE: 0, PENDING_APPROVAL: 0, NEEDS_REVISION: 0, APPROVED: 0 }
    for (const r of rows) {
      if (r.dl.overdue) c.OVERDUE++
      if (r.status === 'PENDING_APPROVAL') c.PENDING_APPROVAL++
      else if (r.status === 'NEEDS_REVISION') c.NEEDS_REVISION++
      else if (r.status === 'APPROVED') c.APPROVED++
    }
    return c
  }, [rows])

  const visibleRows = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows
      .filter(r => {
        if (statusFilter === 'OVERDUE') { if (!r.dl.overdue) return false }
        else if (statusFilter && r.status !== statusFilter) return false
        if (q) {
          const name = (r.isBatch
            ? `batch ${r.head.combo_name || ''}`
            : r.head.combo_name || r.head.combo_id_display || '').toLowerCase()
          if (!name.includes(q)) return false
        }
        return true
      })
      .sort((a, b) => {
        const ra = urgencyRank(a.status, a.dl.overdue)
        const rb = urgencyRank(b.status, b.dl.overdue)
        if (ra !== rb) return ra - rb
        // within pending/overdue: nearest (or most-overdue) deadline first
        if (ra <= 1 && a.dl.date && b.dl.date) return a.dl.date.getTime() - b.dl.date.getTime()
        // otherwise newest submission first
        const ta = a.head.submitted_at ? new Date(a.head.submitted_at).getTime() : 0
        const tb = b.head.submitted_at ? new Date(b.head.submitted_at).getTime() : 0
        return tb - ta
      })
  }, [rows, statusFilter, search])

  const chips: { key: string; label: string; count: number; activeClass: string }[] = [
    { key: '', label: 'All', count: counts.all, activeClass: 'bg-gray-900 text-white' },
    { key: 'OVERDUE', label: 'Overdue', count: counts.OVERDUE, activeClass: 'bg-red-600 text-white' },
    { key: 'PENDING_APPROVAL', label: 'Pending', count: counts.PENDING_APPROVAL, activeClass: 'bg-amber-500 text-white' },
    { key: 'NEEDS_REVISION', label: 'Needs Revision', count: counts.NEEDS_REVISION, activeClass: 'bg-orange-500 text-white' },
    { key: 'APPROVED', label: 'Approved', count: counts.APPROVED, activeClass: 'bg-green-600 text-white' },
  ]

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Approvals</h1>
          {!loading && counts.OVERDUE > 0 && (
            <p className="mt-1 inline-flex items-center gap-1 text-sm text-red-600 font-medium">
              <AlertTriangle className="w-3.5 h-3.5" />
              {counts.OVERDUE} overdue · {counts.PENDING_APPROVAL} awaiting review
            </p>
          )}
        </div>
        <Link href="/creative/submit" className="inline-flex items-center gap-1.5 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700">
          <Plus className="w-4 h-4" /> New Approval
        </Link>
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          <button
            onClick={() => setTab('all')}
            className={`px-3 py-1.5 rounded-md text-sm font-medium ${tab === 'all' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'}`}
          >
            All
          </button>
          {isReviewer && (
            <button
              onClick={() => setTab('pending')}
              className={`px-3 py-1.5 rounded-md text-sm font-medium ${tab === 'pending' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'}`}
            >
              Pending Review
            </button>
          )}
        </div>

        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search combo…"
            className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-300"
          />
        </div>
      </div>

      {/* Summary filter chips — counts double as the status filter. */}
      <div className="flex flex-wrap gap-2 mb-4">
        {chips.map(chip => {
          const active = statusFilter === chip.key
          const dim = chip.key !== '' && chip.count === 0
          return (
            <button
              key={chip.key || 'all'}
              onClick={() => setStatusFilter(chip.key)}
              disabled={dim}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                active ? chip.activeClass : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
              } ${dim ? 'opacity-40 cursor-default' : ''}`}
            >
              {chip.label}
              <span className={`text-xs tabular-nums ${active ? 'opacity-90' : 'text-gray-400'}`}>{chip.count}</span>
            </button>
          )
        })}
      </div>

      {loading ? (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-4 px-4 py-3.5 border-b border-gray-50 last:border-0">
              <div className="h-4 bg-gray-100 rounded animate-pulse flex-1" />
              <div className="h-5 w-20 bg-gray-100 rounded-full animate-pulse" />
              <div className="h-4 w-16 bg-gray-100 rounded animate-pulse" />
              <div className="h-4 w-16 bg-gray-100 rounded animate-pulse" />
            </div>
          ))}
        </div>
      ) : visibleRows.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center">
          <p className="text-gray-500 font-medium">No approvals found</p>
          <p className="text-sm text-gray-400 mt-1">
            {statusFilter || search ? 'Try clearing the filter or search.' : 'Submit a creative to start a review.'}
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Combo</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Submitted By</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Round</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Reviewers</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Deadline</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Submitted</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Action</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map(({ row, head, isBatch, status, dl }) => {
                const href = isBatch ? `/approvals/batch/${row.key}` : `/approvals/${head.id}`
                // Reviewers are identical across batch members, so the head row's are representative.
                const approvedReviewers = head.reviewers.filter(r => r.status === 'APPROVED').length
                // Older standalone rounds, folded under the latest one as history.
                const olderRounds = isBatch ? [] : row.members.slice(1)
                const hasHistory = olderRounds.length > 0
                const isExpanded = expanded.has(row.key)
                return (
                  <Fragment key={row.key}>
                  <tr
                    className={`border-b border-gray-50 hover:bg-gray-50 ${dl.overdue ? 'bg-red-50/40' : ''}`}
                  >
                    <td className={`px-4 py-3 ${dl.overdue ? 'border-l-2 border-l-red-500' : ''}`}>
                      <Link href={href} className="text-sm font-medium text-blue-600 hover:text-blue-700">
                        {isBatch
                          ? `Batch — ${row.members.length} version${row.members.length !== 1 ? 's' : ''}`
                          : head.combo_name || head.combo_id_display || 'Unknown'}
                      </Link>
                      {isBatch && (
                        <span className="ml-2 inline-flex items-center gap-1 text-[10px] font-medium text-gray-400 uppercase tracking-wide">
                          <Layers className="w-3 h-3" /> batch
                        </span>
                      )}
                      {hasHistory && (
                        <button
                          onClick={() => toggleExpand(row.key)}
                          className="ml-2 inline-flex items-center gap-0.5 text-[11px] font-medium text-gray-500 hover:text-gray-800 align-middle"
                          title={isExpanded ? 'Hide previous rounds' : 'Show previous rounds'}
                        >
                          {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                          {row.members.length} rounds
                        </button>
                      )}
                      {isBatch && (
                        <ol className="mt-1 space-y-0.5">
                          {row.members.map((m, i) => (
                            <li key={m.id} className="flex items-start gap-1.5 text-xs text-gray-500">
                              <span className="mt-px text-gray-300 tabular-nums">{i + 1}.</span>
                              <span className="truncate">{m.combo_name || m.combo_id_display || 'Unknown'}</span>
                            </li>
                          ))}
                        </ol>
                      )}
                    </td>
                    <td className="px-4 py-3"><ApprovalStatusBadge status={status} /></td>
                    <td className="px-4 py-3 text-sm text-gray-600">{head.submitter_name || '-'}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{head.round}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5" title={head.reviewers.map(r => `${r.reviewer_name}: ${r.status}`).join('\n')}>
                        <div className="flex gap-0.5">
                          {head.reviewers.map((rv, i) => (
                            <span
                              key={i}
                              className={`w-2 h-2 rounded-full ${
                                rv.status === 'APPROVED' ? 'bg-green-500'
                                : rv.status === 'REJECTED' ? 'bg-red-500'
                                : rv.status === 'NEEDS_REVISION' ? 'bg-orange-400'
                                : 'bg-gray-300'
                              }`}
                            />
                          ))}
                        </div>
                        <span className="text-xs text-gray-500 tabular-nums">{approvedReviewers}/{head.reviewers.length}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {dl.date ? (
                        <div className="flex flex-col leading-tight">
                          <span className={
                            dl.tone === 'red' ? 'text-red-600 font-semibold'
                            : dl.tone === 'amber' ? 'text-amber-600 font-medium'
                            : 'text-gray-500'
                          }>
                            {dl.label}
                          </span>
                          {dl.tone !== 'muted' && (
                            <span className="text-[10px] text-gray-400">{dl.date.toLocaleDateString()}</span>
                          )}
                        </div>
                      ) : <span className="text-gray-300">-</span>}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {head.submitted_at ? new Date(head.submitted_at).toLocaleDateString() : '-'}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {!isBatch && head.status === 'PENDING_APPROVAL' && (user?.id === head.submitted_by || user?.roles?.includes('admin')) ? (
                        <button
                          onClick={() => handleResend(head.id)}
                          disabled={resending === head.id}
                          className="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded disabled:opacity-50 disabled:cursor-not-allowed"
                          title="Resend review request email to pending reviewers"
                        >
                          <Send className="w-3 h-3" />
                          {resending === head.id ? 'Sending…' : 'Resend'}
                        </button>
                      ) : (
                        <span className="text-gray-300">-</span>
                      )}
                    </td>
                  </tr>
                  {/* History: older standalone rounds, shown when expanded. */}
                  {isExpanded && olderRounds.map(m => {
                    const mApproved = m.reviewers.filter(r => r.status === 'APPROVED').length
                    return (
                      <tr key={m.id} className="border-b border-gray-50 bg-gray-50/40">
                        <td className="px-4 py-2 pl-10">
                          <Link href={`/approvals/${m.id}`} className="text-xs text-gray-500 hover:text-blue-600">
                            Round {m.round}
                          </Link>
                        </td>
                        <td className="px-4 py-2"><ApprovalStatusBadge status={m.status} /></td>
                        <td className="px-4 py-2 text-xs text-gray-400">{m.submitter_name || '-'}</td>
                        <td className="px-4 py-2 text-xs text-gray-400">{m.round}</td>
                        <td className="px-4 py-2 text-xs text-gray-400 tabular-nums">{mApproved}/{m.reviewers.length}</td>
                        <td className="px-4 py-2 text-xs text-gray-400">
                          {m.deadline ? new Date(m.deadline).toLocaleDateString() : '-'}
                        </td>
                        <td className="px-4 py-2 text-xs text-gray-400">
                          {m.submitted_at ? new Date(m.submitted_at).toLocaleDateString() : '-'}
                        </td>
                        <td className="px-4 py-2 text-xs text-gray-300">-</td>
                      </tr>
                    )
                  })}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
