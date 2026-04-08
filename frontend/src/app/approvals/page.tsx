'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useAuth } from '@/components/AuthContext'
import ApprovalStatusBadge from '@/components/ApprovalStatusBadge'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Approval {
  id: string
  combo_id: string
  combo_name: string | null
  combo_id_display: string | null
  round: number
  status: string
  submitter_name: string | null
  submitted_at: string | null
  deadline: string | null
  resolved_at: string | null
  reviewers: { reviewer_name: string; status: string }[]
}

export default function ApprovalsPage() {
  const { user } = useAuth()
  const [tab, setTab] = useState<'all' | 'pending'>('all')
  const [approvals, setApprovals] = useState<Approval[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState('')

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
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Approvals</h1>

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
              </tr>
            </thead>
            <tbody>
              {approvals.map(a => (
                <tr key={a.id} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <Link href={`/approvals/${a.id}`} className="text-sm font-medium text-blue-600 hover:text-blue-700">
                      {a.combo_name || a.combo_id_display || 'Unknown'}
                    </Link>
                  </td>
                  <td className="px-4 py-3"><ApprovalStatusBadge status={a.status} /></td>
                  <td className="px-4 py-3 text-sm text-gray-600">{a.submitter_name || '-'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{a.round}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {a.reviewers.filter(r => r.status === 'APPROVED').length}/{a.reviewers.length} approved
                  </td>
                  <td className="px-4 py-3 text-xs">
                    {a.deadline ? (
                      <span className={new Date(a.deadline) < new Date() && a.status === 'PENDING_APPROVAL' ? 'text-red-500 font-medium' : 'text-gray-500'}>
                        {new Date(a.deadline).toLocaleDateString()}
                        {new Date(a.deadline) < new Date() && a.status === 'PENDING_APPROVAL' && ' (!!)'}
                      </span>
                    ) : <span className="text-gray-300">-</span>}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {a.submitted_at ? new Date(a.submitted_at).toLocaleDateString() : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
