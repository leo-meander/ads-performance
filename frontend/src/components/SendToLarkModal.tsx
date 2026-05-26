'use client'

import { useEffect, useMemo, useState } from 'react'
import { X, ListChecks } from 'lucide-react'

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
  angle?: string
  keypoints: string[]
  visual_direction?: VisualDirection
}

interface Template {
  id: string
  name: string
  width: number
  height: number
  deep_link?: string
}

interface Props {
  brief: Brief
  branchId: string
  branchName: string
  country?: string
  ta?: string
  onClose: () => void
  onCreated: (recordId: string, taskName: string) => void
}

// Branch → square-bracket tag used in the "Tasks" board (from the CSV rule:
// names start with [1948] / [Oani] / [Osaka] / [Saigon] / [Taipei] / [Bread]).
function branchTag(branchName: string): string {
  const n = (branchName || '').toLowerCase()
  if (n.includes('1948')) return '1948'
  if (n.includes('oani')) return 'Oani'
  if (n.includes('osaka')) return 'Osaka'
  if (n.includes('saigon')) return 'Saigon'
  if (n.includes('taipei')) return 'Taipei'
  if (n.includes('bread')) return 'Bread'
  return branchName || 'Task'
}

// Compose a Task name following the CSV naming rule:
//   [Branch] <Format>_<Country> - <TA> - <Theme>
// Format defaults to "Image" (the common case) — the field stays editable so
// the designer can switch to Video / Carousel / aspect ratios etc.
function suggestTaskName(brief: Brief, branchName: string, country?: string, ta?: string): string {
  const tag = branchTag(branchName)
  const loc = (country || '').toUpperCase()
  const head = loc ? `Image_${loc}` : 'Image'
  const segs = [head]
  if (ta) segs.push(ta)
  if (brief.title) segs.push(brief.title)
  return `[${tag}] ${segs.join(' - ')}`
}

function formatVisualDirection(vd?: VisualDirection): string {
  if (!vd) return ''
  const parts: string[] = []
  if (vd.scene) parts.push(`scene: ${vd.scene}`)
  if (vd.human_presence) parts.push(`people: ${vd.human_presence}`)
  if (vd.color_palette) parts.push(`palette: ${vd.color_palette}`)
  if (vd.emotional_angle) parts.push(`emotion: ${vd.emotional_angle}`)
  return parts.join(' · ')
}

// Full brief details → the "Description" column. Includes the chosen Figma
// template (name + size + deep link) so the designer has the file to start from.
function buildDescription(brief: Brief, template?: Template): string {
  const blocks: string[] = []
  if (brief.hook) blocks.push(`Hook: ${brief.hook}`)
  if (brief.subhead) blocks.push(`Subhead: ${brief.subhead}`)
  if (brief.cta) blocks.push(`CTA: ${brief.cta}`)
  if (brief.angle) blocks.push(`Angle: ${brief.angle}`)
  if (brief.keypoints?.length) {
    blocks.push(`Keypoints:\n${brief.keypoints.map(k => `- ${k}`).join('\n')}`)
  }
  const vd = formatVisualDirection(brief.visual_direction)
  if (vd) blocks.push(`Visual direction: ${vd}`)
  if (template) {
    const link = template.deep_link ? `\n${template.deep_link}` : ''
    blocks.push(`Figma template: ${template.name} (${template.width}×${template.height})${link}`)
  }
  return blocks.join('\n\n')
}

/**
 * Mirrors SendToFigmaModal, but the destination is the Lark Base "Tasks" table.
 * Composes a Task name (CSV rule) + a Description (brief details + the chosen
 * Figma template), both editable, then POSTs to /api/lark/tasks.
 */
export default function SendToLarkModal({ brief, branchId, branchName, country, ta, onClose, onCreated }: Props) {
  const [templates, setTemplates] = useState<Template[]>([])
  const [loadingTpl, setLoadingTpl] = useState(true)
  const [templateId, setTemplateId] = useState('')
  const [taskName, setTaskName] = useState(() => suggestTaskName(brief, branchName, country, ta))
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    const params = new URLSearchParams()
    if (branchId) params.set('branch_id', branchId)
    fetch(`${API_BASE}/api/figma/templates?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setTemplates(d.data.items || []) })
      .finally(() => setLoadingTpl(false))
  }, [branchId])

  const tpl = useMemo(() => templates.find(t => t.id === templateId), [templates, templateId])

  // (Re)seed the description whenever the chosen template changes. Mirrors the
  // Figma modal's reseed-on-template-change behaviour.
  useEffect(() => {
    setDescription(buildDescription(brief, tpl))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId, templates.length])

  const submit = async () => {
    if (!taskName.trim()) { setErr('Task name is required'); return }
    setErr('')
    setSubmitting(true)
    try {
      const r = await fetch(`${API_BASE}/api/lark/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          branch_id: branchId,
          task_name: taskName.trim(),
          description,
        }),
      })
      const d = await r.json()
      if (!d.success) { setErr(d.error || 'Failed to create Lark task'); return }
      onCreated(d.data.record_id || '', d.data.task_name || taskName.trim())
    } catch {
      setErr('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl w-full max-w-lg max-h-[85vh] overflow-auto">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <ListChecks className="w-4 h-4 text-blue-600" /> Send to Lark — {brief.title}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div>
            <label className="text-xs text-gray-600 block mb-1">Task name</label>
            <input
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono"
              value={taskName}
              onChange={e => setTaskName(e.target.value)}
            />
            <p className="text-[11px] text-gray-400 mt-0.5">
              Rule: [Branch] Format_Country - TA - Theme. Edit Format/aspect ratio as needed.
            </p>
          </div>

          <div>
            <label className="text-xs text-gray-600 block mb-1">
              Figma template {loadingTpl ? '(loading…)' : `(${templates.length})`}
            </label>
            <select
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              value={templateId}
              onChange={e => setTemplateId(e.target.value)}
            >
              <option value="">— no template —</option>
              {templates.map(t => (
                <option key={t.id} value={t.id}>{t.name} ({t.width}×{t.height})</option>
              ))}
            </select>
            <p className="text-[11px] text-gray-400 mt-0.5">
              Adds the template name + link into the Description. Changing it rewrites the Description.
            </p>
          </div>

          <div>
            <label className="text-xs text-gray-600 block mb-1">Description (goes into the Tasks board)</label>
            <textarea
              className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono h-56"
              value={description}
              onChange={e => setDescription(e.target.value)}
            />
          </div>

          <p className="text-[11px] text-gray-400">
            Auto-set on create: PIC nora@staymeander.com · Status “Not started” · Project “[branch] Ads”.
          </p>

          {err && <p className="text-sm text-red-600">{err}</p>}

          <div className="flex gap-2 pt-2 border-t border-gray-100">
            <button
              onClick={submit}
              disabled={submitting || !taskName.trim()}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
            >
              <ListChecks className="w-4 h-4" /> {submitting ? 'Creating…' : 'Create Lark task'}
            </button>
            <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded">
              Cancel
            </button>
          </div>
          <p className="text-xs text-gray-400">
            Creates a row in the Lark Base “Tasks” table. The designer picks it up there.
          </p>
        </div>
      </div>
    </div>
  )
}
