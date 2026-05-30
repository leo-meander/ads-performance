'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/components/AuthContext'
import ApprovalStatusBadge from '@/components/ApprovalStatusBadge'
import ReviewerStatusList from '@/components/ReviewerStatusList'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Reviewer {
  id: string
  reviewer_id: string
  reviewer_name: string
  status: string
  decided_at: string | null
  feedback: string | null
}

interface Version {
  id: string
  combo_id: string
  combo_name: string | null
  combo_id_display: string | null
  status: string
  working_file_url: string | null
  working_file_label: string | null
  copy: {
    copy_id: string; headline: string; body_text: string; cta: string | null
    language: string; target_audience: string
  } | null
  material: {
    material_id: string; material_type: string; file_url: string; description: string | null
  } | null
  angle: { angle_id: string; angle_type: string } | null
  branch: { id: string; name: string } | null
  reviewers: Reviewer[]
}

interface BatchDetail {
  id: string
  round: number
  status: string
  submitted_by: string
  submitter_name: string | null
  submitted_at: string | null
  deadline: string | null
  note: string | null
  reviewers: Reviewer[]
  versions: Version[]
}

export default function BatchDetailPage() {
  const { batchId } = useParams()
  const { user } = useAuth()
  const router = useRouter()
  const [batch, setBatch] = useState<BatchDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [deciding, setDeciding] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [decisionError, setDecisionError] = useState('')

  const fetchBatch = () => {
    fetch(`${API_BASE}/api/approval-batches/${batchId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setBatch(data.data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchBatch() }, [batchId])

  const handleDecision = async (decision: string) => {
    const trimmed = feedback.trim()
    if (decision !== 'APPROVED' && !trimmed) {
      setDecisionError('Please leave feedback before requesting revision or rejecting.')
      return
    }
    setDecisionError('')
    setDeciding(true)
    try {
      const res = await fetch(`${API_BASE}/api/approval-batches/${batchId}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ decision, feedback: trimmed || null }),
      })
      const data = await res.json()
      if (data.success) {
        setBatch(data.data)
        setFeedback('')
      } else {
        setDecisionError(data.error || 'Failed to submit decision')
      }
    } catch {
      setDecisionError('Network error')
    }
    setDeciding(false)
  }

  if (loading) return <p className="text-gray-500">Loading...</p>
  if (!batch) return <p className="text-red-500">Batch not found</p>

  const isAssignedReviewer = batch.reviewers.some(
    r => r.reviewer_id === user?.id && r.status === 'PENDING'
  )
  const overdue = batch.deadline ? new Date(batch.deadline) < new Date() && batch.status === 'PENDING_APPROVAL' : false

  return (
    <div>
      <button onClick={() => router.push('/approvals')} className="text-sm text-blue-600 hover:text-blue-700 mb-4">
        &larr; Back to Approvals
      </button>

      <div className="flex items-center gap-3 mb-1">
        <h1 className="text-2xl font-bold text-gray-900">
          Batch — {batch.versions.length} version{batch.versions.length !== 1 ? 's' : ''}
        </h1>
        <ApprovalStatusBadge status={batch.status} />
      </div>
      <p className="text-sm text-gray-500 mb-6">
        All-or-nothing review: a single decision applies to every version below.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Main content */}
        <div className="lg:col-span-2 space-y-4">
          {/* Batch metadata */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Submission</h3>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div><span className="text-gray-500">Round:</span> <span className="text-gray-900">{batch.round}</span></div>
              <div><span className="text-gray-500">Versions:</span> <span className="text-gray-900">{batch.versions.length}</span></div>
              <div><span className="text-gray-500">Submitted by:</span> <span className="text-gray-900">{batch.submitter_name || '-'}</span></div>
              <div><span className="text-gray-500">Submitted:</span> <span className="text-gray-900">{batch.submitted_at ? new Date(batch.submitted_at).toLocaleString() : '-'}</span></div>
              {batch.deadline && (
                <div>
                  <span className="text-gray-500">Deadline:</span>{' '}
                  <span className={`font-medium ${overdue ? 'text-red-600' : 'text-gray-900'}`}>
                    {new Date(batch.deadline).toLocaleString()}{overdue && ' (overdue)'}
                  </span>
                </div>
              )}
            </div>
            {batch.note && (
              <div className="mt-3 pt-3 border-t border-gray-100">
                <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1">Note from Submitter</p>
                <p className="text-sm text-gray-700 whitespace-pre-line">{batch.note}</p>
              </div>
            )}
          </div>

          {/* Versions */}
          {batch.versions.map((v, i) => (
            <div key={v.id} className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-center gap-2 mb-3">
                <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-100 text-blue-700 text-xs font-bold">
                  {i + 1}
                </span>
                <h3 className="text-sm font-semibold text-gray-900">
                  {v.combo_name || v.combo_id_display || 'Version'}
                </h3>
                <span className="font-mono text-xs text-gray-400">{v.combo_id_display}</span>
                <ApprovalStatusBadge status={v.status} />
              </div>

              {v.copy && (
                <div className="mb-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Ad Copy</span>
                    <span className="font-mono text-xs text-gray-400">{v.copy.copy_id}</span>
                  </div>
                  <p className="text-sm text-gray-600 whitespace-pre-line">{v.copy.body_text}</p>
                  {v.copy.cta && <p className="text-sm text-blue-600 mt-1 font-medium">{v.copy.cta}</p>}
                  <p className="text-sm font-semibold text-gray-900 mt-1">{v.copy.headline}</p>
                  <div className="flex gap-3 mt-1 text-xs text-gray-400">
                    <span>{v.copy.language}</span>
                    <span>{v.copy.target_audience}</span>
                  </div>
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2">
                {v.angle && (
                  <span className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-700">
                    Angle: {v.angle.angle_type}
                  </span>
                )}
                {v.material && (
                  <a href={v.material.file_url} target="_blank" rel="noopener noreferrer"
                    className="inline-block bg-gray-100 text-gray-800 px-3 py-1 rounded-lg text-xs hover:bg-gray-200">
                    View Creative &rarr;
                  </a>
                )}
                {v.working_file_url && (
                  <a href={v.working_file_url} target="_blank" rel="noopener noreferrer"
                    className="inline-block bg-gray-100 text-gray-800 px-3 py-1 rounded-lg text-xs hover:bg-gray-200">
                    {v.working_file_label || 'Working file'} &rarr;
                  </a>
                )}
              </div>
            </div>
          ))}

          {/* Reviewer decision — one control for the whole batch */}
          {isAssignedReviewer && batch.status === 'PENDING_APPROVAL' && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <h3 className="text-sm font-semibold text-gray-900 mb-1">Your Decision</h3>
              <p className="text-xs text-gray-500 mb-3">
                This decision applies to all {batch.versions.length} versions at once.
              </p>
              <div className="mb-3">
                <label className="block text-xs text-gray-600 mb-1">
                  Feedback
                  <span className="text-gray-400 font-normal"> (required for Needs Revision / Reject)</span>
                </label>
                <textarea
                  value={feedback}
                  onChange={e => setFeedback(e.target.value)}
                  placeholder="What works, what to change across these versions…"
                  rows={4}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              {decisionError && (
                <div className="bg-red-50 text-red-700 px-3 py-2 rounded-lg text-xs mb-3">{decisionError}</div>
              )}
              <div className="flex flex-wrap gap-3">
                <button
                  onClick={() => handleDecision('APPROVED')}
                  disabled={deciding}
                  className="bg-green-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                >
                  {deciding ? 'Submitting...' : 'Approve all'}
                </button>
                <button
                  onClick={() => handleDecision('NEEDS_REVISION')}
                  disabled={deciding}
                  className="bg-orange-500 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-orange-600 disabled:opacity-50"
                >
                  {deciding ? 'Submitting...' : 'Needs Revision'}
                </button>
                <button
                  onClick={() => handleDecision('REJECTED')}
                  disabled={deciding}
                  className="bg-red-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50"
                >
                  {deciding ? 'Submitting...' : 'Reject all'}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          <ReviewerStatusList reviewers={batch.reviewers} />

          {/* Working files — one entry per version */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Working Files</h3>
            {batch.versions.some(v => v.working_file_url) ? (
              <div className="space-y-3">
                {batch.versions.map((v, i) => (
                  <div key={v.id} className={i > 0 ? 'pt-3 border-t border-gray-100' : ''}>
                    <div className="flex items-center gap-2 mb-1">
                      <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-100 text-blue-700 text-[11px] font-bold">
                        {i + 1}
                      </span>
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {v.working_file_label || v.combo_name || v.combo_id_display || `Version ${i + 1}`}
                      </p>
                    </div>
                    {v.working_file_url ? (
                      <>
                        <p className="text-xs text-gray-400 break-all mb-2">{v.working_file_url}</p>
                        <a
                          href={v.working_file_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-block bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700"
                          title={v.working_file_url}
                        >
                          Open Working File →
                        </a>
                      </>
                    ) : (
                      <p className="text-xs text-gray-400">No working file linked</p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-400">No working file linked</p>
            )}
            <p className="text-[11px] text-gray-400 mt-3">
              If you have feedback, please make changes directly on these files.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
