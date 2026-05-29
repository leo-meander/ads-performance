'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Plus, Send, Layers } from 'lucide-react'
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

// A row in the rendered table: either a single standalone approval, or a
// batch aggregating N child approvals into one all-or-nothing review.
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
      rows.push({ kind: 'single', key: a.id, members: [a] })
    }
  }
  return rows
}

export default function ApprovalsPage() {
  const { user } = useAuth()
  const [tab, setTab] = useState<'all' | 'pending'>('all')
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('')
  const [resending, setResending] = useState<string | null>(null)

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

  useEffect(() => {
    setLoading(true)
    const endpoint = tab === 'pending' ? '/api/approvals/pending' : '/api/approvals'
    const params = new URLSearchParams()
    if (statusFilter && tab === 'all') params.set('status', statusFilter)

    fetch(`${API_BASE}${endpoint}?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setApprovals(data.data.items || []) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [tab, statusFilter])

  const isReviewer = user?.roles?.includes('reviewer') || user?.roles?.includes('admin')

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Approvals</h1>
        <Link href="/creative/submit" className="inline-flex items-center gap-1.5 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700">
          <Plus className="w-4 h-4" /> New Approval
        </Link>
      </div>

      <div className="flex items-center gap-4 mb-4">
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

        {tab === 'all' && (
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm"
          >
            <option value="">All Status</option>
            <option value="PENDING_APPROVAL">Pending</option>
            <option value="NEEDS_REVISION">Needs Revision</option>
            <option value="APPROVED">Approved</option>
            <option value="REJECTED">Rejected</option>
            <option value="LAUNCHED">Launched</option>
          </select>
        )}
      </div>

      {loading ? (
        <p className="text-gray-500">Loading...</p>
      ) : approvals.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
          No approvals found.
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
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Date</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Action</th>
              </tr>
            </thead>
            <tbody>
              {groupRows(approvals).map(row => {
                const head = row.members[0]
                const isBatch = row.kind === 'batch'
                const status = isBatch ? rollupStatus(row.members.map(m => m.status)) : head.status
                const href = isBatch ? `/approvals/batch/${row.key}` : `/approvals/${head.id}`
                // Reviewers are identical across batch members, so the head row's are representative.
                const approvedReviewers = head.reviewers.filter(r => r.status === 'APPROVED').length
                const overdue = head.deadline ? new Date(head.deadline) < new Date() && status === 'PENDING_APPROVAL' : false
                return (
                  <tr key={row.key} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-4 py-3">
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
                    </td>
                    <td className="px-4 py-3"><ApprovalStatusBadge status={status} /></td>
                    <td className="px-4 py-3 text-sm text-gray-600">{head.submitter_name || '-'}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{head.round}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">
                      {approvedReviewers}/{head.reviewers.length} approved
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {head.deadline ? (
                        <span className={overdue ? 'text-red-500 font-medium' : 'text-gray-500'}>
                          {new Date(head.deadline).toLocaleDateString()}
                          {overdue && ' (!!)'}
                        </span>
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
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
