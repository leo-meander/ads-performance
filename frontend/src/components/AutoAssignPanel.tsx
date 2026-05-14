'use client'

import { useState } from 'react'
import { Sparkles, X, Check } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface MatchedKeypoint { id: string; title: string; category: string }
interface ProposedKeypoint { title: string; category: string; rationale: string }
interface SuggestAngle { angle_id: string; angle_type: string; confidence: number | null; rationale: string }

interface Suggestion {
  source: string
  angle: SuggestAngle | null
  keypoints: { matched: MatchedKeypoint[]; proposed: ProposedKeypoint[] }
}

export interface AutoAssignResult {
  angle_id: string | null
  keypoint_ids: string[]
  created_keypoints: MatchedKeypoint[]
}

interface Props {
  branchId: string
  headline?: string
  bodyText?: string
  onResult: (r: AutoAssignResult) => void
  onClose: () => void
}

/**
 * Suggest → confirm panel for angle + keypoint auto-assignment.
 *
 * Calls /api/creative/autoassign/suggest with the ad's headline + body (or a
 * pasted video script). The user reviews the suggested angle, the matched
 * existing keypoints, and any PROPOSED new keypoints — nothing is created
 * until "Use these" is pressed, at which point confirmed new keypoints are
 * created via /api/keypoints and the full selection is bubbled up.
 */
export default function AutoAssignPanel({ branchId, headline, bodyText, onResult, onClose }: Props) {
  const [script, setScript] = useState('')
  const [loading, setLoading] = useState(false)
  const [applying, setApplying] = useState(false)
  const [err, setErr] = useState('')
  const [sug, setSug] = useState<Suggestion | null>(null)

  // selection state
  const [useAngle, setUseAngle] = useState(true)
  const [matchedSel, setMatchedSel] = useState<Record<string, boolean>>({})
  const [proposedSel, setProposedSel] = useState<Record<number, boolean>>({})

  const runSuggest = async () => {
    setErr('')
    setLoading(true)
    setSug(null)
    try {
      const body: Record<string, unknown> = { branch_id: branchId }
      if (script.trim()) {
        body.script_text = script.trim()
      } else {
        if (headline) body.headline = headline
        if (bodyText) body.body_text = bodyText
      }
      const r = await fetch(`${API_BASE}/api/creative/autoassign/suggest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })
      const d = await r.json()
      if (!d.success) { setErr(d.error || 'Suggest failed'); return }
      const s: Suggestion = d.data
      setSug(s)
      setUseAngle(!!s.angle)
      setMatchedSel(Object.fromEntries(s.keypoints.matched.map(k => [k.id, true])))
      setProposedSel(Object.fromEntries(s.keypoints.proposed.map((_, i) => [i, true])))
    } catch {
      setErr('Network error')
    } finally {
      setLoading(false)
    }
  }

  const confirm = async () => {
    if (!sug) return
    setApplying(true)
    setErr('')
    try {
      // Create the confirmed proposed keypoints.
      const created: MatchedKeypoint[] = []
      for (let i = 0; i < sug.keypoints.proposed.length; i++) {
        if (!proposedSel[i]) continue
        const p = sug.keypoints.proposed[i]
        const r = await fetch(`${API_BASE}/api/keypoints`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ branch_id: branchId, category: p.category, title: p.title }),
        })
        const d = await r.json()
        if (d.success) created.push({ id: d.data.id, title: d.data.title, category: d.data.category })
      }
      const matchedIds = sug.keypoints.matched.filter(k => matchedSel[k.id]).map(k => k.id)
      onResult({
        angle_id: useAngle && sug.angle ? sug.angle.angle_id : null,
        keypoint_ids: [...matchedIds, ...created.map(c => c.id)],
        created_keypoints: created,
      })
    } catch {
      setErr('Failed to create keypoints')
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl w-full max-w-lg max-h-[85vh] overflow-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-purple-600" /> Auto-assign angle &amp; keypoints
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {!sug && (
            <>
              <p className="text-sm text-gray-600">
                Claude reads the ad text and suggests one of the 13 angles + matching keypoints.
                Existing keypoints are reused; genuinely new ones are proposed for you to confirm.
              </p>
              {(headline || bodyText) && !script.trim() && (
                <div className="text-xs text-gray-500 bg-gray-50 rounded p-2">
                  Source: {headline && <span className="font-medium">{headline}</span>}
                  {bodyText && <span className="block mt-0.5 line-clamp-2">{bodyText}</span>}
                </div>
              )}
              <div>
                <label className="block text-xs text-gray-500 mb-1">
                  Or paste a video script (overrides the ad text above)
                </label>
                <textarea
                  value={script}
                  onChange={e => setScript(e.target.value)}
                  rows={4}
                  placeholder="Paste the full video script here for video content…"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm resize-none"
                />
              </div>
              {err && <p className="text-sm text-red-600">{err}</p>}
              <button
                onClick={runSuggest}
                disabled={loading || (!headline && !bodyText && !script.trim())}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
              >
                <Sparkles className="w-4 h-4" /> {loading ? 'Analyzing…' : 'Suggest'}
              </button>
            </>
          )}

          {sug && (
            <>
              <p className="text-xs text-gray-400">Analyzed from: {sug.source}</p>

              {/* Angle */}
              <div>
                <div className="text-xs font-medium text-gray-500 mb-1.5">Suggested angle</div>
                {sug.angle ? (
                  <label className="flex items-start gap-2 p-2.5 rounded border border-gray-200 cursor-pointer">
                    <input type="checkbox" checked={useAngle} onChange={e => setUseAngle(e.target.checked)} className="mt-0.5" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-gray-900">
                        {sug.angle.angle_id} — {sug.angle.angle_type}
                        {sug.angle.confidence != null && (
                          <span className="text-xs text-gray-400 ml-1">{(sug.angle.confidence * 100).toFixed(0)}%</span>
                        )}
                      </div>
                      {sug.angle.rationale && <div className="text-xs text-gray-500 mt-0.5">{sug.angle.rationale}</div>}
                    </div>
                  </label>
                ) : (
                  <p className="text-sm text-gray-400">No confident angle match.</p>
                )}
              </div>

              {/* Matched keypoints */}
              <div>
                <div className="text-xs font-medium text-gray-500 mb-1.5">
                  Existing keypoints ({sug.keypoints.matched.length})
                </div>
                {sug.keypoints.matched.length === 0 ? (
                  <p className="text-sm text-gray-400">None matched.</p>
                ) : (
                  <div className="space-y-1">
                    {sug.keypoints.matched.map(k => (
                      <label key={k.id} className="flex items-center gap-2 text-sm p-1.5 rounded hover:bg-gray-50 cursor-pointer">
                        <input type="checkbox" checked={!!matchedSel[k.id]}
                          onChange={e => setMatchedSel(p => ({ ...p, [k.id]: e.target.checked }))} />
                        <span className="text-xs text-gray-400">[{k.category}]</span>
                        <span className="text-gray-700">{k.title}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              {/* Proposed new keypoints */}
              <div>
                <div className="text-xs font-medium text-gray-500 mb-1.5">
                  Proposed NEW keypoints ({sug.keypoints.proposed.length})
                  {sug.keypoints.proposed.length > 0 && (
                    <span className="text-gray-400 font-normal"> — will be created on confirm</span>
                  )}
                </div>
                {sug.keypoints.proposed.length === 0 ? (
                  <p className="text-sm text-gray-400">None — existing keypoints covered everything.</p>
                ) : (
                  <div className="space-y-1">
                    {sug.keypoints.proposed.map((p, i) => (
                      <label key={i} className="flex items-start gap-2 text-sm p-1.5 rounded hover:bg-amber-50 cursor-pointer">
                        <input type="checkbox" checked={!!proposedSel[i]}
                          onChange={e => setProposedSel(s => ({ ...s, [i]: e.target.checked }))} className="mt-0.5" />
                        <span className="text-xs px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">{p.category}</span>
                        <div className="min-w-0">
                          <span className="text-gray-800">{p.title}</span>
                          {p.rationale && <div className="text-xs text-gray-400">{p.rationale}</div>}
                        </div>
                      </label>
                    ))}
                  </div>
                )}
              </div>

              {err && <p className="text-sm text-red-600">{err}</p>}

              <div className="flex gap-2 pt-2 border-t border-gray-100">
                <button
                  onClick={confirm}
                  disabled={applying}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
                >
                  <Check className="w-4 h-4" /> {applying ? 'Applying…' : 'Use these'}
                </button>
                <button onClick={() => setSug(null)} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded">
                  Re-run
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
