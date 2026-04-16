'use client'

import { useEffect, useState } from 'react'
import { Mic, Play, CheckCircle, XCircle, Loader2, Sparkles, ArrowRight, Search, Filter } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Transcript {
  id: string
  material_id: string | null
  combo_id: string | null
  video_url: string
  language: string | null
  transcript: string | null
  ai_analysis: {
    summary?: string
    suggested_angle_type?: string
    suggested_angle_explain?: string
    suggested_hook_examples?: string[]
    suggested_keypoints?: { category: string; title: string }[]
    detected_ta?: string
    tone?: string
  } | null
  status: string
  error_message: string | null
  processing_time_seconds: number | null
  created_at: string | null
}

interface Combo {
  id: string
  combo_id: string
  ad_name: string | null
  branch_id: string
  material_id: string
}

interface Material {
  id: string
  material_id: string
  material_type: string
  file_url: string
  branch_id: string
}

interface Account {
  id: string
  account_name: string
}

const STATUS_STYLES: Record<string, { icon: any; color: string; bg: string; label: string }> = {
  PENDING: { icon: Loader2, color: 'text-gray-600', bg: 'bg-gray-100', label: 'Queued' },
  TRANSCRIBING: { icon: Mic, color: 'text-blue-600', bg: 'bg-blue-100', label: 'Transcribing...' },
  ANALYZING: { icon: Sparkles, color: 'text-purple-600', bg: 'bg-purple-100', label: 'AI Analyzing...' },
  COMPLETED: { icon: CheckCircle, color: 'text-green-600', bg: 'bg-green-100', label: 'Completed' },
  FAILED: { icon: XCircle, color: 'text-red-600', bg: 'bg-red-100', label: 'Failed' },
}

const ANGLE_COLORS: Record<string, string> = {
  location: 'bg-blue-50 text-blue-700',
  amenity: 'bg-green-50 text-green-700',
  experience: 'bg-purple-50 text-purple-700',
  value: 'bg-orange-50 text-orange-700',
}

export default function TranscriptionsPage() {
  const [transcripts, setTranscripts] = useState<Transcript[]>([])
  const [combos, setCombos] = useState<Combo[]>([])
  const [materials, setMaterials] = useState<Material[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Filters
  const [selectedBranch, setSelectedBranch] = useState('')
  const [comboSearch, setComboSearch] = useState('')

  // New transcription form
  const [showForm, setShowForm] = useState(false)
  const [videoUrl, setVideoUrl] = useState('')
  const [selectedCombo, setSelectedCombo] = useState('')
  const [selectedMaterial, setSelectedMaterial] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [useSync, setUseSync] = useState(false) // sync mode (no Celery needed)
  const [applyingId, setApplyingId] = useState<string | null>(null)

  const loadData = () => {
    setLoading(true)
    Promise.all([
      fetch(`${API_BASE}/api/transcripts?limit=100`).then(r => r.json()),
      fetch(`${API_BASE}/api/combos?limit=200`).then(r => r.json()),
      fetch(`${API_BASE}/api/materials?limit=200`).then(r => r.json()),
      fetch(`${API_BASE}/api/accounts`).then(r => r.json()),
    ]).then(([tRes, cRes, mRes, aRes]) => {
      if (tRes.success) setTranscripts(tRes.data.items)
      if (cRes.success) setCombos(cRes.data.items)
      if (mRes.success) setMaterials(mRes.data.items)
      if (aRes.success) setAccounts(aRes.data.filter((a: any) => a.platform === 'meta'))
    }).catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadData() }, [])

  // Auto-refresh processing transcripts
  useEffect(() => {
    const processing = transcripts.some(t => ['PENDING', 'TRANSCRIBING', 'ANALYZING'].includes(t.status))
    if (!processing) return
    const interval = setInterval(() => {
      fetch(`${API_BASE}/api/transcripts?limit=100`).then(r => r.json())
        .then(data => { if (data.success) setTranscripts(data.data.items) })
    }, 5000)
    return () => clearInterval(interval)
  }, [transcripts])

  const handleSubmit = async () => {
    if (!videoUrl) return
    setSubmitting(true)
    try {
      const endpoint = useSync ? '/api/transcribe/sync' : '/api/transcribe'
      const resp = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_url: videoUrl,
          combo_id: selectedCombo || null,
          material_id: selectedMaterial || null,
        }),
      })
      const data = await resp.json()
      if (data.success) {
        setShowForm(false)
        setVideoUrl('')
        setSelectedCombo('')
        setSelectedMaterial('')
        // Auto-expand the new result
        const newId = data.data?.id || data.data?.transcript_id
        if (newId) setExpandedId(newId)
        loadData()
      }
    } catch { /* */ }
    finally { setSubmitting(false) }
  }

  const handleApply = async (transcriptId: string) => {
    setApplyingId(transcriptId)
    try {
      const resp = await fetch(`${API_BASE}/api/transcripts/${transcriptId}/apply`, {
        method: 'POST',
      })
      const data = await resp.json()
      if (data.success) {
        loadData()
      }
    } catch { /* */ }
    finally { setApplyingId(null) }
  }

  const accName = (id: string) => accounts.find(a => a.id === id)?.account_name || ''
  const videoMaterials = materials.filter(m => m.material_type === 'video')

  // Filtered combos: by branch + search term
  const filteredCombos = combos.filter(c => {
    if (selectedBranch && c.branch_id !== selectedBranch) return false
    if (comboSearch) {
      const q = comboSearch.toLowerCase()
      const name = (c.ad_name || '').toLowerCase()
      const cid = (c.combo_id || '').toLowerCase()
      const branch = accName(c.branch_id).toLowerCase()
      if (!name.includes(q) && !cid.includes(q) && !branch.includes(q)) return false
    }
    return true
  })

  // Filtered transcripts: by branch
  const filteredTranscripts = transcripts.filter(t => {
    if (!selectedBranch) return true
    if (t.combo_id) {
      const combo = combos.find(c => c.id === t.combo_id)
      return combo ? combo.branch_id === selectedBranch : true
    }
    return true
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Video Transcriptions</h1>
          <p className="text-sm text-gray-500 mt-1">
            Transcribe ad videos → AI auto-classify Angles & Keypoints
          </p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 text-sm font-medium flex items-center gap-1.5"
        >
          <Mic className="w-4 h-4" />
          {showForm ? 'Cancel' : 'Transcribe Video'}
        </button>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Filter className="w-4 h-4" />
          <span>Filter:</span>
        </div>
        <select
          value={selectedBranch}
          onChange={e => { setSelectedBranch(e.target.value); setSelectedCombo('') }}
          className="border border-gray-300 rounded-lg px-3 py-1.5 text-sm bg-white min-w-[180px]"
        >
          <option value="">All Branches</option>
          {accounts.map(a => (
            <option key={a.id} value={a.id}>{a.account_name}</option>
          ))}
        </select>
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            type="text"
            value={comboSearch}
            onChange={e => setComboSearch(e.target.value)}
            placeholder="Search combo by name or ID..."
            className="w-full border border-gray-300 rounded-lg pl-9 pr-3 py-1.5 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
          />
        </div>
        {(selectedBranch || comboSearch) && (
          <button
            onClick={() => { setSelectedBranch(''); setComboSearch('') }}
            className="text-xs text-gray-500 hover:text-gray-700 underline"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* New Transcription Form */}
      {showForm && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6 space-y-4">
          <h2 className="font-semibold text-gray-900">New Transcription</h2>

          {/* Combo Selection — required */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Ad Combo <span className="text-red-500">*</span>
            </label>
            <select
              value={selectedCombo}
              onChange={e => setSelectedCombo(e.target.value)}
              className={`w-full border rounded-lg px-3 py-2 text-sm ${!selectedCombo ? 'border-red-300 bg-red-50' : 'border-gray-300'}`}
            >
              <option value="">-- Select combo (ad name) --</option>
              {filteredCombos.map(c => (
                <option key={c.id} value={c.id}>
                  {c.combo_id} — {c.ad_name || 'Unnamed'} ({accName(c.branch_id)})
                </option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">
              {filteredCombos.length} combo{filteredCombos.length !== 1 ? 's' : ''} available
              {selectedBranch ? ` for ${accName(selectedBranch)}` : ''}
              {comboSearch ? ` matching "${comboSearch}"` : ''}
              {' · '}AI will auto-apply Angle & Keypoints to this combo after analysis
            </p>
          </div>

          {/* Video URL */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Video URL <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={videoUrl}
              onChange={e => setVideoUrl(e.target.value)}
              placeholder="Paste Facebook URL, Instagram Reel, or direct video link..."
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
            />
            <div className="flex flex-wrap gap-2 mt-1.5">
              {['facebook.com', 'instagram.com', 'tiktok.com', '.mp4', 'drive.google.com'].map(tag => (
                <span key={tag} className="text-[10px] px-2 py-0.5 bg-gray-100 rounded-full text-gray-500">{tag}</span>
              ))}
            </div>
          </div>

          {/* Material link — optional */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Link to Material (optional)</label>
            <select
              value={selectedMaterial}
              onChange={e => setSelectedMaterial(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
            >
              <option value="">-- No material --</option>
              {videoMaterials.map(m => (
                <option key={m.id} value={m.id}>{m.material_id} — {accName(m.branch_id)}</option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                checked={useSync}
                onChange={e => setUseSync(e.target.checked)}
                className="w-4 h-4 text-purple-600"
              />
              Sync mode (wait for result — no Redis/Celery needed)
            </label>
          </div>

          <button
            onClick={handleSubmit}
            disabled={!videoUrl || !selectedCombo || submitting}
            className="px-6 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 text-sm font-medium disabled:opacity-50 flex items-center gap-2"
          >
            {submitting ? (
              <><Loader2 className="w-4 h-4 animate-spin" /> {useSync ? 'Processing...' : 'Queueing...'}</>
            ) : (
              <><Play className="w-4 h-4" /> Start Transcription</>
            )}
          </button>
        </div>
      )}

      {/* Transcripts List */}
      {loading ? (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">Loading...</div>
      ) : filteredTranscripts.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center">
          <Mic className="w-12 h-12 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500 text-lg">{transcripts.length === 0 ? 'No transcriptions yet' : 'No transcriptions match filters'}</p>
          <p className="text-sm text-gray-400 mt-2">
            {transcripts.length === 0
              ? 'Click "Transcribe Video" to analyze your first ad video'
              : `${transcripts.length} total transcription${transcripts.length !== 1 ? 's' : ''} — try changing filters`
            }
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredTranscripts.length !== transcripts.length && (
            <p className="text-xs text-gray-400">
              Showing {filteredTranscripts.length} of {transcripts.length} transcriptions
            </p>
          )}
          {filteredTranscripts.map(t => {
            const style = STATUS_STYLES[t.status] || STATUS_STYLES.PENDING
            const Icon = style.icon
            const isExpanded = expandedId === t.id
            const comboInfo = t.combo_id ? combos.find(c => c.id === t.combo_id) : null

            return (
              <div key={t.id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                {/* Summary row */}
                <div
                  className="p-4 flex items-center gap-4 cursor-pointer hover:bg-gray-50"
                  onClick={() => setExpandedId(isExpanded ? null : t.id)}
                >
                  <div className={`p-2 rounded-lg ${style.bg}`}>
                    <Icon className={`w-5 h-5 ${style.color} ${t.status === 'PENDING' || t.status === 'TRANSCRIBING' || t.status === 'ANALYZING' ? 'animate-spin' : ''}`} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${style.bg} ${style.color}`}>
                        {style.label}
                      </span>
                      {comboInfo && (
                        <span className="text-xs font-semibold text-purple-700 bg-purple-50 px-2 py-0.5 rounded-full">
                          {comboInfo.combo_id} — {comboInfo.ad_name || 'Unnamed'}
                        </span>
                      )}
                      {t.language && (
                        <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600 uppercase">{t.language}</span>
                      )}
                      {t.ai_analysis?.suggested_angle_type && (
                        <span className="text-xs px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 truncate max-w-[250px]">
                          {t.ai_analysis.suggested_angle_type}
                        </span>
                      )}
                      {t.ai_analysis?.detected_ta && t.ai_analysis.detected_ta !== 'null' && (
                        <span className="text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700">
                          {t.ai_analysis.detected_ta}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-600 mt-1 truncate">
                      {t.ai_analysis?.summary || t.transcript?.substring(0, 120) || t.video_url}
                    </p>
                  </div>
                  <div className="text-right shrink-0">
                    {t.processing_time_seconds && (
                      <p className="text-xs text-gray-400">{t.processing_time_seconds.toFixed(1)}s</p>
                    )}
                    {t.created_at && (
                      <p className="text-xs text-gray-400">{new Date(t.created_at).toLocaleString()}</p>
                    )}
                  </div>
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div className="border-t border-gray-100 p-5 space-y-4">
                    {/* Error */}
                    {t.error_message && (
                      <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
                        {t.error_message}
                      </div>
                    )}

                    {/* Transcript */}
                    {t.transcript && (
                      <div>
                        <h3 className="text-sm font-semibold text-gray-700 mb-2">Transcript</h3>
                        <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-700 whitespace-pre-wrap max-h-48 overflow-auto">
                          {t.transcript}
                        </div>
                      </div>
                    )}

                    {/* AI Analysis */}
                    {t.ai_analysis && (
                      <div className="space-y-4">
                        {/* Angle */}
                        {t.ai_analysis.suggested_angle_type && (
                          <div>
                            <h3 className="text-sm font-semibold text-gray-700 mb-2">Suggested Angle</h3>
                            <div className="bg-indigo-50 rounded-lg p-4">
                              <p className="font-medium text-indigo-800">{t.ai_analysis.suggested_angle_type}</p>
                              {t.ai_analysis.suggested_angle_explain && (
                                <p className="text-sm text-indigo-600 mt-1">{t.ai_analysis.suggested_angle_explain}</p>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Hook Examples */}
                        {t.ai_analysis.suggested_hook_examples && t.ai_analysis.suggested_hook_examples.length > 0 && (
                          <div>
                            <h3 className="text-sm font-semibold text-gray-700 mb-2">Hook Examples</h3>
                            <div className="space-y-1">
                              {t.ai_analysis.suggested_hook_examples.map((hook, i) => (
                                <div key={i} className="bg-amber-50 rounded-lg px-4 py-2 text-sm text-amber-800 font-medium">
                                  &ldquo;{hook}&rdquo;
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Keypoints */}
                        {t.ai_analysis.suggested_keypoints && t.ai_analysis.suggested_keypoints.length > 0 && (
                          <div>
                            <h3 className="text-sm font-semibold text-gray-700 mb-2">Suggested Keypoints</h3>
                            <div className="flex flex-wrap gap-2">
                              {t.ai_analysis.suggested_keypoints.map((kp, i) => (
                                <span key={i} className={`text-xs font-medium px-3 py-1.5 rounded-full ${ANGLE_COLORS[kp.category] || 'bg-gray-50 text-gray-700'}`}>
                                  [{kp.category}] {kp.title}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Meta info */}
                        <div className="flex flex-wrap gap-3 text-xs text-gray-500">
                          {t.ai_analysis.detected_ta && t.ai_analysis.detected_ta !== 'null' && (
                            <span className="px-2 py-1 bg-gray-100 rounded">TA: {t.ai_analysis.detected_ta}</span>
                          )}
                          {t.ai_analysis.tone && (
                            <span className="px-2 py-1 bg-gray-100 rounded">Tone: {t.ai_analysis.tone}</span>
                          )}
                        </div>

                        {/* Apply button */}
                        {t.combo_id && t.status === 'COMPLETED' && t.ai_analysis.suggested_angle_type && (
                          <button
                            onClick={() => handleApply(t.id)}
                            disabled={applyingId === t.id}
                            className="mt-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-medium flex items-center gap-2 disabled:opacity-50"
                          >
                            {applyingId === t.id ? (
                              <><Loader2 className="w-4 h-4 animate-spin" /> Applying...</>
                            ) : (
                              <><ArrowRight className="w-4 h-4" /> Apply to Combo {comboInfo?.combo_id}</>
                            )}
                          </button>
                        )}
                      </div>
                    )}

                    {/* Source URL */}
                    <div className="text-xs text-gray-400 pt-2 border-t border-gray-100">
                      <span>Source: </span>
                      <a href={t.video_url} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline truncate">
                        {t.video_url}
                      </a>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
