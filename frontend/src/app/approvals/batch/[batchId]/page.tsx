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
  branch: { id: string; name: string } | null
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

const verdictClass = (v: string) =>
  v === 'WIN' ? 'bg-green-100 text-green-700' :
  v === 'LOSE' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'

// Per-version draft held by the edit panel.
interface VersionDraft {
  file: string
  headline: string
  body: string
  cta: string
  language: string
  ta: string
  angleId: string
  keypointIds: string[]
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

  // Revise-while-pending state (creator-only edit panel)
  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editError, setEditError] = useState('')
  const [editDeadline, setEditDeadline] = useState('')
  const [editReviewerIds, setEditReviewerIds] = useState<string[]>([])
  const [editVersions, setEditVersions] = useState<Record<string, VersionDraft>>({})
  const [reviewerOptions, setReviewerOptions] = useState<{ id: string; full_name: string; email: string }[]>([])
  const [angleOptions, setAngleOptions] = useState<{ angle_id: string; angle_type: string; branch_id: string | null }[]>([])
  const [keypointOptions, setKeypointOptions] = useState<{ id: string; title: string; category: string; branch_id: string }[]>([])

  const fetchBatch = () => {
    fetch(`${API_BASE}/api/approval-batches/${batchId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setBatch(data.data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchBatch() }, [batchId])

  const isCreatorPending =
    !!batch && user?.id === batch.submitted_by && batch.status === 'PENDING_APPROVAL'

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

  // Seed the edit form whenever the panel opens (or the batch reloads)
  useEffect(() => {
    if (!editOpen || !batch) return
    setEditDeadline(batch.deadline ? batch.deadline.slice(0, 16) : '')
    setEditReviewerIds(batch.reviewers.map(r => r.reviewer_id))
    const drafts: Record<string, VersionDraft> = {}
    for (const v of batch.versions) {
      drafts[v.id] = {
        file: v.working_file_url || '',
        headline: v.copy?.headline || '',
        body: v.copy?.body_text || '',
        cta: v.copy?.cta || '',
        language: v.copy?.language || '',
        ta: v.copy?.target_audience || '',
        angleId: v.angle?.angle_id || '',
        keypointIds: v.keypoints.map(k => k.id),
      }
    }
    setEditVersions(drafts)
    setEditError('')
  }, [editOpen, batch])

  const patchDraft = (vid: string, patch: Partial<VersionDraft>) =>
    setEditVersions(prev => ({ ...prev, [vid]: { ...prev[vid], ...patch } }))

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

  const handleRevise = async () => {
    if (!batch) return
    if (editReviewerIds.length === 0) {
      setEditError('Pick at least one reviewer.')
      return
    }
    setEditing(true)
    setEditError('')
    try {
      const res = await fetch(`${API_BASE}/api/approval-batches/${batchId}/revise`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          deadline: editDeadline ? new Date(editDeadline).toISOString() : '',
          reviewer_ids: editReviewerIds,
          versions: batch.versions.map(v => {
            const e = editVersions[v.id]
            return {
              approval_id: v.id,
              working_file_url: e.file,
              headline: e.headline,
              body_text: e.body,
              cta: e.cta,
              language: e.language,
              target_audience: e.ta,
              angle_id: e.angleId,
              keypoint_ids: e.keypointIds,
            }
          }),
        }),
      })
      const data = await res.json()
      if (data.success) {
        setBatch(data.data)
        setEditOpen(false)
      } else {
        setEditError(data.error || 'Revise failed')
      }
    } catch {
      setEditError('Network error')
    }
    setEditing(false)
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

              {/* Angle context + ROAS */}
              {v.angle && (
                <div className="mb-3 bg-gray-50 border border-gray-200 rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">Angle</span>
                    <span className="font-mono text-xs text-gray-400">{v.angle.angle_id}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${verdictClass(v.angle.branch_verdict)}`}>
                      {v.angle.branch_verdict}
                    </span>
                    {v.branch && <span className="text-xs text-gray-400">on {v.branch.name}</span>}
                  </div>
                  {v.angle.angle_type && (
                    <p className="text-sm font-semibold text-gray-900">{v.angle.angle_type}</p>
                  )}
                  {v.angle.hook_examples && v.angle.hook_examples.length > 0 && (
                    <p className="text-sm text-gray-700 mt-1">
                      <span className="text-gray-500">Example:</span> {v.angle.hook_examples[0]}
                    </p>
                  )}
                  <div className="grid grid-cols-4 gap-2 mt-3">
                    {[
                      { label: 'ROAS (branch)', value: `${v.angle.roas.toFixed(2)}x` },
                      { label: 'Benchmark', value: v.angle.branch_benchmark > 0 ? `${v.angle.branch_benchmark.toFixed(2)}x` : '–' },
                      { label: 'Conversions', value: v.angle.conversions },
                      { label: 'Combos', value: v.angle.combos },
                    ].map(m => (
                      <div key={m.label} className="bg-white rounded-lg p-2">
                        <p className="text-[10px] text-gray-500 uppercase">{m.label}</p>
                        <p className="text-sm font-bold text-gray-900">{m.value}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Keypoints + ROAS */}
              {v.keypoints && v.keypoints.length > 0 && (
                <div className="mb-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 mb-2">Keypoints</p>
                  <ul className="space-y-2">
                    {v.keypoints.map(k => (
                      <li key={k.id} className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 flex items-center justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 mb-0.5">
                            <span className="text-[10px] uppercase text-gray-500">{k.category}</span>
                            <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${verdictClass(k.branch_verdict)}`}>
                              {k.branch_verdict}
                            </span>
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

              <div className="flex flex-wrap items-center gap-2">
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

          {/* Creator: edit while pending — bumps round, resets reviewers across all versions */}
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
                Apply quick fixes (verbal feedback). Saving bumps to round {batch.round + 1} and asks all reviewers to re-review the whole batch.
              </p>

              {editOpen && (
                <div className="mt-4 space-y-4">
                  {/* Shared batch fields */}
                  <div className="bg-white border border-gray-200 rounded-lg p-3 space-y-3">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Batch settings</p>
                    <div>
                      <label className="block text-xs text-gray-600 mb-1">Deadline</label>
                      <input
                        type="datetime-local"
                        value={editDeadline}
                        onChange={e => setEditDeadline(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-600 mb-1">
                        Reviewers <span className="text-gray-400 font-normal">(at least one — applies to all versions)</span>
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
                  </div>

                  {/* Per-version content */}
                  {batch.versions.map((v, i) => {
                    const e = editVersions[v.id]
                    if (!e) return null
                    return (
                      <div key={v.id} className="bg-white border border-gray-200 rounded-lg p-3 space-y-2">
                        <div className="flex items-center gap-2">
                          <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-blue-100 text-blue-700 text-[11px] font-bold">
                            {i + 1}
                          </span>
                          <p className="text-xs font-semibold text-gray-900">
                            {v.combo_name || v.combo_id_display || `Version ${i + 1}`}
                          </p>
                        </div>

                        <div>
                          <label className="block text-xs text-gray-600 mb-1">Working file URL</label>
                          <input
                            type="url"
                            value={e.file}
                            onChange={ev => patchDraft(v.id, { file: ev.target.value })}
                            placeholder="https://figma.com/design/..."
                            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                          />
                        </div>

                        <div className="border border-gray-100 rounded-lg p-2.5 space-y-2 bg-gray-50">
                          <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                            Ad copy {v.copy ? <span className="font-mono normal-case font-normal text-gray-400">({v.copy.copy_id})</span> : null}
                          </p>
                          <div>
                            <label className="block text-xs text-gray-600 mb-1">Headline</label>
                            <input
                              type="text"
                              value={e.headline}
                              onChange={ev => patchDraft(v.id, { headline: ev.target.value })}
                              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                            />
                          </div>
                          <div>
                            <label className="block text-xs text-gray-600 mb-1">Body</label>
                            <textarea
                              value={e.body}
                              onChange={ev => patchDraft(v.id, { body: ev.target.value })}
                              rows={5}
                              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
                            />
                          </div>
                          <div className="grid grid-cols-3 gap-2">
                            <div>
                              <label className="block text-xs text-gray-600 mb-1">CTA</label>
                              <input
                                type="text"
                                value={e.cta}
                                onChange={ev => patchDraft(v.id, { cta: ev.target.value })}
                                placeholder="Book Now"
                                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                              />
                            </div>
                            <div>
                              <label className="block text-xs text-gray-600 mb-1">Language</label>
                              <select
                                value={e.language}
                                onChange={ev => patchDraft(v.id, { language: ev.target.value })}
                                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                              >
                                <option value="en">English</option>
                                <option value="vi">Vietnamese</option>
                                <option value="zh">Chinese</option>
                                <option value="ja">Japanese</option>
                                <option value="de">German</option>
                              </select>
                            </div>
                            <div>
                              <label className="block text-xs text-gray-600 mb-1">Target audience</label>
                              <select
                                value={e.ta}
                                onChange={ev => patchDraft(v.id, { ta: ev.target.value })}
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
                            If this copy is shared with other combos, a new copy_id is auto-cloned so the change doesn&apos;t leak.
                          </p>
                        </div>

                        <div>
                          <label className="block text-xs text-gray-600 mb-1">Angle</label>
                          <select
                            value={e.angleId}
                            onChange={ev => patchDraft(v.id, { angleId: ev.target.value })}
                            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                          >
                            <option value="">— No angle —</option>
                            {angleOptions
                              .filter(a => !a.branch_id || a.branch_id === v.branch?.id)
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
                              .filter(k => k.branch_id === v.branch?.id)
                              .map(k => {
                                const on = e.keypointIds.includes(k.id)
                                return (
                                  <button
                                    key={k.id}
                                    type="button"
                                    onClick={() => patchDraft(v.id, {
                                      keypointIds: on
                                        ? e.keypointIds.filter(x => x !== k.id)
                                        : [...e.keypointIds, k.id],
                                    })}
                                    className={`text-xs px-2 py-1 rounded-full border ${
                                      on ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-700 border-gray-300 hover:border-blue-400'
                                    }`}
                                  >
                                    {k.title}
                                  </button>
                                )
                              })}
                            {keypointOptions.filter(k => k.branch_id === v.branch?.id).length === 0 && (
                              <span className="text-xs text-gray-400 italic">No keypoints for this branch.</span>
                            )}
                          </div>
                        </div>
                      </div>
                    )
                  })}

                  {editError && (
                    <div className="bg-red-50 text-red-700 px-3 py-2 rounded-lg text-xs">{editError}</div>
                  )}
                  <button
                    onClick={handleRevise}
                    disabled={editing}
                    className="bg-blue-600 text-white px-6 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
                  >
                    {editing ? 'Saving…' : `Save & re-notify (round ${batch.round + 1})`}
                  </button>
                </div>
              )}
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
                        {v.combo_name || v.combo_id_display || v.working_file_label || `Version ${i + 1}`}
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
