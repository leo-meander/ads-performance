'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Trash2, Sparkles } from 'lucide-react'
import AutoAssignPanel, { AutoAssignResult } from '@/components/AutoAssignPanel'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Account { id: string; account_name: string; platform: string }
interface ReviewerOption { id: string; full_name: string; email: string }
interface Copy { id: string; copy_id: string; headline: string; body_text: string; cta: string | null; language: string; target_audience: string; derived_verdict: string | null }
interface Material { id: string; material_id: string; material_type: string; file_url: string; description: string | null; target_audience: string | null }
interface Keypoint { id: string; branch_id: string; category: string; title: string }
interface Angle { angle_id: string; branch_id: string | null; angle_type: string; angle_explain: string; status: string }

interface Version {
  mode: 'new' | 'existing'
  adName: string
  // new
  creativeUrl: string
  creativeType: string
  headline: string
  primaryText: string
  cta: string
  // existing
  copyId: string
  materialId: string
  // working file override
  workingFileUrl: string
  // per-version targeting
  keypointIds: string[]
  angleId: string
}

const emptyVersion = (): Version => ({
  mode: 'new', adName: '', creativeUrl: '', creativeType: 'image',
  headline: '', primaryText: '', cta: '', copyId: '', materialId: '', workingFileUrl: '',
  keypointIds: [], angleId: '',
})

export default function CreateBatchAndSubmitPage() {
  const router = useRouter()
  const [accounts, setAccounts] = useState<Account[]>([])
  const [reviewers, setReviewers] = useState<ReviewerOption[]>([])
  const [copies, setCopies] = useState<Copy[]>([])
  const [materials, setMaterials] = useState<Material[]>([])
  const [keypoints, setKeypoints] = useState<Keypoint[]>([])
  const [angles, setAngles] = useState<Angle[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  // Shared fields (same target across all versions)
  const [branchId, setBranchId] = useState('')
  const [targetAudience, setTargetAudience] = useState('')
  const [language, setLanguage] = useState('')
  const [selectedReviewers, setSelectedReviewers] = useState<string[]>([])
  // Index of the version whose auto-assign panel is open (null = none).
  const [autoAssignVersion, setAutoAssignVersion] = useState<number | null>(null)
  const [workingFileLabel, setWorkingFileLabel] = useState('Figma Frame')
  const [deadline, setDeadline] = useState('')
  const [note, setNote] = useState('')

  // Versions
  const [versions, setVersions] = useState<Version[]>([emptyVersion()])

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setAccounts(d.data.filter((a: Account) => a.platform === 'meta')) }).catch(() => {})
    fetch(`${API_BASE}/api/users/reviewers`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setReviewers(d.data.items || []) }).catch(() => {})
    fetch(`${API_BASE}/api/keypoints`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setKeypoints(d.data) }).catch(() => {})
    fetch(`${API_BASE}/api/angles`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setAngles(d.data) }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!branchId) { setCopies([]); setMaterials([]); return }
    fetch(`${API_BASE}/api/copies?branch_id=${branchId}&limit=200`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setCopies(d.data.items || []) }).catch(() => {})
    fetch(`${API_BASE}/api/materials?branch_id=${branchId}&limit=200`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setMaterials(d.data.items || []) }).catch(() => {})
  }, [branchId])

  const toggleReviewer = (id: string) => setSelectedReviewers(prev => prev.includes(id) ? prev.filter(r => r !== id) : [...prev, id])

  const branchKeypoints = keypoints.filter(k => k.branch_id === branchId)
  const branchAngles = angles.filter(a => !a.branch_id || a.branch_id === branchId)
  const filteredCopies = copies.filter(c => (!language || c.language === language) && (!targetAudience || c.target_audience === targetAudience))
  const filteredMaterials = materials.filter(m => !targetAudience || !m.target_audience || m.target_audience === targetAudience)

  const updateVersion = (i: number, patch: Partial<Version>) =>
    setVersions(prev => prev.map((v, idx) => idx === i ? { ...v, ...patch } : v))
  const addVersion = () => setVersions(prev => [...prev, emptyVersion()])
  const removeVersion = (i: number) => setVersions(prev => prev.filter((_, idx) => idx !== i))
  const toggleVersionKeypoint = (i: number, id: string) =>
    setVersions(prev => prev.map((v, idx) => idx === i
      ? { ...v, keypointIds: v.keypointIds.includes(id) ? v.keypointIds.filter(k => k !== id) : [...v.keypointIds, id] }
      : v))

  // Headline/body the auto-assign panel analyzes for a given version.
  const autoAssignSource = (v: Version): { headline: string; bodyText: string } => {
    if (v.mode === 'new') return { headline: v.headline, bodyText: v.primaryText }
    const copy = copies.find(c => c.copy_id === v.copyId)
    return { headline: copy?.headline || '', bodyText: copy?.body_text || '' }
  }

  const handleAutoAssignResult = (i: number, r: AutoAssignResult) => {
    setAutoAssignVersion(null)
    // Newly-created keypoints must appear in the branch checkbox list.
    if (r.created_keypoints.length > 0) {
      setKeypoints(prev => [
        ...prev,
        ...r.created_keypoints.map(k => ({ id: k.id, branch_id: branchId, category: k.category, title: k.title })),
      ])
    }
    setVersions(prev => prev.map((v, idx) => idx === i ? {
      ...v,
      angleId: r.angle_id || v.angleId,
      keypointIds: Array.from(new Set([...v.keypointIds, ...r.keypoint_ids])),
    } : v))
  }

  const createCombo = async (v: Version): Promise<{ id: string; workingFileUrl: string } | null> => {
    const shared = {
      branch_id: branchId,
      ad_name: v.adName,
      target_audience: targetAudience || null,
      keypoint_ids: v.keypointIds.length > 0 ? v.keypointIds : null,
      angle_id: v.angleId || null,
    }
    if (v.mode === 'existing') {
      const res = await fetch(`${API_BASE}/api/combos`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ ...shared, copy_id: v.copyId, material_id: v.materialId }),
      })
      const data = await res.json()
      if (!data.success) { setError(`Version "${v.adName}": ${data.error || 'failed to create combo'}`); return null }
      const material = materials.find(m => m.material_id === v.materialId)
      return { id: data.data.id, workingFileUrl: v.workingFileUrl || material?.file_url || '' }
    }
    const res = await fetch(`${API_BASE}/api/combos/quick-create`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
      body: JSON.stringify({
        ...shared, creative_url: v.creativeUrl, creative_type: v.creativeType,
        headline: v.headline, primary_text: v.primaryText, cta: v.cta || null, language: language || 'en',
      }),
    })
    const data = await res.json()
    if (!data.success) { setError(`Version "${v.adName}": ${data.error || 'failed to create combo'}`); return null }
    return { id: data.data.id, workingFileUrl: v.workingFileUrl || v.creativeUrl }
  }

  const validate = (): string | null => {
    if (!branchId) return 'Select a branch'
    if (selectedReviewers.length === 0) return 'Select at least one reviewer'
    for (const [i, v] of versions.entries()) {
      const n = i + 1
      if (!v.adName) return `Version ${n}: enter an ad name`
      if (v.mode === 'existing') {
        if (!v.copyId) return `Version ${n}: select a copy`
        if (!v.materialId) return `Version ${n}: select a material`
      } else {
        if (!v.creativeUrl) return `Version ${n}: enter a creative URL`
        if (!v.headline) return `Version ${n}: enter a headline`
        if (!v.primaryText) return `Version ${n}: enter primary text`
      }
    }
    return null
  }

  const handleSubmit = async () => {
    const err = validate()
    if (err) return setError(err)
    setSubmitting(true)
    setError('')

    try {
      const created: { combo_id: string; working_file_url: string | null; working_file_label: string | null }[] = []
      for (const v of versions) {
        const combo = await createCombo(v)
        if (!combo) { setSubmitting(false); return }
        created.push({
          combo_id: combo.id,
          working_file_url: combo.workingFileUrl || null,
          working_file_label: workingFileLabel || null,
        })
      }

      const res = await fetch(`${API_BASE}/api/approval-batches`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({
          versions: created,
          reviewer_ids: selectedReviewers,
          deadline: deadline ? new Date(deadline).toISOString() : null,
          note: note.trim() || null,
        }),
      })
      const data = await res.json()
      if (data.success) {
        router.push(`/approvals/batch/${data.data.id}`)
      } else {
        setError(data.error || 'Combos created but failed to submit batch for approval')
      }
    } catch {
      setError('Network error')
    }
    setSubmitting(false)
  }

  return (
    <div className="max-w-2xl mx-auto">
      <button onClick={() => router.push('/creative')} className="text-sm text-blue-600 hover:text-blue-700 mb-4">
        &larr; Back to Creative Library
      </button>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">New Versions &amp; Submit for Approval</h1>
      {error && <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">{error}</div>}

      <div className="space-y-6">
        {/* Shared target */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Target (shared by all versions)</h3>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Branch *</label>
              <select value={branchId} onChange={e => { setBranchId(e.target.value); setVersions(vs => vs.map(v => ({ ...v, copyId: '', materialId: '', keypointIds: [], angleId: '' }))) }}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                <option value="">Select branch</option>
                {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Target Audience</label>
              <select value={targetAudience} onChange={e => setTargetAudience(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                <option value="">None</option>
                {['Solo','Couple','Friend','Group','Business'].map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Language</label>
              <select value={language} onChange={e => setLanguage(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                <option value="">English (default)</option>
                <option value="en">English</option>
                <option value="vi">Vietnamese</option>
                <option value="zh">Chinese</option>
                <option value="ja">Japanese</option>
                <option value="de">German</option>
              </select>
            </div>
          </div>

        </div>

        {/* Versions */}
        {versions.map((v, i) => (
          <div key={i} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-gray-900">Version {i + 1}</h3>
              <div className="flex items-center gap-2">
                <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5">
                  {(['new', 'existing'] as const).map(m => (
                    <button key={m} type="button" onClick={() => updateVersion(i, { mode: m })}
                      className={`px-2.5 py-1 rounded-md text-xs font-medium ${v.mode === m ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500'}`}>
                      {m === 'new' ? 'Create New' : 'Use Existing'}
                    </button>
                  ))}
                </div>
                {versions.length > 1 && (
                  <button type="button" onClick={() => removeVersion(i)} title="Remove version"
                    className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded">
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </div>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Ad Name *</label>
                <input type="text" value={v.adName} onChange={e => updateVersion(i, { adName: e.target.value })}
                  placeholder="e.g. Solo Female Dorm - Saigon - TOF - v1"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>

              {v.mode === 'new' ? (
                <>
                  <div className="grid grid-cols-3 gap-3">
                    <div className="col-span-2">
                      <label className="block text-xs text-gray-500 mb-1">Creative URL *</label>
                      <input type="url" value={v.creativeUrl} onChange={e => updateVersion(i, { creativeUrl: e.target.value })}
                        placeholder="https://figma.com/design/..."
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Type</label>
                      <select value={v.creativeType} onChange={e => updateVersion(i, { creativeType: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                        <option value="image">Image</option><option value="video">Video</option><option value="carousel">Carousel</option>
                      </select>
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Headline *</label>
                    <input type="text" value={v.headline} onChange={e => updateVersion(i, { headline: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Primary Text *</label>
                    <textarea value={v.primaryText} onChange={e => updateVersion(i, { primaryText: e.target.value })} rows={3}
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">CTA</label>
                    <input type="text" value={v.cta} onChange={e => updateVersion(i, { cta: e.target.value })} placeholder="e.g. Book Now"
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Ad Copy *</label>
                    <select value={v.copyId} onChange={e => updateVersion(i, { copyId: e.target.value })}
                      disabled={!branchId}
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm disabled:bg-gray-50">
                      <option value="">{branchId ? 'Select copy' : 'Select a branch first'}</option>
                      {filteredCopies.map(c => <option key={c.copy_id} value={c.copy_id}>{c.copy_id} — {c.headline}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Material *</label>
                    <select value={v.materialId} onChange={e => updateVersion(i, { materialId: e.target.value })}
                      disabled={!branchId}
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm disabled:bg-gray-50">
                      <option value="">{branchId ? 'Select material' : 'Select a branch first'}</option>
                      {filteredMaterials.map(m => <option key={m.material_id} value={m.material_id}>{m.material_id} — {m.material_type}{m.description ? ` — ${m.description}` : ''}</option>)}
                    </select>
                  </div>
                </>
              )}

              <div>
                <label className="block text-xs text-gray-500 mb-1">Working File for Review (optional — defaults to creative)</label>
                <input type="url" value={v.workingFileUrl} onChange={e => updateVersion(i, { workingFileUrl: e.target.value })}
                  placeholder="Leave empty to use the creative URL"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>

              {/* Per-version targeting: keypoints + angle */}
              <div className="pt-3 mt-1 border-t border-gray-100 space-y-4">
                <div className="flex items-center justify-between">
                  <label className="block text-xs font-medium text-gray-500">Keypoints &amp; Angle</label>
                  <button type="button"
                    onClick={() => setAutoAssignVersion(i)}
                    disabled={!branchId || (!autoAssignSource(v).headline && !autoAssignSource(v).bodyText)}
                    title={!branchId ? 'Select a branch first' : (!autoAssignSource(v).headline && !autoAssignSource(v).bodyText ? 'Fill the headline/copy first' : '')}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-purple-700 bg-purple-50 rounded hover:bg-purple-100 disabled:opacity-40 disabled:cursor-not-allowed">
                    <Sparkles className="w-3.5 h-3.5" /> Auto-assign
                  </button>
                </div>
                {!branchId ? (
                  <p className="text-xs text-gray-400">Select a branch to choose keypoints &amp; angle.</p>
                ) : (
                  <>
                    <div>
                      <label className="block text-xs text-gray-500 mb-2">Keypoints</label>
                      {branchKeypoints.length === 0 ? <p className="text-xs text-gray-400">No keypoints for this branch.</p> : (
                        <div className="grid grid-cols-2 gap-1 max-h-40 overflow-auto">
                          {branchKeypoints.map(k => (
                            <label key={k.id} className="flex items-center gap-2 p-1.5 rounded hover:bg-gray-50 cursor-pointer text-xs">
                              <input type="checkbox" checked={v.keypointIds.includes(k.id)} onChange={() => toggleVersionKeypoint(i, k.id)} className="w-3 h-3" />
                              <span className="text-gray-400">[{k.category}]</span>
                              <span className="text-gray-700">{k.title}</span>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-2">Ad Angle</label>
                      <select value={v.angleId} onChange={e => updateVersion(i, { angleId: e.target.value })}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                        <option value="">No angle</option>
                        {branchAngles.map(a => <option key={a.angle_id} value={a.angle_id}>{a.angle_id} - {a.angle_type} ({a.status})</option>)}
                      </select>
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        ))}

        <button type="button" onClick={addVersion}
          className="w-full inline-flex items-center justify-center gap-1.5 border border-dashed border-gray-300 text-gray-600 px-4 py-3 rounded-lg text-sm font-medium hover:border-blue-300 hover:text-blue-600">
          <Plus className="w-4 h-4" /> Add another version
        </button>

        {/* Working file label + deadline + note */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Working File Type</label>
            <select value={workingFileLabel} onChange={e => setWorkingFileLabel(e.target.value)}
              className="px-3 py-2 border border-gray-200 rounded-lg text-sm">
              <option value="Figma Frame">Figma</option><option value="Google Sheet">GSheet</option><option value="Other">Other</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Review Deadline</label>
            <input type="datetime-local" value={deadline} onChange={e => setDeadline(e.target.value)}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Note for Reviewers</label>
            <textarea value={note} onChange={e => setNote(e.target.value)} rows={2}
              placeholder="e.g. Testing 3 hook variations of the June angle."
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y" />
          </div>
        </div>

        {/* Reviewers */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Select Reviewers *</h3>
          {reviewers.length === 0 ? (
            <p className="text-sm text-gray-400">No reviewers available.</p>
          ) : (
            <div className="space-y-2">
              {reviewers.map(r => (
                <label key={r.id} className="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50 cursor-pointer">
                  <input type="checkbox" checked={selectedReviewers.includes(r.id)} onChange={() => toggleReviewer(r.id)} className="rounded border-gray-300" />
                  <div>
                    <p className="text-sm font-medium text-gray-900">{r.full_name}</p>
                    <p className="text-xs text-gray-400">{r.email}</p>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>

        <button onClick={handleSubmit} disabled={submitting}
          className="w-full bg-blue-600 text-white px-4 py-3 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
          {submitting ? 'Creating & Submitting...' : `Submit ${versions.length} version${versions.length !== 1 ? 's' : ''} for Approval`}
        </button>
      </div>

      {autoAssignVersion !== null && versions[autoAssignVersion] && (
        <AutoAssignPanel
          branchId={branchId}
          headline={autoAssignSource(versions[autoAssignVersion]).headline}
          bodyText={autoAssignSource(versions[autoAssignVersion]).bodyText}
          onResult={r => handleAutoAssignResult(autoAssignVersion, r)}
          onClose={() => setAutoAssignVersion(null)}
        />
      )}
    </div>
  )
}
