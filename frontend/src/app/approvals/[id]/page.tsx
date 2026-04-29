'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useAuth } from '@/components/AuthContext'
import ApprovalStatusBadge from '@/components/ApprovalStatusBadge'
import ReviewerStatusList from '@/components/ReviewerStatusList'
import WorkingFileLinkCard from '@/components/WorkingFileLinkCard'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface ApprovalDetail {
  id: string
  combo_id: string
  combo_name: string | null
  combo_id_display: string | null
  material_id: string | null
  copy_id: string | null
  round: number
  status: string
  submitted_by: string
  submitter_name: string | null
  submitted_at: string | null
  deadline: string | null
  resolved_at: string | null
  working_file_url: string | null
  working_file_label: string | null
  launch_status: string | null
  launch_meta_ad_id: string | null
  launched_at: string | null
  reviewers: {
    id: string
    reviewer_id: string
    reviewer_name: string
    status: string
    decided_at: string | null
  }[]
  copy: {
    copy_id: string; headline: string; body_text: string; cta: string | null
    language: string; target_audience: string; derived_verdict: string | null
  } | null
  material: {
    material_id: string; material_type: string; file_url: string
    description: string | null; derived_verdict: string | null
  } | null
  performance: {
    verdict: string; spend: number | null; impressions: number | null
    clicks: number | null; conversions: number | null; revenue: number | null
    roas: number | null; ctr: number | null; hook_rate: number | null
    thruplay_rate: number | null; engagement_rate: number | null
    target_audience: string | null; keypoint_ids: string[] | null; angle_id: string | null
  } | null
}

export default function ApprovalDetailPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const router = useRouter()
  const [approval, setApproval] = useState<ApprovalDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [deciding, setDeciding] = useState(false)
  const [resubmitting, setResubmitting] = useState(false)
  const [resubmitFile, setResubmitFile] = useState('')
  const [resubmitDeadline, setResubmitDeadline] = useState('')
  const [resubmitError, setResubmitError] = useState('')

  const fetchApproval = () => {
    fetch(`${API_BASE}/api/approvals/${id}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setApproval(data.data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchApproval() }, [id])

  const handleDecision = async (decision: string) => {
    setDeciding(true)
    try {
      const res = await fetch(`${API_BASE}/api/approvals/${id}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ decision }),
      })
      const data = await res.json()
      if (data.success) setApproval(data.data)
    } catch {}
    setDeciding(false)
  }

  const handleResubmit = async () => {
    setResubmitting(true)
    setResubmitError('')
    try {
      const res = await fetch(`${API_BASE}/api/approvals/${id}/resubmit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          working_file_url: resubmitFile || null,
          deadline: resubmitDeadline ? new Date(resubmitDeadline).toISOString() : null,
        }),
      })
      const data = await res.json()
      if (data.success) {
        router.push(`/approvals/${data.data.id}`)
      } else {
        setResubmitError(data.error || 'Resubmit failed')
      }
    } catch {
      setResubmitError('Network error')
    }
    setResubmitting(false)
  }

  if (loading) return <p className="text-gray-500">Loading...</p>
  if (!approval) return <p className="text-red-500">Approval not found</p>

  const isCreator = user?.id === approval.submitted_by
  const isAssignedReviewer = approval.reviewers.some(
    r => r.reviewer_id === user?.id && r.status === 'PENDING'
  )
  const canLaunch = isCreator && approval.status === 'APPROVED' && !approval.launch_status

  return (
    <div>
      <button onClick={() => router.push('/approvals')} className="text-sm text-blue-600 hover:text-blue-700 mb-4">
        &larr; Back to Approvals
      </button>

      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-2xl font-bold text-gray-900">
          {approval.combo_name || approval.combo_id_display || 'Combo'}
        </h1>
        <ApprovalStatusBadge status={approval.status} />
        {approval.launch_status && <ApprovalStatusBadge status={approval.launch_status} />}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Main content */}
        <div className="lg:col-span-2 space-y-4">
          {/* Combo info */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">Combo Details</h3>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div><span className="text-gray-500">Combo ID:</span> <span className="text-gray-900">{approval.combo_id_display}</span></div>
              <div><span className="text-gray-500">Round:</span> <span className="text-gray-900">{approval.round}</span></div>
              <div><span className="text-gray-500">Submitted by:</span> <span className="text-gray-900">{approval.submitter_name}</span></div>
              <div><span className="text-gray-500">Submitted:</span> <span className="text-gray-900">{approval.submitted_at ? new Date(approval.submitted_at).toLocaleString() : '-'}</span></div>
              {approval.deadline && (
                <div>
                  <span className="text-gray-500">Deadline:</span>{' '}
                  <span className={`font-medium ${new Date(approval.deadline) < new Date() && approval.status === 'PENDING_APPROVAL' ? 'text-red-600' : 'text-gray-900'}`}>
                    {new Date(approval.deadline).toLocaleString()}
                    {new Date(approval.deadline) < new Date() && approval.status === 'PENDING_APPROVAL' && ' (overdue)'}
                  </span>
                </div>
              )}
              {approval.material_id && <div><span className="text-gray-500">Material:</span> <span className="text-gray-900">{approval.material_id}</span></div>}
              {approval.copy_id && <div><span className="text-gray-500">Copy:</span> <span className="text-gray-900">{approval.copy_id}</span></div>}
              {approval.launch_meta_ad_id && <div><span className="text-gray-500">Meta Ad ID:</span> <span className="text-gray-900">{approval.launch_meta_ad_id}</span></div>}
            </div>
          </div>

          {/* Ad Copy */}
          {approval.copy && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-center gap-2 mb-3">
                <h3 className="text-sm font-semibold text-gray-900">Ad Copy</h3>
                <span className="font-mono text-xs text-gray-400">{approval.copy.copy_id}</span>
                {approval.copy.derived_verdict && (
                  <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                    approval.copy.derived_verdict === 'WIN' ? 'bg-green-100 text-green-700' :
                    approval.copy.derived_verdict === 'LOSE' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
                  }`}>{approval.copy.derived_verdict}</span>
                )}
              </div>
              <p className="text-sm font-semibold text-gray-900">{approval.copy.headline}</p>
              <p className="text-sm text-gray-600 mt-1 whitespace-pre-line">{approval.copy.body_text}</p>
              {approval.copy.cta && <p className="text-sm text-blue-600 mt-2 font-medium">{approval.copy.cta}</p>}
              <div className="flex gap-3 mt-2 text-xs text-gray-400">
                <span>{approval.copy.language}</span>
                <span>{approval.copy.target_audience}</span>
              </div>
            </div>
          )}

          {/* Material */}
          {approval.material && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-center gap-2 mb-3">
                <h3 className="text-sm font-semibold text-gray-900">Creative Material</h3>
                <span className="font-mono text-xs text-gray-400">{approval.material.material_id}</span>
                <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100">{approval.material.material_type}</span>
                {approval.material.derived_verdict && (
                  <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                    approval.material.derived_verdict === 'WIN' ? 'bg-green-100 text-green-700' :
                    approval.material.derived_verdict === 'LOSE' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
                  }`}>{approval.material.derived_verdict}</span>
                )}
              </div>
              {approval.material.description && <p className="text-sm text-gray-600 mb-2">{approval.material.description}</p>}
              <a href={approval.material.file_url} target="_blank" rel="noopener noreferrer"
                className="inline-block bg-gray-100 text-gray-800 px-3 py-1.5 rounded-lg text-sm hover:bg-gray-200">
                View Creative &rarr;
              </a>
            </div>
          )}

          {/* Performance Data */}
          {approval.performance && (approval.performance.spend || approval.performance.impressions) && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-center gap-2 mb-3">
                <h3 className="text-sm font-semibold text-gray-900">Performance Data</h3>
                <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                  approval.performance.verdict === 'WIN' ? 'bg-green-100 text-green-700' :
                  approval.performance.verdict === 'LOSE' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
                }`}>{approval.performance.verdict}</span>
              </div>
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'Spend', value: approval.performance.spend != null ? `${approval.performance.spend.toLocaleString()}` : null },
                  { label: 'ROAS', value: approval.performance.roas != null ? `${approval.performance.roas.toFixed(2)}x` : null },
                  { label: 'Conversions', value: approval.performance.conversions },
                  { label: 'CTR', value: approval.performance.ctr != null ? `${(approval.performance.ctr * 100).toFixed(2)}%` : null },
                  { label: 'Hook Rate', value: approval.performance.hook_rate != null ? `${(approval.performance.hook_rate * 100).toFixed(1)}%` : null },
                  { label: 'Thruplay Rate', value: approval.performance.thruplay_rate != null ? `${(approval.performance.thruplay_rate * 100).toFixed(1)}%` : null },
                ].filter(m => m.value != null).map(m => (
                  <div key={m.label} className="bg-gray-50 rounded-lg p-2.5">
                    <p className="text-[10px] text-gray-500 uppercase">{m.label}</p>
                    <p className="text-sm font-bold text-gray-900">{m.value}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Action buttons */}
          {isAssignedReviewer && approval.status === 'PENDING_APPROVAL' && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <h3 className="text-sm font-semibold text-gray-900 mb-3">Your Decision</h3>
              <div className="flex flex-wrap gap-3">
                <button
                  onClick={() => handleDecision('APPROVED')}
                  disabled={deciding}
                  className="bg-green-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
                >
                  {deciding ? 'Submitting...' : 'Approve'}
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
                  {deciding ? 'Submitting...' : 'Reject'}
                </button>
              </div>
              <p className="text-xs text-gray-400 mt-2">
                Approve = ready to launch. Needs Revision = creator can fix and resubmit. Reject = combo dead.
              </p>
            </div>
          )}

          {/* Creator: revise & resubmit panel */}
          {isCreator && approval.status === 'NEEDS_REVISION' && (
            <div className="bg-orange-50 border border-orange-200 rounded-xl p-4">
              <h3 className="text-sm font-semibold text-orange-900 mb-1">Revise & Resubmit</h3>
              <p className="text-xs text-orange-700 mb-3">
                Update the working file with your changes, then submit a new round to the same reviewers.
              </p>
              {resubmitError && (
                <div className="bg-red-50 text-red-700 px-3 py-2 rounded-lg text-xs mb-3">{resubmitError}</div>
              )}
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-gray-600 mb-1">New working file URL (optional)</label>
                  <input
                    type="url"
                    value={resubmitFile}
                    onChange={e => setResubmitFile(e.target.value)}
                    placeholder={approval.working_file_url || 'https://canva.com/design/...'}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
                  />
                  <p className="text-[11px] text-gray-400 mt-1">Leave empty to reuse the previous file.</p>
                </div>
                <div>
                  <label className="block text-xs text-gray-600 mb-1">New deadline (optional)</label>
                  <input
                    type="datetime-local"
                    value={resubmitDeadline}
                    onChange={e => setResubmitDeadline(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
                  />
                </div>
                <button
                  onClick={handleResubmit}
                  disabled={resubmitting}
                  className="bg-orange-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-orange-700 disabled:opacity-50"
                >
                  {resubmitting ? 'Submitting...' : 'Submit New Round'}
                </button>
              </div>
            </div>
          )}

          {canLaunch && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <h3 className="text-sm font-semibold text-gray-900 mb-3">Launch to Meta Ads</h3>
              <button
                onClick={() => router.push(`/approvals/${id}/launch`)}
                className="bg-blue-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-blue-700"
              >
                Launch Ad
              </button>
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          <ReviewerStatusList reviewers={approval.reviewers} />
          <WorkingFileLinkCard url={approval.working_file_url} label={approval.working_file_label} />
        </div>
      </div>
    </div>
  )
}
