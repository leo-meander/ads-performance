'use client'

import { useEffect, useState } from 'react'
import { X, Send, ImageIcon, Search } from 'lucide-react'

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
  platform: string
  width: number
  height: number
  placeholder_schema: Record<string, { type?: string; figma_layer?: string }>
}

interface LibraryImage {
  combo_id: string
  material_id: string | null
  file_url: string | null
  headline: string | null
  verdict: string
  roas: number | null
}

interface Props {
  brief: Brief
  branchId: string
  onClose: () => void
  onQueued: (jobId: string) => void
}

// Tag dropdowns for the image picker (mirrors creative_vision_tagger.TAG_VOCAB).
const PICKER_TAGS: { category: string; label: string; values: string[] }[] = [
  { category: 'human_presence', label: 'People', values: ['solo', 'couple', 'group', 'none'] },
  { category: 'scene_type', label: 'Scene', values: ['room', 'exterior', 'food', 'activity', 'aerial', 'abstract', 'mixed'] },
  { category: 'color_palette', label: 'Palette', values: ['warm', 'cool', 'neutral', 'high_contrast', 'pastel', 'dark', 'other'] },
  { category: 'emotional_angle', label: 'Emotion', values: ['aspirational', 'calm', 'urgency', 'informational', 'playful', 'luxe', 'other'] },
]

/**
 * Maps an AI brief variant onto a Figma template's $-prefixed slots and queues
 * a render job. Text slots auto-fill from the brief; image slots can be filled
 * from a URL or picked from the branch's vision-tagged creative library —
 * pre-seeded from the brief's visual_direction.
 */
export default function SendToFigmaModal({ brief, branchId, onClose, onQueued }: Props) {
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [templateId, setTemplateId] = useState('')
  const [values, setValues] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState('')

  // Image picker state — `pickerSlot` is the slug whose image we're choosing.
  const [pickerSlot, setPickerSlot] = useState<string | null>(null)
  const [pickerTags, setPickerTags] = useState<Record<string, string>>({})
  const [pickerResults, setPickerResults] = useState<LibraryImage[]>([])
  const [pickerLoading, setPickerLoading] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams()
    if (branchId) params.set('branch_id', branchId)
    fetch(`${API_BASE}/api/figma/templates?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setTemplates(d.data.items || []) })
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

  // ── Image picker ──────────────────────────────────────────

  const openPicker = (slug: string) => {
    // Seed the tag filters from the brief's visual_direction.
    const vd = brief.visual_direction || {}
    setPickerTags({
      human_presence: vd.human_presence || '',
      scene_type: vd.scene || '',
      color_palette: vd.color_palette || '',
      emotional_angle: vd.emotional_angle || '',
    })
    setPickerResults([])
    setPickerSlot(slug)
  }

  const runPickerSearch = () => {
    setPickerLoading(true)
    const params = new URLSearchParams({ match: 'all', limit: '40' })
    if (branchId) params.set('branch_id', branchId)
    Object.entries(pickerTags).forEach(([cat, val]) => {
      if (val) params.append('tags', `${cat}:${val}`)
    })
    fetch(`${API_BASE}/api/creative/search?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          // Keep one entry per distinct image.
          const seen = new Set<string>()
          const imgs: LibraryImage[] = []
          for (const it of d.data.items || []) {
            if (!it.file_url || seen.has(it.file_url)) continue
            seen.add(it.file_url)
            imgs.push(it)
          }
          setPickerResults(imgs)
        }
      })
      .finally(() => setPickerLoading(false))
  }

  // Auto-run the search when the picker opens with seeded tags.
  useEffect(() => {
    if (pickerSlot) runPickerSearch()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickerSlot])

  const pickImage = (url: string) => {
    if (pickerSlot) setValues(v => ({ ...v, [pickerSlot]: url }))
    setPickerSlot(null)
  }

  // ── Submit ────────────────────────────────────────────────

  const submit = async () => {
    if (!templateId) { setErr('Pick a template'); return }
    setErr('')
    setSubmitting(true)
    try {
      const payload: Record<string, string> = {}
      Object.entries(values).forEach(([k, v]) => { if (v && v.trim()) payload[k] = v.trim() })

      const r = await fetch(`${API_BASE}/api/figma/jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ template_id: templateId, request_payload: payload }),
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
                    Slot values — text auto-filled from the brief; images from the library or a URL
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
                            </label>
                            <div className="flex gap-1.5">
                              <input
                                className="flex-1 border border-gray-200 rounded px-2.5 py-1.5 text-sm"
                                placeholder={isImage ? 'Image URL — or pick from library →' : 'Leave empty to skip'}
                                value={values[slug] || ''}
                                onChange={e => setValues(v => ({ ...v, [slug]: e.target.value }))}
                              />
                              {isImage && (
                                <button
                                  type="button"
                                  onClick={() => openPicker(slug)}
                                  className="inline-flex items-center gap-1 px-2 py-1.5 text-xs border border-blue-200 text-blue-700 rounded hover:bg-blue-50 whitespace-nowrap"
                                >
                                  <ImageIcon className="w-3.5 h-3.5" /> Library
                                </button>
                              )}
                            </div>
                            {isImage && values[slug] && (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={values[slug]} alt="" className="mt-1 h-16 rounded border border-gray-100 object-cover" />
                            )}
                          </div>
                        )
                      })}
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
                Queues a job. A designer runs the MEANDER Figma plugin to generate the frame.
              </p>
            </>
          )}
        </div>
      </div>

      {/* Image library picker — nested overlay */}
      {pickerSlot && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[60] p-4">
          <div className="bg-white rounded-xl w-full max-w-2xl max-h-[85vh] overflow-auto">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white">
              <h3 className="text-sm font-semibold text-gray-900">
                Pick image for <span className="font-mono">{pickerSlot}</span>
              </h3>
              <button onClick={() => setPickerSlot(null)} className="text-gray-400 hover:text-gray-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 space-y-3">
              <p className="text-xs text-gray-500">
                Searches this branch&apos;s vision-tagged materials. Tags are seeded from the brief&apos;s
                visual direction — adjust and search again.
              </p>
              <div className="flex flex-wrap gap-2">
                {PICKER_TAGS.map(tf => (
                  <select
                    key={tf.category}
                    className="border border-gray-300 rounded px-2.5 py-1.5 text-sm"
                    value={pickerTags[tf.category] || ''}
                    onChange={e => setPickerTags(p => ({ ...p, [tf.category]: e.target.value }))}
                  >
                    <option value="">{tf.label}: any</option>
                    {tf.values.map(v => <option key={v} value={v}>{tf.label}: {v}</option>)}
                  </select>
                ))}
                <button
                  onClick={runPickerSearch}
                  className="inline-flex items-center gap-1 px-3 py-1.5 text-sm bg-gray-900 text-white rounded hover:bg-gray-800"
                >
                  <Search className="w-3.5 h-3.5" /> Search
                </button>
              </div>

              {pickerLoading ? (
                <p className="text-sm text-gray-400">Searching…</p>
              ) : pickerResults.length === 0 ? (
                <p className="text-sm text-gray-500 py-6 text-center">
                  No matching images in the library. Loosen the tags, or paste a URL directly —
                  hotel room photos can&apos;t be AI-generated, they need to be real.
                </p>
              ) : (
                <div className="grid grid-cols-3 gap-2">
                  {pickerResults.map(img => (
                    <button
                      key={img.combo_id}
                      onClick={() => img.file_url && pickImage(img.file_url)}
                      className="group border border-gray-200 rounded overflow-hidden hover:border-purple-400 text-left"
                      title={img.headline || img.material_id || ''}
                    >
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={img.file_url || ''} alt="" className="w-full h-24 object-cover" />
                      <div className="px-1.5 py-1">
                        <div className="text-[10px] text-gray-500 truncate">{img.headline || img.material_id}</div>
                        <div className="text-[10px] text-gray-400">
                          {img.verdict}{img.roas != null ? ` · ROAS ${img.roas.toFixed(1)}` : ''}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
