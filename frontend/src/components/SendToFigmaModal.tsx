'use client'

import { useEffect, useState } from 'react'
import { X, Send } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface VisualDirection {
  scene?: string
  human_presence?: string
  color_palette?: string
  emotional_angle?: string
}

interface Brief {
  title: string
  hook: string
  subhead: string
  cta: string
  keypoints: string[]
  visual_direction?: VisualDirection
}

interface Template {
  id: string
  name: string
  branch_id?: string | null
  platform: string
  width: number
  height: number
  placeholder_schema: Record<string, { type?: string; figma_layer?: string }>
}

interface Props {
  brief: Brief
  branchId: string
  // The winning ad this brief is reused from. Recorded on the render job as
  // source_combo_id so the combo surfaces under the Figma list's "Figma only".
  sourceComboId?: string
  onClose: () => void
  onQueued: (jobId: string) => void
}

// Render the brief's visual_direction into a one-line note the designer sees
// in the Figma plugin log — tells them which photo to drop into image slots.
function formatVisualDirection(vd?: VisualDirection): string {
  if (!vd) return ''
  const parts: string[] = []
  if (vd.scene) parts.push(`scene: ${vd.scene}`)
  if (vd.human_presence) parts.push(`people: ${vd.human_presence}`)
  if (vd.color_palette) parts.push(`palette: ${vd.color_palette}`)
  if (vd.emotional_angle) parts.push(`emotion: ${vd.emotional_angle}`)
  return parts.join(' · ')
}

/**
 * Maps an AI brief variant onto a Figma template's $-prefixed slots and queues
 * a render job. Text slots auto-fill from the brief. Image slots are left for
 * the designer to fill by hand in Figma (Option 2) — an optional URL can still
 * be supplied, but the job always carries the brief's visual_direction as a
 * `_visual_direction` note so the designer knows which photo to place.
 */
export default function SendToFigmaModal({ brief, branchId, sourceComboId, onClose, onQueued }: Props) {
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [templateId, setTemplateId] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    const params = new URLSearchParams()
    if (branchId) params.set('branch_id', branchId)
    fetch(`${API_BASE}/api/figma/templates?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (!d.success) return
        const list: Template[] = d.data.items || []
        setTemplates(list)
        // Auto-select a template for this branch so the designer doesn't have
        // to. The API returns branch-scoped + shared templates ordered by
        // created_at, so prefer one whose branch_id matches; otherwise fall
        // back to the most recent (likely a shared master). Still overridable.
        const preferred = list.find(t => t.branch_id === branchId) || list[0]
        if (preferred) setTemplateId(prev => prev || preferred.id)
      })
      .finally(() => setLoading(false))
  }, [branchId])

  const tpl = templates.find(t => t.id === templateId)

  const autoFill = (slug: string): string => {
    const s = slug.toLowerCase()
    if (s === 'headline' || s === 'hook' || s === 'title') return brief.hook || ''
    if (s === 'subhead' || s === 'subheadline' || s === 'body') return brief.subhead || ''
    if (s === 'cta') return brief.cta || ''
    const m = s.match(/^benefit_?(\d+)$/)
    if (m) return brief.keypoints[parseInt(m[1], 10) - 1] || ''
    return ''
  }

  useEffect(() => {
    if (!tpl) { setValues({}); return }
    const seeded: Record<string, string> = {}
    Object.keys(tpl.placeholder_schema || {}).forEach(slug => {
      seeded[slug] = autoFill(slug)
    })
    setValues(seeded)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId])

  const visualDirection = formatVisualDirection(brief.visual_direction)

  // ── Submit ────────────────────────────────────────────────

  const submit = async () => {
    if (!templateId) { setErr('Pick a template'); return }
    setErr('')
    setSubmitting(true)
    try {
      const payload: Record<string, string> = {}
      Object.entries(values).forEach(([k, v]) => { if (v && v.trim()) payload[k] = v.trim() })
      // Always pass the brief's visual direction as a reserved note — the
      // plugin surfaces it so the designer knows which photo to place in the
      // image slots they fill manually.
      if (visualDirection) payload._visual_direction = visualDirection

      const r = await fetch(`${API_BASE}/api/figma/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          template_id: templateId,
          request_payload: payload,
          ...(sourceComboId ? { source_combo_id: sourceComboId } : {}),
        }),
      })
      const d = await r.json()
      if (!d.success) { setErr(d.error || 'Failed to queue job'); return }
      onQueued(d.data.id)
    } catch {
      setErr('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  const slots = tpl ? Object.entries(tpl.placeholder_schema || {}) : []

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl w-full max-w-lg max-h-[85vh] overflow-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Send className="w-4 h-4 text-purple-600" /> Send to Figma — {brief.title}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {loading ? (
            <p className="text-sm text-gray-400">Loading templates…</p>
          ) : templates.length === 0 ? (
            <p className="text-sm text-gray-500">
              No Figma templates for this branch. Register one in Figma Templates first.
            </p>
          ) : (
            <>
              <div>
                <label className="text-xs text-gray-600 block mb-1">Template</label>
                <select
                  className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  value={templateId}
                  onChange={e => setTemplateId(e.target.value)}
                >
                  <option value="">— pick a template —</option>
                  {templates.map(t => (
                    <option key={t.id} value={t.id}>
                      {t.name} ({t.width}×{t.height})
                    </option>
                  ))}
                </select>
              </div>

              {tpl && (
                <div>
                  <div className="text-xs font-medium text-gray-500 mb-2">
                    Slot values — text auto-filled from the brief; image slots are placed by the designer in Figma
                  </div>
                  {slots.length === 0 ? (
                    <p className="text-sm text-yellow-700 bg-yellow-50 px-2 py-1.5 rounded">
                      This template has no $-prefixed slots. Refresh its schema in Figma Templates.
                    </p>
                  ) : (
                    <div className="space-y-2">
                      {slots.map(([slug, meta]) => {
                        const isImage = meta.type === 'image'
                        return (
                          <div key={slug}>
                            <label className="text-xs text-gray-500 flex items-center gap-1.5 mb-0.5">
                              <span className="font-mono">{slug}</span>
                              <span className={`text-[10px] px-1 rounded ${
                                isImage ? 'bg-blue-100 text-blue-600' : 'bg-green-100 text-green-600'
                              }`}>{meta.type || 'text'}</span>
                              {isImage && (
                                <span className="text-[10px] text-gray-400">designer places this in Figma</span>
                              )}
                            </label>
                            <input
                              className="w-full border border-gray-200 rounded px-2.5 py-1.5 text-sm"
                              placeholder={isImage ? 'Optional image URL — leave empty for the designer to place' : 'Leave empty to skip'}
                              value={values[slug] || ''}
                              onChange={e => setValues(v => ({ ...v, [slug]: e.target.value }))}
                            />
                            {isImage && values[slug] && (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={values[slug]} alt="" className="mt-1 h-16 rounded border border-gray-100 object-cover" />
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}

                  {visualDirection && (
                    <div className="mt-3 text-xs bg-purple-50 border border-purple-100 rounded px-2.5 py-2">
                      <span className="font-medium text-purple-700">Visual direction</span>
                      <span className="text-purple-600"> — sent to the designer for image slots:</span>
                      <div className="text-purple-800 mt-0.5">{visualDirection}</div>
                    </div>
                  )}
                </div>
              )}

              {err && <p className="text-sm text-red-600">{err}</p>}

              <div className="flex gap-2 pt-2 border-t border-gray-100">
                <button
                  onClick={submit}
                  disabled={submitting || !templateId}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
                >
                  <Send className="w-4 h-4" /> {submitting ? 'Queuing…' : 'Queue render job'}
                </button>
                <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded">
                  Cancel
                </button>
              </div>
              <p className="text-xs text-gray-400">
                Queues a job. A designer runs the MEANDER Figma plugin to fill the text, then places the room/scene photos by hand.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
