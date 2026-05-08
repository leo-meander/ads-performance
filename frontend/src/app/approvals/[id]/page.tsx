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
    feedback: string | null
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
    target_audience: string | null; country: string | null
    keypoint_ids: string[] | null; angle_id: string | null
  } | null
  branch: {
    id: string; name: string; platform: string; currency: string
  } | null
  angle: {
    angle_id: string; angle_type: string; angle_explain: string
    hook_examples: string[]; status: string
    branch_verdict: string; branch_benchmark: number
    combos: number; spend: number; revenue: number
    roas: number; conversions: number
  } | null
  keypoints: {
    id: string; title: string; category: string
    combos: number; spend: number; roas: number
    conversions: number; branch_verdict: string
  }[]
}

export default function ApprovalDetailPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const router = useRouter()
  const [approval, setApproval] = useState<ApprovalDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [deciding, setDeciding] = useState(false)
  const [feedback, setFeedback] = useState('')
  const [decisionError, setDecisionError] = useState('')
  const [resubmitting, setResubmitting] = useState(false)
  const [resubmitFile, setResubmitFile] = useState('')
  const [resubmitDeadline, setResubmitDeadline] = useState('')
  const [resubmitError, setResubmitError] = useState('')

  // Revise-while-pending state (creator-only edit panel)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editError, setEditError] = useState('')
  const [editFile, setEditFile] = useState('')
  const [editDeadline, setEditDeadline] = useState('')
  const [editAngleId, setEditAngleId] = useState('')
  const [editKeypointIds, setEditKeypointIds] = useState<string[]>([])
  const [editReviewerIds, setEditReviewerIds] = useState<string[]>([])
  const [editHeadline, setEditHeadline] = useState('')
  const [editBodyText, setEditBodyText] = useState('')
  const [editCta, setEditCta] = useState('')
  const [editLanguage, setEditLanguage] = useState('')
  const [editTargetAudience, setEditTargetAudience] = useState('')
  const [reviewerOptions, setReviewerOptions] = useState<{ id: string; full_name: string; email: string }[]>([])
  const [angleOptions, setAngleOptions] = useState<{ angle_id: string; angle_type: string; branch_id: string | null }[]>([])
  const [keypointOptions, setKeypointOptions] = useState<{ id: string; title: string; category: string; branch_id: string }[]>([])

  const fetchApproval = () => {
    fetch(`${API_BASE}/api/approvals/${id}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setApproval(data.data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchApproval() }, [id])

  const isCreatorPending =
    approval && user?.id === approval.submitted_by && approval.status === 'PENDING_APPROVAL'

  // Lazy-load reviewer/angle/keypoint options the first time the creator opens the edit panel
  useEffect(() => {
    if (!editOpen || !isCreatorPending) return
    if (reviewerOptions.length === 0) {
      fetch(`${API_BASE}/api/users/reviewers`, { credentials: 'include' })
        .then(r => r.json())
        .then(d => { if (d.success) setReviewerOptions(d.data.items || []) })
        .catch(() => {})
    }
    if (angleOptions.length === 0) {
      fetch(`${API_BASE}/api/angles`, { credentials: 'include' })
        .then(r => r.json())
        .then(d => { if (d.success) setAngleOptions(d.data || []) })
        .catch(() => {})
    }
    if (keypointOptions.length === 0) {
      fetch(`${API_BASE}/api/keypoints`, { credentials: 'include' })
        .then(r => r.json())
        .then(d => { if (d.success) setKeypointOptions(d.data || []) })
        .catch(() => {})
    }
  }, [editOpen, isCreatorPending, reviewerOptions.length, angleOptions.length, keypointOptions.length])

  // Seed the edit form whenever the panel opens (or the underlying approval reloads)
  useEffect(() => {
    if (!editOpen || !approval) return
    setEditFile(approval.working_file_url || '')
    setEditDeadline(approval.deadline ? approval.deadline.slice(0, 16) : '')
    setEditAngleId(approval.angle?.angle_id || '')
    setEditKeypointIds(approval.keypoints.map(k => k.id))
    setEditReviewerIds(approval.reviewers.map(r => r.reviewer_id))
    setEditHeadline(approval.copy?.headline || '')
    setEditBodyText(approval.copy?.body_text || '')
    setEditCta(approval.copy?.cta || '')
    setEditLanguage(approval.copy?.language || '')
    setEditTargetAudience(approval.copy?.target_audience || '')
    setEditError('')
  }, [editOpen, approval])

  const handleDecision = async (decision: string) => {
    const trimmed = feedback.trim()
    if (decision !== 'APPROVED' && !trimmed) {
      setDecisionError('Please leave feedback before requesting revision or rejecting.')
      return
    }
    setDecisionError('')
    setDeciding(true)
    try {
      const res = await fetch(`${API_BASE}/api/approvals/${id}/decide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ decision, feedback: trimmed || null }),
      })
      const data = await res.json()
      if (data.success) {
        setApproval(data.data)
        setFeedback('')
      } else {
        setDecisionError(data.error || 'Failed to submit decision')
      }
    } catch {
      setDecisionError('Network error')
    }
    setDeciding(false)
  }

  const handleRevise = async () => {
    if (editReviewerIds.length === 0) {
      setEditError('Pick at least one reviewer.')
      return
    }
    setEditing(true)
    setEditError('')
    try {
      const res = await fetch(`${API_BASE}/api/approvals/${id}/revise`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          working_file_url: editFile,
          deadline: editDeadline ? new Date(editDeadline).toISOString() : '',
          angle_id: editAngleId,
          keypoint_ids: editKeypointIds,
          reviewer_ids: editReviewerIds,
          headline: editHeadline,
          body_text: editBodyText,
          cta: editCta,
          language: editLanguage,
          target_audience: editTargetAudience,
        }),
      })
      const data = await res.json()
      if (data.success) {
        setApproval(data.data)
        setEditOpen(false)
      } else {
        setEditError(data.error || 'Revise failed')
      }
    } catch {
      setEditError('Network error')
    }
    setEditing(false)
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
              {approval.branch && (
                <div><span className="text-gray-500">Branch:</span> <span className="text-gray-900">{approval.branch.name}</span></div>
              )}
              {approval.performance?.country && (
                <div><span className="text-gray-500">Country:</span> <span className="text-gray-900">{approval.performance.country}</span></div>
              )}
              {approval.performance?.target_audience && (
                <div><span className="text-gray-500">Target Audience:</span> <span className="text-gray-900">{approval.performance.target_audience}</span></div>
              )}
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

          {/* Angle context */}
          {approval.angle && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-center gap-2 mb-1">
                <h3 className="text-sm font-semibold text-gray-900">Angle</h3>
                <span className="font-mono text-xs text-gray-400">{approval.angle.angle_id}</span>
                <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                  approval.angle.branch_verdict === 'WIN' ? 'bg-green-100 text-green-700' :
                  approval.angle.branch_verdict === 'LOSE' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
                }`}>{approval.angle.branch_verdict}</span>
                {approval.branch && (
                  <span className="text-xs text-gray-400">on {approval.branch.name}</span>
                )}
              </div>
              <p className="text-xs text-gray-500 italic mb-2">
                The angle is the strategic approach this content takes.
              </p>
              {approval.angle.angle_type && (
                <p className="text-sm font-semibold text-gray-900">{approval.angle.angle_type}</p>
              )}
              {approval.angle.hook_examples && approval.angle.hook_examples.length > 0 && (
                <p className="text-sm text-gray-700 mt-1">
                  <span className="text-gray-500">Example:</span> {approval.angle.hook_examples[0]}
                </p>
              )}
              <div className="grid grid-cols-4 gap-3 mt-3">
                {[
                  { label: 'ROAS (branch)', value: `${approval.angle.roas.toFixed(2)}x` },
                  { label: 'Benchmark', value: approval.angle.branch_benchmark > 0 ? `${approval.angle.branch_benchmark.toFixed(2)}x` : '–' },
                  { label: 'Spend', value: approval.angle.spend.toLocaleString() },
                  { label: 'Conversions', value: approval.angle.conversions },
                  { label: 'Combos', value: approval.angle.combos },
                ].map(m => (
                  <div key={m.label} className="bg-gray-50 rounded-lg p-2.5">
                    <p className="text-[10px] text-gray-500 uppercase">{m.label}</p>
                    <p className="text-sm font-bold text-gray-900">{m.value}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Keypoints */}
          {approval.keypoints && approval.keypoints.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <h3 className="text-sm font-semibold text-gray-900 mb-1">Keypoints</h3>
              <p className="text-xs text-gray-500 italic mb-3">
                The specific selling points this content leans on.
              </p>
              <ul className="space-y-2">
                {approval.keypoints.map(k => (
                  <li key={k.id} className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 flex items-center justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span className="text-[10px] uppercase text-gray-500">{k.category}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                          k.branch_verdict === 'WIN' ? 'bg-green-100 text-green-700' :
                          k.branch_verdict === 'LOSE' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
                        }`}>{k.branch_verdict}</span>
                      </div>
                      <p className="text-sm text-gray-900 font-medium truncate">{k.title}</p>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-gray-700 shrink-0">
                      <div className="text-right">
                        <p className="text-[10px] text-gray-500 uppercase">ROAS</p>
                        <p className="text-sm font-bold">{k.roas.toFixed(2)}x</p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] text-gray-500 uppercase">Conv</p>
                        <p className="text-sm font-bold">{k.conversions}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] text-gray-500 uppercase">Combos</p>
                        <p className="text-sm font-bold">{k.combos}</p>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

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

              {/* Reviewers feedback on the ad copy */}
              <div className="mt-4 pt-3 border-t border-gray-100">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">
                  Reviewers feedback
                </h4>
                {approval.reviewers.filter(r => r.feedback && r.feedback.trim()).length === 0 ? (
                  <p className="text-xs text-gray-400 italic">No feedback yet.</p>
                ) : (
                  <ul className="space-y-2">
                    {approval.reviewers
                      .filter(r => r.feedback && r.feedback.trim())
                      .map(r => (
                        <li key={r.id} className="bg-gray-50 rounded-lg p-3">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-sm font-medium text-gray-900">{r.reviewer_name}</span>
                            <span className={`text-[11px] px-1.5 py-0.5 rounded font-medium ${
                              r.status === 'APPROVED' ? 'bg-green-100 text-green-700' :
                              r.status === 'REJECTED' ? 'bg-red-100 text-red-700' :
                              r.status === 'NEEDS_REVISION' ? 'bg-orange-100 text-orange-700' :
                              'bg-amber-100 text-amber-700'
                            }`}>{r.status}</span>
                            {r.decided_at && (
                              <span className="text-[11px] text-gray-400">
                                {new Date(r.decided_at).toLocaleString()}
                              </span>
                            )}
                          </div>
                          <p className="text-sm text-gray-700 whitespace-pre-line">{r.feedback}</p>
                        </li>
                      ))}
                  </ul>
                )}
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
              <div className="mb-3">
                <label className="block text-xs text-gray-600 mb-1">
                  Feedback for ad copy
                  <span className="text-gray-400 font-normal"> (required for Needs Revision / Reject)</span>
                </label>
                <textarea
                  value={feedback}
                  onChange={e => setFeedback(e.target.value)}
                  placeholder="What works, what to change, suggested rewrites…"
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

          {/* Creator: edit while pending — bumps round, resets reviewers */}
          {isCreatorPending && (
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
              <div className="flex items-center justify-between mb-1">
                <h3 className="text-sm font-semibold text-blue-900">Edit while pending</h3>
                <button
                  onClick={() => setEditOpen(o => !o)}
                  className="text-xs font-medium text-blue-700 hover:text-blue-800"
                >
                  {editOpen ? 'Cancel' : 'Edit →'}
                </button>
              </div>
              <p className="text-xs text-blue-700">
                Apply quick fixes (verbal feedback). Saving bumps to round {approval.round + 1} and asks all reviewers to re-review.
              </p>

              {editOpen && (
                <div className="mt-4 space-y-3">
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">Working file URL</label>
                    <input
                      type="url"
                      value={editFile}
                      onChange={e => setEditFile(e.target.value)}
                      placeholder="https://canva.com/design/..."
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">Deadline</label>
                    <input
                      type="datetime-local"
                      value={editDeadline}
                      onChange={e => setEditDeadline(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    />
                  </div>
                  <div className="bg-white border border-gray-200 rounded-lg p-3 space-y-2">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                      Ad copy {approval.copy_id ? <span className="font-mono normal-case font-normal text-gray-400">({approval.copy_id})</span> : null}
                    </p>
                    <div>
                      <label className="block text-xs text-gray-600 mb-1">Headline</label>
                      <input
                        type="text"
                        value={editHeadline}
                        onChange={e => setEditHeadline(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-600 mb-1">Body</label>
                      <textarea
                        value={editBodyText}
                        onChange={e => setEditBodyText(e.target.value)}
                        rows={5}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
                      />
                    </div>
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <label className="block text-xs text-gray-600 mb-1">CTA</label>
                        <input
                          type="text"
                          value={editCta}
                          onChange={e => setEditCta(e.target.value)}
                          placeholder="Book Now"
                          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-gray-600 mb-1">Language</label>
                        <select
                          value={editLanguage}
                          onChange={e => setEditLanguage(e.target.value)}
                          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                          <option value="en">English</option>
                          <option value="vi">Vietnamese</option>
                          <option value="zh">Chinese</option>
                          <option value="ja">Japanese</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs text-gray-600 mb-1">Target audience</label>
                        <select
                          value={editTargetAudience}
                          onChange={e => setEditTargetAudience(e.target.value)}
                          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                        >
                          <option value="Solo">Solo</option>
                          <option value="Couple">Couple</option>
                          <option value="Friend">Friend</option>
                          <option value="Group">Group</option>
                          <option value="Family">Family</option>
                          <option value="Business">Business</option>
                          <option value="Re-target">Re-target</option>
                        </select>
                      </div>
                    </div>
                    <p className="text-[10px] text-gray-400 italic">
                      If this copy is shared with other combos, a new copy_id is auto-cloned so the change doesn't leak.
                    </p>
                  </div>

                  <div>
                    <label className="block text-xs text-gray-600 mb-1">Angle</label>
                    <select
                      value={editAngleId}
                      onChange={e => setEditAngleId(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    >
                      <option value="">— No angle —</option>
                      {angleOptions
                        .filter(a => !a.branch_id || a.branch_id === approval.branch?.id)
                        .map(a => (
                          <option key={a.angle_id} value={a.angle_id}>
                            {a.angle_id} — {a.angle_type}
                          </option>
                        ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">
                      Keypoints <span className="text-gray-400 font-normal">(click to toggle)</span>
                    </label>
                    <div className="flex flex-wrap gap-1.5">
                      {keypointOptions
                        .filter(k => k.branch_id === approval.branch?.id)
                        .map(k => {
                          const on = editKeypointIds.includes(k.id)
                          return (
                            <button
                              key={k.id}
                              type="button"
                              onClick={() => setEditKeypointIds(prev =>
                                on ? prev.filter(x => x !== k.id) : [...prev, k.id]
                              )}
                              className={`text-xs px-2 py-1 rounded-full border ${
                                on ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300 hover:border-blue-400'
                              }`}
                            >
                              {k.title}
                            </button>
                          )
                        })}
                      {keypointOptions.filter(k => k.branch_id === approval.branch?.id).length === 0 && (
                        <span className="text-xs text-gray-400 italic">No keypoints for this branch.</span>
                      )}
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">
                      Reviewers <span className="text-gray-400 font-normal">(at least one)</span>
                    </label>
                    <div className="flex flex-wrap gap-1.5">
                      {reviewerOptions.map(r => {
                        const on = editReviewerIds.includes(r.id)
                        return (
                          <button
                            key={r.id}
                            type="button"
                            onClick={() => setEditReviewerIds(prev =>
                              on ? prev.filter(x => x !== r.id) : [...prev, r.id]
                            )}
                            className={`text-xs px-2 py-1 rounded-full border ${
                              on ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300 hover:border-blue-400'
                            }`}
                          >
                            {r.full_name}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                  {editError && (
                    <div className="bg-red-50 text-red-700 px-3 py-2 rounded-lg text-xs">{editError}</div>
                  )}
                  <button
                    onClick={handleRevise}
                    disabled={editing}
                    className="bg-blue-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
                  >
                    {editing ? 'Saving…' : `Save & re-notify (round ${approval.round + 1})`}
                  </button>
                </div>
              )}
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
