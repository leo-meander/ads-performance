'use client'

import { useEffect, useState } from 'react'
import { Sparkles, X, Check } from 'lucide-react'
import AutoAssignPanel, { AutoAssignResult } from './AutoAssignPanel'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Keypoint { id: string; branch_id: string; category: string; title: string }

interface Props {
  comboId: string
  branchId: string
  adName: string | null
  initialKeypointIds: string[]
  onClose: () => void
  onSaved: () => void
}

/**
 * "Double check keypoints" modal for the Creative Library.
 *
 * Replaces the inline checkbox dropdown: opens a focused dialog where the user
 * can manually toggle the branch's keypoints AND run the AI auto-suggest
 * (AutoAssignPanel) to re-generate suitable keypoints from the combo's own ad
 * copy — useful for winning ads that were tagged with the wrong keypoints.
 * Nothing persists until "Save"; suggested NEW keypoints are created by the
 * panel, then merged into the selection here.
 */
export default function KeypointDoubleCheckModal({
  comboId, branchId, adName, initialKeypointIds, onClose, onSaved,
}: Props) {
  const [keypoints, setKeypoints] = useState<Keypoint[]>([])
  const [selected, setSelected] = useState<string[]>(initialKeypointIds)
  const [showAuto, setShowAuto] = useState(false)
  // Angle suggested by the AI run, kept only to apply alongside the keypoints.
  const [pendingAngle, setPendingAngle] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const loadKeypoints = () => {
    fetch(`${API_BASE}/api/keypoints?branch_id=${branchId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setKeypoints(d.data) })
      .catch(() => {})
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(loadKeypoints, [branchId])

  // Close on Escape (but let the AI panel handle its own Escape first).
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape' && !showAuto) onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose, showAuto])

  const toggle = (id: string) =>
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])

  const onAutoResult = (r: AutoAssignResult) => {
    // Merge the suggested keypoints into the current selection; reload the list
    // so freshly-created keypoints show their titles in the checkbox list.
    setSelected(prev => Array.from(new Set([...prev, ...r.keypoint_ids])))
    if (r.angle_id) setPendingAngle(r.angle_id)
    loadKeypoints()
    setShowAuto(false)
  }

  const save = async () => {
    setSaving(true); setErr('')
    try {
      const body: Record<string, unknown> = { keypoint_ids: selected }
      // Only touch the angle when the AI run proposed one the user kept.
      if (pendingAngle) body.angle_id = pendingAngle
      const r = await fetch(`${API_BASE}/api/combos/${comboId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })
      const d = await r.json()
      if (!d.success) { setErr(d.error || 'Save failed'); return }
      onSaved()
    } catch {
      setErr('Network error')
    } finally {
      setSaving(false)
    }
  }

  const branchKeypoints = keypoints.filter(k => k.branch_id === branchId)

  return (
    <>
      <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
        <div className="bg-white rounded-xl w-full max-w-lg max-h-[85vh] overflow-auto flex flex-col">
          <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white">
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-gray-900">Double check keypoints</h3>
              <p className="text-xs text-gray-400 truncate">{adName || comboId}</p>
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="p-5 space-y-4">
            <button
              onClick={() => setShowAuto(true)}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-sm font-medium text-purple-700 bg-purple-50 hover:bg-purple-100 border border-purple-200 rounded-lg"
            >
              <Sparkles className="w-4 h-4" /> Auto-suggest keypoints with AI
            </button>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-medium text-gray-500">
                  Keypoints ({selected.length} selected)
                </span>
              </div>
              {branchKeypoints.length === 0 ? (
                <p className="text-sm text-gray-400">No keypoints for this branch yet — use AI to propose some.</p>
              ) : (
                <div className="space-y-1 max-h-72 overflow-auto">
                  {branchKeypoints.map(k => (
                    <label key={k.id} className="flex items-center gap-2 text-sm p-1.5 rounded hover:bg-gray-50 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={selected.includes(k.id)}
                        onChange={() => toggle(k.id)}
                        className="w-3.5 h-3.5"
                      />
                      <span className="text-xs text-gray-400">[{k.category}]</span>
                      <span className="text-gray-700">{k.title}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            {err && <p className="text-sm text-red-600">{err}</p>}
          </div>

          <div className="flex gap-2 px-5 py-4 border-t border-gray-100 sticky bottom-0 bg-white">
            <button
              onClick={save}
              disabled={saving}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              <Check className="w-4 h-4" /> {saving ? 'Saving…' : 'Save'}
            </button>
            <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded">
              Cancel
            </button>
          </div>
        </div>
      </div>

      {showAuto && (
        <AutoAssignPanel
          branchId={branchId}
          comboId={comboId}
          onResult={onAutoResult}
          onClose={() => setShowAuto(false)}
        />
      )}
    </>
  )
}
