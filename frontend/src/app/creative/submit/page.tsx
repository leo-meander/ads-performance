'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Account { id: string; account_name: string }
interface ReviewerOption { id: string; full_name: string; email: string }
interface Copy { id: string; copy_id: string; headline: string; body_text: string; cta: string | null; language: string; target_audience: string; derived_verdict: string | null }
interface Material { id: string; material_id: string; material_type: string; file_url: string; description: string | null; target_audience: string | null; derived_verdict: string | null }
interface Keypoint { id: string; branch_id: string; category: string; title: string }
interface Angle { angle_id: string; branch_id: string | null; angle_type: string; angle_explain: string; status: string }

const VERDICT_COLORS: Record<string, string> = {
  WIN: 'bg-green-100 text-green-700', TEST: 'bg-yellow-100 text-yellow-700', LOSE: 'bg-red-100 text-red-700',
}

export default function CreateAndSubmitPage() {
  const router = useRouter()
  const [mode, setMode] = useState<'existing' | 'new'>('new')
  const [accounts, setAccounts] = useState<Account[]>([])
  const [reviewers, setReviewers] = useState<ReviewerOption[]>([])
  const [copies, setCopies] = useState<Copy[]>([])
  const [materials, setMaterials] = useState<Material[]>([])
  const [keypoints, setKeypoints] = useState<Keypoint[]>([])
  const [angles, setAngles] = useState<Angle[]>([])
  const [selectedReviewers, setSelectedReviewers] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  // Shared fields
  const [branchId, setBranchId] = useState('')
  const [adName, setAdName] = useState('')
  const [targetAudience, setTargetAudience] = useState('')
  const [filterLanguage, setFilterLanguage] = useState('')
  const [selectedKeypoints, setSelectedKeypoints] = useState<string[]>([])
  const [selectedAngle, setSelectedAngle] = useState('')

  // Option 1: Existing
  const [selectedCopyId, setSelectedCopyId] = useState('')
  const [selectedMaterialId, setSelectedMaterialId] = useState('')
  const [copySearch, setCopySearch] = useState('')
  const [materialSearch, setMaterialSearch] = useState('')

  // Option 2: New
  const [creativeUrl, setCreativeUrl] = useState('')
  const [creativeType, setCreativeType] = useState('image')
  const [headline, setHeadline] = useState('')
  const [primaryText, setPrimaryText] = useState('')
  const [cta, setCta] = useState('')

  // Approval fields
  const [workingFileUrl, setWorkingFileUrl] = useState('')
  const [workingFileLabel, setWorkingFileLabel] = useState('Canva Design')
  const [deadline, setDeadline] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`).then(r => r.json()).then(d => { if (d.success) setAccounts(d.data) }).catch(() => {})
    fetch(`${API_BASE}/api/users/reviewers`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setReviewers(d.data.items || []) }).catch(() => {})
    fetch(`${API_BASE}/api/keypoints`).then(r => r.json()).then(d => { if (d.success) setKeypoints(d.data) }).catch(() => {})
    fetch(`${API_BASE}/api/angles`).then(r => r.json()).then(d => { if (d.success) setAngles(d.data) }).catch(() => {})
  }, [])

  useEffect(() => {
    if (!branchId) return
    fetch(`${API_BASE}/api/copies?branch_id=${branchId}&limit=200`).then(r => r.json()).then(d => { if (d.success) setCopies(d.data.items || []) }).catch(() => {})
    fetch(`${API_BASE}/api/materials?branch_id=${branchId}&limit=200`).then(r => r.json()).then(d => { if (d.success) setMaterials(d.data.items || []) }).catch(() => {})
  }, [branchId])

  const toggleReviewer = (id: string) => setSelectedReviewers(prev => prev.includes(id) ? prev.filter(r => r !== id) : [...prev, id])
  const toggleKeypoint = (id: string) => setSelectedKeypoints(prev => prev.includes(id) ? prev.filter(k => k !== id) : [...prev, id])

  const selectedCopy = copies.find(c => c.copy_id === selectedCopyId)
  const selectedMaterial = materials.find(m => m.material_id === selectedMaterialId)
  const branchKeypoints = keypoints.filter(k => k.branch_id === branchId)
  const branchAngles = angles.filter(a => !a.branch_id || a.branch_id === branchId)

  const handleSubmit = async () => {
    if (!branchId) return setError('Select a branch')
    if (!adName) return setError('Enter an ad name')
    if (selectedReviewers.length === 0) return setError('Select at least one reviewer')

    if (mode === 'existing') {
      if (!selectedCopyId) return setError('Select a copy')
      if (!selectedMaterialId) return setError('Select a material')
    } else {
      if (!creativeUrl) return setError('Enter a creative URL')
      if (!headline) return setError('Enter a headline')
      if (!primaryText) return setError('Enter primary text')
    }

    setSubmitting(true)
    setError('')

    try {
      let comboDataId: string

      if (mode === 'existing') {
        // Use existing copy + material
        const res = await fetch(`${API_BASE}/api/combos`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            branch_id: branchId, ad_name: adName, target_audience: targetAudience || null,
            copy_id: selectedCopyId, material_id: selectedMaterialId,
            keypoint_ids: selectedKeypoints.length > 0 ? selectedKeypoints : null,
            angle_id: selectedAngle || null,
          }),
        })
        const data = await res.json()
        if (!data.success) { setError(data.error || 'Failed to create combo'); setSubmitting(false); return }
        comboDataId = data.data.id
      } else {
        // Create new material + copy + combo
        const res = await fetch(`${API_BASE}/api/combos/quick-create`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            branch_id: branchId, ad_name: adName, creative_url: creativeUrl, creative_type: creativeType,
            headline, primary_text: primaryText, cta: cta || null, language: filterLanguage || 'en', target_audience: targetAudience || null,
            keypoint_ids: selectedKeypoints.length > 0 ? selectedKeypoints : null,
            angle_id: selectedAngle || null,
          }),
        })
        const data = await res.json()
        if (!data.success) { setError(data.error || 'Failed to create combo'); setSubmitting(false); return }
        comboDataId = data.data.id
      }

      // Submit for approval
      const approvalRes = await fetch(`${API_BASE}/api/approvals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          combo_id: comboDataId,
          reviewer_ids: selectedReviewers,
          working_file_url: workingFileUrl || (mode === 'new' ? creativeUrl : selectedMaterial?.file_url) || null,
          working_file_label: workingFileLabel || null,
          deadline: deadline ? new Date(deadline).toISOString() : null,
        }),
      })
      const approvalData = await approvalRes.json()
      if (approvalData.success) {
        router.push(`/approvals/${approvalData.data.id}`)
      } else {
        setError(approvalData.error || 'Combo created but failed to submit for approval')
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
      <h1 className="text-2xl font-bold text-gray-900 mb-6">New Combo &amp; Submit for Approval</h1>
      {error && <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">{error}</div>}

      <div className="space-y-6">

        {/* Mode Toggle */}
        <div className="flex gap-2">
          <button onClick={() => setMode('existing')}
            className={`flex-1 px-4 py-3 rounded-lg border text-sm font-medium ${mode === 'existing' ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-gray-200 text-gray-600'}`}>
            Use Existing Copy + Material
          </button>
          <button onClick={() => setMode('new')}
            className={`flex-1 px-4 py-3 rounded-lg border text-sm font-medium ${mode === 'new' ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-gray-200 text-gray-600'}`}>
            Create New
          </button>
        </div>

        {/* Combo Info */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Combo Info</h3>
          <div className="space-y-4">
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Branch *</label>
                <select value={branchId} onChange={e => { setBranchId(e.target.value); setSelectedCopyId(''); setSelectedMaterialId('') }}
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
                <select value={filterLanguage} onChange={e => setFilterLanguage(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                  <option value="">All Languages</option>
                  <option value="en">English</option>
                  <option value="vi">Vietnamese</option>
                  <option value="zh">Chinese</option>
                  <option value="ja">Japanese</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Ad Name *</label>
              <input type="text" value={adName} onChange={e => setAdName(e.target.value)}
                placeholder="e.g. Solo Female Dorm - Saigon - TOF"
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
        </div>

        {/* Option 1: Existing Copy + Material */}
        {mode === 'existing' && branchId && (() => {
          let filteredCopies = copies
          if (filterLanguage) filteredCopies = filteredCopies.filter(c => c.language === filterLanguage)
          if (targetAudience) filteredCopies = filteredCopies.filter(c => c.target_audience === targetAudience)
          const q = copySearch.toLowerCase()
          if (q) filteredCopies = filteredCopies.filter(c => c.copy_id.toLowerCase().includes(q) || c.headline.toLowerCase().includes(q) || c.body_text.toLowerCase().includes(q) || c.target_audience.toLowerCase().includes(q))

          let filteredMaterials = materials
          if (targetAudience) filteredMaterials = filteredMaterials.filter(m => !m.target_audience || m.target_audience === targetAudience)
          const mq = materialSearch.toLowerCase()
          if (mq) filteredMaterials = filteredMaterials.filter(m => m.material_id.toLowerCase().includes(mq) || (m.description || '').toLowerCase().includes(mq) || m.file_url.toLowerCase().includes(mq) || m.material_type.toLowerCase().includes(mq))

          return (
          <>
            {/* Select Copy */}
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-900">Select Ad Copy *</h3>
                <span className="text-xs text-gray-400">{filteredCopies.length} of {copies.length}</span>
              </div>
              <input type="text" value={copySearch} onChange={e => setCopySearch(e.target.value)}
                placeholder="Search by ID, headline, or content..."
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              {copies.length === 0 ? <p className="text-sm text-gray-400">No copies for this branch.</p> :
               filteredCopies.length === 0 ? <p className="text-sm text-gray-400">No copies match &quot;{copySearch}&quot;</p> : (
                <div className="space-y-2 max-h-64 overflow-auto">
                  {filteredCopies.map(c => (
                    <label key={c.copy_id}
                      className={`block p-3 rounded-lg border cursor-pointer ${selectedCopyId === c.copy_id ? 'border-blue-400 bg-blue-50' : 'border-gray-100 hover:border-gray-200'}`}>
                      <div className="flex items-center gap-2">
                        <input type="radio" name="copy" checked={selectedCopyId === c.copy_id} onChange={() => setSelectedCopyId(c.copy_id)} />
                        <span className="font-mono text-xs text-gray-400">{c.copy_id}</span>
                        <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100">{c.target_audience}</span>
                        <span className="text-xs text-gray-400">{c.language}</span>
                        {c.derived_verdict && <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${VERDICT_COLORS[c.derived_verdict] || ''}`}>{c.derived_verdict}</span>}
                      </div>
                      <p className="text-sm font-medium text-gray-900 mt-1">{c.headline}</p>
                      <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{c.body_text}</p>
                    </label>
                  ))}
                </div>
              )}
            </div>

            {/* Select Material */}
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-900">Select Material *</h3>
                <span className="text-xs text-gray-400">{filteredMaterials.length} of {materials.length}</span>
              </div>
              <input type="text" value={materialSearch} onChange={e => setMaterialSearch(e.target.value)}
                placeholder="Search by ID, description, or URL..."
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm mb-3 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              {materials.length === 0 ? <p className="text-sm text-gray-400">No materials for this branch.</p> :
               filteredMaterials.length === 0 ? <p className="text-sm text-gray-400">No materials match &quot;{materialSearch}&quot;</p> : (
                <div className="space-y-2 max-h-64 overflow-auto">
                  {filteredMaterials.map(m => (
                    <label key={m.material_id}
                      className={`block p-3 rounded-lg border cursor-pointer ${selectedMaterialId === m.material_id ? 'border-blue-400 bg-blue-50' : 'border-gray-100 hover:border-gray-200'}`}>
                      <div className="flex items-center gap-2">
                        <input type="radio" name="material" checked={selectedMaterialId === m.material_id} onChange={() => setSelectedMaterialId(m.material_id)} />
                        <span className="font-mono text-xs text-gray-400">{m.material_id}</span>
                        <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100">{m.material_type}</span>
                        {m.derived_verdict && <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${VERDICT_COLORS[m.derived_verdict] || ''}`}>{m.derived_verdict}</span>}
                      </div>
                      <p className="text-sm text-gray-600 mt-1">{m.description || 'No description'}</p>
                      <a href={m.file_url} target="_blank" rel="noopener noreferrer" className="text-xs text-blue-500 truncate block mt-0.5">{m.file_url}</a>
                    </label>
                  ))}
                </div>
              )}
            </div>
          </>
          )
        })()}

        {/* Option 2: Create New */}
        {mode === 'new' && (
          <>
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-gray-900 mb-4">Creative</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Creative URL * (Canva / Figma / Drive)</label>
                  <input type="url" value={creativeUrl} onChange={e => setCreativeUrl(e.target.value)}
                    placeholder="https://canva.com/design/..."
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Type</label>
                  <select value={creativeType} onChange={e => setCreativeType(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                    <option value="image">Image</option><option value="video">Video</option><option value="carousel">Carousel</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-gray-900 mb-4">Ad Copy</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Headline *</label>
                  <input type="text" value={headline} onChange={e => setHeadline(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Primary Text *</label>
                  <textarea value={primaryText} onChange={e => setPrimaryText(e.target.value)} rows={4}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">CTA</label>
                  <input type="text" value={cta} onChange={e => setCta(e.target.value)} placeholder="e.g. Book Now"
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
            </div>
          </>
        )}

        {/* Keypoints & Angle */}
        {branchId && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">Keypoints &amp; Angle</h3>
            <div className="space-y-4">
              {/* Keypoints */}
              <div>
                <label className="block text-xs text-gray-500 mb-2">Keypoints (select selling points)</label>
                {branchKeypoints.length === 0 ? <p className="text-xs text-gray-400">No keypoints for this branch.</p> : (
                  <div className="grid grid-cols-2 gap-1 max-h-40 overflow-auto">
                    {branchKeypoints.map(k => (
                      <label key={k.id} className="flex items-center gap-2 p-1.5 rounded hover:bg-gray-50 cursor-pointer text-xs">
                        <input type="checkbox" checked={selectedKeypoints.includes(k.id)} onChange={() => toggleKeypoint(k.id)} className="w-3 h-3" />
                        <span className="text-gray-400">[{k.category}]</span>
                        <span className="text-gray-700">{k.title}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
              {/* Angle */}
              <div>
                <label className="block text-xs text-gray-500 mb-2">Ad Angle</label>
                <select value={selectedAngle} onChange={e => setSelectedAngle(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                  <option value="">No angle</option>
                  {branchAngles.map(a => (
                    <option key={a.angle_id} value={a.angle_id}>{a.angle_id} - {a.angle_type} ({a.status})</option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        )}

        {/* Working File */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-2">Working File for Review</h3>
          <p className="text-xs text-gray-400 mb-3">Where reviewers should give feedback. Defaults to Creative URL.</p>
          <div className="flex gap-3">
            <input type="url" value={workingFileUrl} onChange={e => setWorkingFileUrl(e.target.value)}
              placeholder="Leave empty to use Creative URL"
              className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            <select value={workingFileLabel} onChange={e => setWorkingFileLabel(e.target.value)}
              className="px-3 py-2 border border-gray-200 rounded-lg text-sm">
              <option value="Canva Design">Canva</option><option value="Figma Frame">Figma</option><option value="Google Sheet">GSheet</option><option value="Other">Other</option>
            </select>
          </div>
        </div>

        {/* Deadline */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-2">Review Deadline</h3>
          <input type="datetime-local" value={deadline} onChange={e => setDeadline(e.target.value)}
            className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
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
          {submitting ? 'Creating & Submitting...' : 'Create Combo & Submit for Approval'}
        </button>
      </div>
    </div>
  )
}
