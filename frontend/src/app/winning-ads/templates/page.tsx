'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, ExternalLink, Plus, RefreshCw, Image as ImageIcon, Trash2 } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Account { id: string; account_name: string; platform: string }

interface Template {
  id: string
  name: string
  file_key: string
  node_id: string
  branch_id: string | null
  platform: string
  width: number
  height: number
  placeholder_schema: Record<string, { type: string; figma_layer?: string; current?: string }>
  preview_image_url: string | null
  is_active: boolean
  deep_link: string
}

export default function FigmaTemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

  // register form
  const [name, setName] = useState('')
  const [figmaUrl, setFigmaUrl] = useState('')
  const [fileKey, setFileKey] = useState('')
  const [nodeId, setNodeId] = useState('')
  const [branchId, setBranchId] = useState('')
  const [platform, setPlatform] = useState('meta')
  const [width, setWidth] = useState(1080)
  const [height, setHeight] = useState(1080)
  const [saving, setSaving] = useState(false)
  const [formErr, setFormErr] = useState('')

  // Parse a Figma share URL into the file_key + node_id the API needs.
  // Handles /file/, /design/, and /proto/ paths. node-id in the URL uses a
  // dash (143-22) but the REST API expects a colon (143:22).
  const parseFigmaUrl = (url: string): { fileKey?: string; nodeId?: string } => {
    try {
      const u = new URL(url.trim())
      const m = u.pathname.match(/\/(?:file|design|proto)\/([^/]+)/)
      const fk = m ? m[1] : undefined
      const raw = u.searchParams.get('node-id') || undefined
      const nid = raw ? raw.replace(/-/g, ':') : undefined
      return { fileKey: fk, nodeId: nid }
    } catch {
      return {}
    }
  }

  const onFigmaUrlChange = (val: string) => {
    setFigmaUrl(val)
    if (!val.trim()) return
    const { fileKey: fk, nodeId: nid } = parseFigmaUrl(val)
    if (fk) setFileKey(fk)
    if (nid) setNodeId(nid)
  }

  const load = () => {
    setLoading(true)
    fetch(`${API_BASE}/api/figma/templates`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setTemplates(d.data.items || []) })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setAccounts(d.data.filter((a: Account) => a.platform === 'meta')) })
  }, [])

  const register = async () => {
    if (!name.trim() || !fileKey.trim() || !nodeId.trim()) {
      setFormErr('Name, file_key and node_id are required')
      return
    }
    setSaving(true)
    setFormErr('')
    try {
      const r = await fetch(`${API_BASE}/api/figma/templates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          name, file_key: fileKey, node_id: nodeId,
          branch_id: branchId || null, platform, width, height,
        }),
      })
      const d = await r.json()
      if (!d.success) { setFormErr(d.error || 'Failed'); return }
      setName(''); setFigmaUrl(''); setFileKey(''); setNodeId(''); setBranchId('')
      setShowForm(false)
      load()
    } finally {
      setSaving(false)
    }
  }

  const action = async (id: string, path: string, method = 'POST') => {
    setBusyId(id)
    try {
      await fetch(`${API_BASE}/api/figma/templates/${id}${path}`, { method, credentials: 'include' })
      load()
    } finally {
      setBusyId(null)
    }
  }

  const branchName = (id: string | null) =>
    id ? (accounts.find(a => a.id === id)?.account_name || 'Unknown branch') : 'Shared (all branches)'

  return (
    <div className="p-6 max-w-5xl">
      <Link href="/winning-ads" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline mb-4">
        <ArrowLeft className="w-4 h-4" /> Back to Figma
      </Link>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Figma Templates</h1>
          <p className="text-sm text-gray-500 mt-1">
            Master frames the AI brief recommends. Layers prefixed <code className="bg-gray-100 px-1 rounded">$</code> become fillable slots.
          </p>
        </div>
        <button
          onClick={() => setShowForm(s => !s)}
          className="inline-flex items-center gap-1.5 px-3 py-2 text-sm bg-gray-900 text-white rounded hover:bg-gray-800"
        >
          <Plus className="w-4 h-4" /> Register template
        </button>
      </div>

      {showForm && (
        <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
          <h2 className="text-sm font-semibold text-gray-800 mb-3">Register a Figma master frame</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <div className="lg:col-span-3">
              <label className="text-xs text-gray-600 block mb-1">Name *</label>
              <input className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                placeholder="saigon_meta_1080x1080_hero" value={name} onChange={e => setName(e.target.value)} />
            </div>
            <div className="lg:col-span-3">
              <label className="text-xs text-gray-600 block mb-1">
                Figma link <span className="text-gray-400 font-normal">(paste — file_key + node_id auto-extract)</span>
              </label>
              <input className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                placeholder="https://www.figma.com/design/2Z6hfcKRPZfgnRVCID3qtN/MEANDER-Layout?node-id=143-22"
                value={figmaUrl} onChange={e => onFigmaUrlChange(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">file_key *</label>
              <input className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono"
                placeholder="tl4dA72nWVB6oK74RQpgVe" value={fileKey} onChange={e => setFileKey(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">node_id *</label>
              <input className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono"
                placeholder="4:52" value={nodeId} onChange={e => setNodeId(e.target.value)} />
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">Branch</label>
              <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={branchId} onChange={e => setBranchId(e.target.value)}>
                <option value="">Shared (all branches)</option>
                {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">Platform</label>
              <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={platform} onChange={e => setPlatform(e.target.value)}>
                <option value="meta">Meta</option>
                <option value="google">Google PMax</option>
                <option value="tiktok">TikTok</option>
              </select>
            </div>
            <div className="flex gap-2">
              <div className="flex-1">
                <label className="text-xs text-gray-600 block mb-1">Width</label>
                <input type="number" className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  value={width} onChange={e => setWidth(Number(e.target.value))} />
              </div>
              <div className="flex-1">
                <label className="text-xs text-gray-600 block mb-1">Height</label>
                <input type="number" className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
                  value={height} onChange={e => setHeight(Number(e.target.value))} />
              </div>
            </div>
          </div>
          {formErr && <p className="text-sm text-red-600 mt-3">{formErr}</p>}
          <div className="flex gap-2 mt-4">
            <button onClick={register} disabled={saving}
              className="px-4 py-2 text-sm bg-gray-900 text-white rounded hover:bg-gray-800 disabled:opacity-50">
              {saving ? 'Registering…' : 'Register'}
            </button>
            <button onClick={() => setShowForm(false)} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded">
              Cancel
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-3">
            Placeholders auto-inferred from <code className="bg-gray-100 px-1 rounded">$</code>-prefixed layers in the frame.
          </p>
        </div>
      )}

      {loading ? (
        <p className="text-gray-500">Loading…</p>
      ) : templates.length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-lg p-12 text-center text-gray-500">
          No templates yet. Register a Figma master frame to get started.
        </div>
      ) : (
        <div className="space-y-3">
          {templates.map(t => {
            const slots = Object.entries(t.placeholder_schema || {})
            return (
              <div key={t.id} className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="flex items-start gap-4">
                  {/* Preview */}
                  <div className="w-32 h-32 shrink-0 bg-gray-50 border border-gray-100 rounded flex items-center justify-center overflow-hidden">
                    {t.preview_image_url ? (
                      <img src={t.preview_image_url} alt="" className="w-full h-full object-contain" />
                    ) : (
                      <ImageIcon className="w-8 h-8 text-gray-300" />
                    )}
                  </div>

                  {/* Body */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-gray-900">{t.name}</h3>
                      <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600">{t.platform}</span>
                      <span className="text-xs text-gray-400">{t.width}×{t.height}</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">{branchName(t.branch_id)}</div>
                    <div className="text-xs text-gray-400 font-mono mt-0.5">{t.file_key} · {t.node_id}</div>

                    {/* Slots */}
                    <div className="mt-2">
                      {slots.length === 0 ? (
                        <span className="text-xs text-yellow-700 bg-yellow-50 px-2 py-0.5 rounded">
                          No $-prefixed slots found — rename layers in Figma then Refresh schema
                        </span>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {slots.map(([slug, meta]) => (
                            <span key={slug}
                              className={`text-xs px-2 py-0.5 rounded border ${
                                meta.type === 'image'
                                  ? 'bg-blue-50 text-blue-700 border-blue-200'
                                  : 'bg-green-50 text-green-700 border-green-200'
                              }`}
                              title={meta.figma_layer ? `Figma layer: ${meta.figma_layer}` : undefined}
                            >
                              {slug}<span className="opacity-50 ml-1">{meta.type}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex flex-col gap-1.5 shrink-0">
                    <a href={t.deep_link} target="_blank" rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50">
                      Open in Figma <ExternalLink className="w-3 h-3" />
                    </a>
                    <button onClick={() => action(t.id, '/refresh-schema')} disabled={busyId === t.id}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50">
                      <RefreshCw className={`w-3 h-3 ${busyId === t.id ? 'animate-spin' : ''}`} /> Refresh schema
                    </button>
                    <button onClick={() => action(t.id, '/refresh-preview')} disabled={busyId === t.id}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50">
                      <ImageIcon className="w-3 h-3" /> Refresh preview
                    </button>
                    <button
                      onClick={() => { if (confirm(`Deactivate template "${t.name}"?`)) action(t.id, '', 'DELETE') }}
                      disabled={busyId === t.id}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-red-200 text-red-600 rounded hover:bg-red-50 disabled:opacity-50">
                      <Trash2 className="w-3 h-3" /> Deactivate
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
