'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { ArrowLeft, ExternalLink, RefreshCw, Sparkles } from 'lucide-react'

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

interface Detail {
  material_id: string
  branch_name: string | null
  material_type: string
  file_url: string
  description: string | null
  combos: Combo[]
}

interface VisualTag {
  category: string
  value: string
  confidence: number | null
  model_version: string | null
}

interface TagsResponse {
  material_id: string
  analyzed_at: string | null
  model_version: string | null
  tag_count: number
  tags: Record<string, VisualTag[]>
}

const CATEGORY_LABELS: Record<string, string> = {
  text_density: 'Text density',
  hook_type: 'Hook type',
  cta_visible: 'CTA visible',
  color_palette: 'Color palette',
  human_presence: 'People',
  scene_type: 'Scene',
  emotional_angle: 'Emotion',
}

export default function WinningAdDetailPage() {
  const params = useParams()
  const materialId = params?.material_id as string
  const [detail, setDetail] = useState<Detail | null>(null)
  const [loading, setLoading] = useState(true)
  const [tags, setTags] = useState<TagsResponse | null>(null)
  const [tagsLoading, setTagsLoading] = useState(true)
  const [retagging, setRetagging] = useState(false)

  const loadDetail = () => {
    setLoading(true)
    fetch(`${API_BASE}/api/winning-ads/${materialId}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setDetail(d.data) })
      .finally(() => setLoading(false))
  }

  const loadTags = () => {
    setTagsLoading(true)
    fetch(`${API_BASE}/api/creative/materials/${materialId}/tags`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setTags(d.data) })
      .finally(() => setTagsLoading(false))
  }

  useEffect(() => {
    if (materialId) { loadDetail(); loadTags() }
  }, [materialId])

  const retag = async () => {
    setRetagging(true)
    try {
      await fetch(`${API_BASE}/api/creative/materials/${materialId}/retag`, {
        method: 'POST',
        credentials: 'include',
      })
      // Re-tag is async (cron picks it up) — just reflect the cleared state.
      loadTags()
    } finally {
      setRetagging(false)
    }
  }

  if (loading) return <div className="p-6 text-gray-500">Loading…</div>
  if (!detail) return <div className="p-6 text-red-600">Material not found</div>

  const tagCategories = tags ? Object.keys(tags.tags) : []

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
          </p>
        </div>
        {detail.file_url && (
          <a
            href={detail.file_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 px-3 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50"
          >
            Open source <ExternalLink className="w-3 h-3" />
          </a>
        )}
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

      {/* Visual tags — Claude vision */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-purple-600" /> Visual tags
            <span className="text-xs font-normal text-gray-400">(Claude vision)</span>
          </h2>
          <button
            onClick={retag}
            disabled={retagging}
            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`w-3 h-3 ${retagging ? 'animate-spin' : ''}`} /> Re-tag
          </button>
        </div>

        {tagsLoading ? (
          <p className="text-sm text-gray-400">Loading tags…</p>
        ) : !tags || tags.tag_count === 0 ? (
          <p className="text-sm text-gray-500">
            {tags?.analyzed_at
              ? 'No usable tags returned — the thumbnail may be broken. Try Re-tag.'
              : 'Not analyzed yet — the vision tagger cron will reach this material soon.'}
          </p>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
              {tagCategories.map(cat => (
                <div key={cat}>
                  <div className="text-xs font-medium text-gray-500 mb-1">
                    {CATEGORY_LABELS[cat] || cat}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {tags.tags[cat].map(t => (
                      <span
                        key={t.value}
                        className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-purple-50 text-purple-700 border border-purple-200"
                        title={t.confidence != null ? `confidence ${(t.confidence * 100).toFixed(0)}%` : undefined}
                      >
                        {t.value}
                        {t.confidence != null && (
                          <span className="text-purple-400">{(t.confidence * 100).toFixed(0)}%</span>
                        )}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-3">
              {tags.tag_count} tags · {tags.model_version}
              {tags.analyzed_at && ` · ${new Date(tags.analyzed_at).toLocaleString()}`}
            </p>
          </>
        )}
      </div>
    </div>
  )
}
