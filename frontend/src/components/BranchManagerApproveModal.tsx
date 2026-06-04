'use client'

import { useEffect, useRef, useState } from 'react'
import { X, Check, ImageUp, ClipboardPaste } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

// Keep client-side cap below the backend's (~6 MB binary) with margin so a
// rejected paste is caught here with a friendly message instead of a 400.
const MAX_BYTES = 5 * 1024 * 1024

interface Props {
  // Full API path that records the branch-manager approval, e.g.
  // /api/approvals/{id}/branch-manager-approve or the batch variant.
  endpoint: string
  // What's being approved — shown in the header (combo name / batch label).
  title: string
  onClose: () => void
  // Called with the refreshed approval/batch detail returned by the endpoint.
  onApproved: (data: unknown) => void
}

/**
 * Records a branch-manager sign-off: paste (Ctrl+V) or drop/choose a screenshot
 * of the manager's approval, then confirm. The combo is marked APPROVED with the
 * screenshot stored as proof — no reviewer round needed.
 */
export default function BranchManagerApproveModal({ endpoint, title, onClose, onApproved }: Props) {
  const [image, setImage] = useState('')        // base64 data URL
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState('')
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const zoneRef = useRef<HTMLDivElement>(null)

  // Focus the drop zone on open so Ctrl+V lands here immediately.
  useEffect(() => { zoneRef.current?.focus() }, [])

  const readFile = (file: File) => {
    if (!file.type.startsWith('image/')) {
      setErr('That’s not an image — paste or pick a screenshot.')
      return
    }
    if (file.size > MAX_BYTES) {
      setErr('Image is too large (max 5 MB). Crop or re-screenshot a smaller area.')
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      setErr('')
      setImage(typeof reader.result === 'string' ? reader.result : '')
    }
    reader.onerror = () => setErr('Could not read that image.')
    reader.readAsDataURL(file)
  }

  const onPaste = (e: React.ClipboardEvent) => {
    const item = Array.from(e.clipboardData.items).find(i => i.type.startsWith('image/'))
    if (item) {
      const file = item.getAsFile()
      if (file) { e.preventDefault(); readFile(file) }
    }
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    if (file) readFile(file)
  }

  const submit = async () => {
    if (!image) { setErr('Paste or choose a screenshot first.'); return }
    setErr('')
    setSubmitting(true)
    try {
      const r = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ proof_image: image }),
      })
      const d = await r.json()
      if (!d.success) { setErr(d.error || 'Failed to record approval'); return }
      onApproved(d.data)
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
            <Check className="w-4 h-4 text-green-600" /> Branch Manager approved — {title}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <p className="text-xs text-gray-500">
            Paste the screenshot of the branch manager&apos;s approval (Ctrl+V), or choose / drag a file.
            Confirming marks this <span className="font-medium text-gray-700">APPROVED</span> and stores the screenshot as proof.
          </p>

          {!image ? (
            <div
              ref={zoneRef}
              tabIndex={0}
              onPaste={onPaste}
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-10 text-center cursor-pointer outline-none transition-colors ${
                dragOver ? 'border-green-400 bg-green-50' : 'border-gray-300 hover:border-green-300 focus:border-green-400 focus:bg-green-50/40'
              }`}
            >
              <ClipboardPaste className="w-6 h-6 text-gray-400" />
              <p className="text-sm font-medium text-gray-600">Paste screenshot here (Ctrl+V)</p>
              <p className="text-xs text-gray-400">or click to choose a file · drag &amp; drop</p>
            </div>
          ) : (
            <div className="space-y-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={image} alt="Branch manager approval" className="w-full rounded-lg border border-gray-200 max-h-80 object-contain bg-gray-50" />
              <button
                onClick={() => { setImage(''); setErr(''); setTimeout(() => zoneRef.current?.focus(), 0) }}
                className="inline-flex items-center gap-1.5 text-xs font-medium text-gray-600 hover:text-gray-800"
              >
                <ImageUp className="w-3.5 h-3.5" /> Replace screenshot
              </button>
            </div>
          )}

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) readFile(f); e.target.value = '' }}
          />

          {err && <p className="text-sm text-red-600">{err}</p>}

          <div className="flex gap-2 pt-2 border-t border-gray-100">
            <button
              onClick={submit}
              disabled={submitting || !image}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50"
            >
              <Check className="w-4 h-4" /> {submitting ? 'Saving…' : 'Confirm approval'}
            </button>
            <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded">
              Cancel
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
