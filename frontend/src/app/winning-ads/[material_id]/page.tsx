'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, ExternalLink, Sparkles, Settings, Plus, X } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Combo {
  combo_id: string
  ad_name: string | null
  verdict: string
  target_audience: string | null
  country: string | null
  spend: number | null
  roas: number | null
  conversions: number | null
  headline: string
  body_text: string
  cta: string | null
}

interface Regeneration {
  id: string
  comment: string
  overrides: Record<string, string> | null
  status: string
  canva_job_id: string | null
  output_canva_url: string | null
  output_design_id: string | null
  output_material_id: string | null
  error: string | null
  requested_at: string | null
  completed_at: string | null
  autofill_echo: Record<string, any> | null
}

interface Detail {
  material_id: string
  branch_name: string | null
  material_type: string
  file_url: string
  description: string | null
  canva_url: string | null
  canva_design_id: string | null
  canva_captured_at: string | null
  canva_template_id: string | null
  is_template_ready: boolean
  canva_placeholder_schema: Record<string, string> | string[] | null
  combos: Combo[]
  regenerations: Regeneration[]
}

export default function WinningAdDetailPage() {
  const params = useParams()
  const materialId = params?.material_id as string
  const [detail, setDetail] = useState<Detail | null>(null)
  const [loading, setLoading] = useState(true)
  const [showConfig, setShowConfig] = useState(false)

  // Regenerate form state
  const [comment, setComment] = useState('')
  const [overrideRows, setOverrideRows] = useState<{ key: string; value: string }[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [errMsg, setErrMsg] = useState('')

  // Template config state
  const [templateId, setTemplateId] = useState('')
  const [schemaText, setSchemaText] = useState('')
  const [ready, setReady] = useState(false)
  const [savingCfg, setSavingCfg] = useState(false)

  const load = () => {
    setLoading(true)
    fetch(`${API_BASE}/api/winning-ads/${materialId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          setDetail(d.data)
          setTemplateId(d.data.canva_template_id || '')
          setReady(!!d.data.is_template_ready)
          setSchemaText(
            d.data.canva_placeholder_schema
              ? JSON.stringify(d.data.canva_placeholder_schema, null, 2)
              : ''
          )
        }
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { if (materialId) load() }, [materialId])

  const submit = async () => {
    setErrMsg('')
    if (!comment.trim()) { setErrMsg('Comment required'); return }
    setSubmitting(true)
    try {
      const overrides: Record<string, string> = {}
      overrideRows.forEach(r => { if (r.key.trim()) overrides[r.key.trim()] = r.value })

      const r = await fetch(`${API_BASE}/api/winning-ads/${materialId}/regenerate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          comment,
          overrides: Object.keys(overrides).length ? overrides : null,
        }),
      })
      const d = await r.json()
      if (!d.success) { setErrMsg(d.error || 'Failed'); return }
      setComment('')
      setOverrideRows([])
      load()
    } finally {
      setSubmitting(false)
    }
  }

  const saveConfig = async () => {
    setSavingCfg(true)
    try {
      let parsedSchema: any = null
      if (schemaText.trim()) {
        try { parsedSchema = JSON.parse(schemaText) }
        catch { setErrMsg('Placeholder schema must be valid JSON'); setSavingCfg(false); return }
      }
      await fetch(`${API_BASE}/api/winning-ads/${materialId}/template-config`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          canva_template_id: templateId || null,
          canva_placeholder_schema: parsedSchema,
          is_template_ready: ready,
        }),
      })
      load()
      setShowConfig(false)
    } finally {
      setSavingCfg(false)
    }
  }

  if (loading) return <div className="p-6 text-gray-500">Loading…</div>
  if (!detail) return <div className="p-6 text-red-600">Material not found</div>

  const schemaKeys: string[] = Array.isArray(detail.canva_placeholder_schema)
    ? detail.canva_placeholder_schema
    : detail.canva_placeholder_schema
      ? Object.keys(detail.canva_placeholder_schema)
      : []

  return (
    <div className="p-6 max-w-5xl">
      <Link href="/winning-ads" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline mb-4">
        <ArrowLeft className="w-4 h-4" /> Back to Winning Ads
      </Link>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{detail.material_id}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {detail.branch_name} · {detail.material_type}
            {detail.canva_captured_at && ` · captured ${new Date(detail.canva_captured_at).toLocaleDateString()}`}
          </p>
        </div>
        <div className="flex gap-2">
          {detail.canva_url && (
            <a
              href={detail.canva_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-3 py-2 text-sm bg-purple-600 text-white rounded hover:bg-purple-700"
            >
              Open in Canva <ExternalLink className="w-3 h-3" />
            </a>
          )}
          <button
            onClick={() => setShowConfig(s => !s)}
            className="inline-flex items-center gap-1 px-3 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50"
          >
            <Settings className="w-3 h-3" /> Template config
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Material preview</h2>
          {detail.material_type === 'image' && detail.file_url ? (
            <img src={detail.file_url} alt="" className="w-full rounded border border-gray-100" />
          ) : (
            <a href={detail.file_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline text-sm">
              {detail.file_url}
            </a>
          )}
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-2">Combos using this material</h2>
          <div className="space-y-2 text-sm">
            {detail.combos.map(c => (
              <div key={c.combo_id} className="flex justify-between border-b border-gray-100 pb-2 last:border-0">
                <div>
                  <div className="font-medium text-gray-900">{c.ad_name || c.combo_id}</div>
                  <div className="text-xs text-gray-500">{c.target_audience} · {c.country}</div>
                </div>
                <div className="text-right">
                  <div className="font-mono text-green-700">{c.roas?.toFixed(2) ?? '—'}</div>
                  <div className="text-xs text-gray-500">{c.conversions ?? 0} conv</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {showConfig && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 mb-6">
          <h2 className="text-sm font-semibold text-gray-800 mb-3">Canva template config</h2>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-gray-600 block mb-1">Brand template ID</label>
              <input
                value={templateId}
                onChange={e => setTemplateId(e.target.value)}
                placeholder="DAFxxxxxxxx"
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono"
              />
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">
                Placeholder schema (JSON: {`{"headline": "...", "bg_image": "...", "cta": "..."}`})
              </label>
              <textarea
                value={schemaText}
                onChange={e => setSchemaText(e.target.value)}
                rows={6}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono"
                placeholder='{"headline": "Main headline text", "cta": "Button text", "bg_image": "Background image"}'
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={ready} onChange={e => setReady(e.target.checked)} />
              Mark as template-ready (enables regenerate)
            </label>
            <div className="flex gap-2">
              <button
                onClick={saveConfig}
                disabled={savingCfg}
                className="px-4 py-2 text-sm bg-yellow-600 text-white rounded hover:bg-yellow-700 disabled:opacity-50"
              >
                {savingCfg ? 'Saving…' : 'Save config'}
              </button>
              <button onClick={() => setShowConfig(false)} className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded">
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-purple-600" /> Regenerate from comment
          </h2>
          {!detail.is_template_ready && (
            <span className="text-xs text-yellow-700 bg-yellow-100 px-2 py-1 rounded">
              Template config required first
            </span>
          )}
        </div>
        <textarea
          value={comment}
          onChange={e => setComment(e.target.value)}
          placeholder="e.g. Same layout but for couples package, with sea-view background and 'Stay 3 nights save 25%' headline"
          rows={3}
          className="w-full border border-gray-300 rounded px-3 py-2 text-sm mb-3"
          disabled={!detail.is_template_ready}
        />

        {schemaKeys.length > 0 && (
          <div className="mb-3">
            <p className="text-xs text-gray-600 mb-1">Override placeholders (optional)</p>
            <div className="space-y-1">
              {overrideRows.map((row, i) => (
                <div key={i} className="flex gap-2">
                  <select
                    value={row.key}
                    onChange={e => {
                      const next = [...overrideRows]; next[i].key = e.target.value; setOverrideRows(next)
                    }}
                    className="border border-gray-300 rounded px-2 py-1 text-sm"
                  >
                    <option value="">— pick slot —</option>
                    {schemaKeys.map(k => <option key={k} value={k}>{k}</option>)}
                  </select>
                  <input
                    value={row.value}
                    onChange={e => {
                      const next = [...overrideRows]; next[i].value = e.target.value; setOverrideRows(next)
                    }}
                    placeholder="value"
                    className="flex-1 border border-gray-300 rounded px-2 py-1 text-sm"
                  />
                  <button
                    onClick={() => setOverrideRows(overrideRows.filter((_, j) => j !== i))}
                    className="text-gray-400 hover:text-red-600"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              ))}
              <button
                onClick={() => setOverrideRows([...overrideRows, { key: '', value: '' }])}
                className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
              >
                <Plus className="w-3 h-3" /> Add override
              </button>
            </div>
          </div>
        )}

        {errMsg && <p className="text-sm text-red-600 mb-2">{errMsg}</p>}

        <button
          onClick={submit}
          disabled={submitting || !detail.is_template_ready || !comment.trim()}
          className="px-4 py-2 text-sm bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {submitting ? 'Generating…' : 'Regenerate in Canva'}
        </button>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-800 mb-3">Regeneration history</h2>
        {detail.regenerations.length === 0 ? (
          <p className="text-sm text-gray-500">No regenerations yet.</p>
        ) : (
          <div className="divide-y divide-gray-100">
            {detail.regenerations.map(r => (
              <div key={r.id} className="py-3">
                <div className="flex items-start justify-between mb-1">
                  <p className="text-sm text-gray-800 flex-1">{r.comment}</p>
                  <span className={`text-xs px-2 py-0.5 rounded ml-3 ${
                    r.status === 'COMPLETED' ? 'bg-green-100 text-green-700' :
                    r.status === 'FAILED' ? 'bg-red-100 text-red-700' :
                    'bg-yellow-100 text-yellow-700'
                  }`}>{r.status}</span>
                </div>
                <div className="text-xs text-gray-500 flex gap-3 flex-wrap">
                  {r.requested_at && <span>{new Date(r.requested_at).toLocaleString()}</span>}
                  {r.output_canva_url && (
                    <a href={r.output_canva_url} target="_blank" rel="noopener noreferrer" className="text-purple-700 hover:underline inline-flex items-center gap-0.5">
                      Open design <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                  {r.output_material_id && (
                    <Link href={`/winning-ads/${r.output_material_id}`} className="text-blue-600 hover:underline">
                      → New material {r.output_material_id}
                    </Link>
                  )}
                  {r.status === 'PENDING' && r.canva_job_id && (
                    <span className="text-yellow-700">
                      Queued at Canva (job {r.canva_job_id.slice(0, 16)}…) — auto-polled every 2 min
                    </span>
                  )}
                </div>
                {r.error && <p className="text-xs text-red-600 mt-1">{r.error}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
