'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Sparkles, ListChecks } from 'lucide-react'
import SendToLarkModal from '@/components/SendToLarkModal'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Account { id: string; account_name: string; platform: string }

interface ScriptBeat {
  time: string
  visual: string
  on_screen_text: string
  voiceover: string
}
interface VideoProduction {
  voiceover?: string
  music?: string
  captions?: string
  cta?: string
}

interface Brief {
  title: string
  // image fields
  hook?: string
  subhead?: string
  cta?: string
  visual_direction?: {
    scene: string
    human_presence: string
    color_palette: string
    emotional_angle: string
  }
  visual_description?: string
  // video fields
  concept?: string
  duration_sec?: number
  script?: ScriptBeat[]
  production?: VideoProduction
  // shared
  angle?: string
  keypoints: string[]
  rationale?: string
}

interface KeypointPerf { roas: number | null; combos: number; conversions: number; spend: number }

interface TopCreative {
  combo_id: string
  ad_name: string | null
  target_audience: string | null
  country: string | null
  verdict: string
  roas: number | null
  headline: string | null
  material_type: string | null
  file_url: string | null
}

interface BriefResult {
  branch_name: string
  patterns: {
    sample_size: number
    angle_distribution: Record<string, number>
    angle_performance?: Record<string, KeypointPerf>
    keypoint_distribution: Record<string, number>
    keypoint_performance?: Record<string, KeypointPerf>
    visual_distribution: Record<string, number>
    headline_examples: string[]
  }
  top_creatives?: TopCreative[]
  briefs: Brief[]
  templates: { id: string; name: string; size: string; placeholder_keys: string[] }[]
  warning?: string
  error?: string
}

const TA_LIST = ['Solo', 'Couple', 'Friend', 'Group', 'Business']
const COUNTRY_LIST = ['VN', 'TW', 'JP', 'SG', 'HK', 'PH', 'AU', 'US', 'GB', 'DE', 'CA', 'KR', 'MY', 'TH', 'ID']
const FORMAT_LIST: { code: string; label: string }[] = [
  { code: 'image', label: 'Image' },
  { code: 'video', label: 'Video' },
]
const LANGUAGE_LIST: { code: string; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'vi', label: 'Vietnamese' },
  { code: 'zh', label: 'Chinese (Traditional)' },
  { code: 'ja', label: 'Japanese' },
]

export default function AIBriefPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [branchId, setBranchId] = useState('')
  const [ta, setTa] = useState('')
  const [country, setCountry] = useState('')
  const [language, setLanguage] = useState('en')
  const [adFormat, setAdFormat] = useState('image')
  const [vibe, setVibe] = useState('')
  const [selectedCreatives, setSelectedCreatives] = useState<TopCreative[]>([])
  const [selectedKeypoints, setSelectedKeypoints] = useState<string[]>([])
  const [nVariants, setNVariants] = useState(3)
  const [goal, setGoal] = useState('roas')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BriefResult | null>(null)
  const [err, setErr] = useState('')
  const [sendLark, setSendLark] = useState<Brief | null>(null)
  const [larkMsg, setLarkMsg] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setAccounts(d.data.filter((a: Account) => a.platform === 'meta')) })
  }, [])

  // Pre-fill from query params when arriving via "Brief" on the Winning Ads
  // list (e.g. /winning-ads/brief?branch_id=...&ta=Couple). Reads
  // window.location directly so we don't need a Suspense boundary for
  // useSearchParams.
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search)
    const b = sp.get('branch_id')
    const t = sp.get('ta')
    if (b) setBranchId(b)
    if (t) setTa(t)
  }, [])

  const generate = async () => {
    if (!branchId) { setErr('Pick a branch'); return }
    setErr('')
    setLoading(true)
    setResult(null)
    setSelectedCreatives([])
    setSelectedKeypoints([])
    try {
      const r = await fetch(`${API_BASE}/api/creative/brief`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          branch_id: branchId,
          target_audience: ta || null,
          country: country || null,
          language: language || null,
          ad_format: adFormat,
          vibe: vibe.trim() || null,
          n_variants: nVariants,
          performance_goal: goal,
        }),
      })
      const d = await r.json()
      if (!d.success) { setErr(d.error || 'Failed'); return }
      setResult(d.data)
      if (d.data.error) setErr(d.data.error)
    } catch {
      setErr('Network error')
    } finally {
      setLoading(false)
    }
  }

  const toggleCreative = (tc: TopCreative) => {
    setSelectedCreatives(prev =>
      prev.some(s => s.combo_id === tc.combo_id)
        ? prev.filter(s => s.combo_id !== tc.combo_id)
        : [...prev, tc]
    )
  }

  const toggleKeypoint = (kp: string) => {
    setSelectedKeypoints(prev =>
      prev.includes(kp) ? prev.filter(k => k !== kp) : [...prev, kp]
    )
  }

  return (
    <div className="p-6 max-w-5xl">
      <Link href="/winning-ads" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline mb-4">
        <ArrowLeft className="w-4 h-4" /> Back to Winning Ads
      </Link>

      <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
        <Sparkles className="w-6 h-6 text-purple-600" /> AI Creative Brief
      </h1>
      <p className="text-sm text-gray-500 mt-1 mb-6">
        Generates brief variants grounded in the branch&apos;s actual winning patterns.
      </p>

      {/* Form */}
      <div className="bg-white border border-gray-200 rounded-lg p-4 mb-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <div>
            <label className="text-xs text-gray-600 block mb-1">Branch *</label>
            <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={branchId} onChange={e => setBranchId(e.target.value)}>
              <option value="">— pick branch —</option>
              {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">Target audience</label>
            <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={ta} onChange={e => setTa(e.target.value)}>
              <option value="">Any</option>
              {TA_LIST.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">Country</label>
            <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={country} onChange={e => setCountry(e.target.value)}>
              <option value="">Any</option>
              {COUNTRY_LIST.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">Language</label>
            <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={language} onChange={e => setLanguage(e.target.value)}>
              {LANGUAGE_LIST.map(l => <option key={l.code} value={l.code}>{l.label}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">Format</label>
            <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={adFormat} onChange={e => setAdFormat(e.target.value)}>
              {FORMAT_LIST.map(f => <option key={f.code} value={f.code}>{f.label}</option>)}
            </select>
          </div>
          <div className="sm:col-span-2 lg:col-span-3">
            <label className="text-xs text-gray-600 block mb-1">Vibe (optional free text)</label>
            <input className="w-full border border-gray-300 rounded px-3 py-2 text-sm"
              placeholder="e.g. calm, social, slow mornings, sea view"
              value={vibe} onChange={e => setVibe(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">Variants</label>
            <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={nVariants} onChange={e => setNVariants(Number(e.target.value))}>
              {[1, 2, 3, 4, 5, 6].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-gray-600 block mb-1">Rank winners by</label>
            <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={goal} onChange={e => setGoal(e.target.value)}>
              <option value="roas">ROAS</option>
              <option value="spend">Spend</option>
              <option value="conversions">Conversions</option>
            </select>
          </div>
        </div>
        {err && <p className="text-sm text-red-600 mt-3">{err}</p>}
        <button
          onClick={generate}
          disabled={loading || !branchId}
          className="mt-4 inline-flex items-center gap-1.5 px-4 py-2 text-sm bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
        >
          <Sparkles className="w-4 h-4" /> {loading ? 'Generating…' : 'Generate brief'}
        </button>
      </div>

      {result && (
        <>
          {result.warning && (
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3 mb-4 text-sm text-yellow-800">
              {result.warning}
            </div>
          )}

          {/* Patterns summary */}
          <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
            <h2 className="text-sm font-semibold text-gray-800 mb-2">
              Grounded in {result.patterns.sample_size} winning ad{result.patterns.sample_size === 1 ? '' : 's'} — {result.branch_name}
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
              <PerfBlock title="Top angles" dist={result.patterns.angle_distribution} perf={result.patterns.angle_performance} />
              <PerfBlock
                title="Top keypoints — tick to use"
                dist={result.patterns.keypoint_distribution}
                perf={result.patterns.keypoint_performance}
                selectable
                selected={selectedKeypoints}
                onToggle={toggleKeypoint}
              />
              <PatternBlock title="Top visual tags" dist={result.patterns.visual_distribution} />
            </div>
            {selectedKeypoints.length > 0 && (
              <p className="text-xs text-blue-600 mt-2">
                {selectedKeypoints.length} keypoint{selectedKeypoints.length === 1 ? '' : 's'} selected — these replace the brief&apos;s keypoints when you Send to Lark.
              </p>
            )}
          </div>

          {/* Top winning creatives — tick to attach as references */}
          {result.top_creatives && result.top_creatives.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg p-4 mb-4">
              <h2 className="text-sm font-semibold text-gray-800 mb-1">
                Top winning creatives{ta ? ` · ${ta}` : ''}
              </h2>
              <p className="text-xs text-gray-400 mb-3">
                Tick to attach the creative link as a reference in the brief you send to Lark.
              </p>
              <div className="divide-y divide-gray-100">
                {result.top_creatives.map(tc => {
                  const checked = selectedCreatives.some(s => s.combo_id === tc.combo_id)
                  return (
                    <label key={tc.combo_id} className="flex items-center gap-3 py-2 cursor-pointer text-sm">
                      <input type="checkbox" checked={checked} onChange={() => toggleCreative(tc)} className="rounded border-gray-300" />
                      <span className="flex-1 truncate">
                        <span className="font-medium text-gray-800">{tc.ad_name || tc.combo_id}</span>
                        {tc.country && <span className="text-gray-400 ml-2">{tc.country}</span>}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded font-medium ${tc.verdict === 'WIN' ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'}`}>{tc.verdict}</span>
                      <span className="font-mono text-green-700 w-16 text-right">{tc.roas != null ? tc.roas.toFixed(2) : '—'}</span>
                      {tc.file_url
                        ? <a href={tc.file_url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} className="text-blue-600 hover:underline text-xs w-12 text-right">link ↗</a>
                        : <span className="text-gray-300 text-xs w-12 text-right">—</span>}
                    </label>
                  )
                })}
              </div>
              {selectedCreatives.length > 0 && (
                <p className="text-xs text-blue-600 mt-2">
                  {selectedCreatives.length} selected — attached to the brief you send to Lark.
                </p>
              )}
            </div>
          )}

          {larkMsg && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4 text-sm text-blue-800">
              {larkMsg} — check the Lark “Tasks” board.
            </div>
          )}

          {/* Brief variants */}
          <div className="space-y-4">
            {result.briefs.map((b, i) => (
              <div key={i} className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="flex items-baseline justify-between mb-2">
                  <h3 className="text-base font-semibold text-gray-900">{b.title}</h3>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => { setLarkMsg(''); setSendLark(b) }}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
                    >
                      <ListChecks className="w-3 h-3" /> Send to Lark
                    </button>
                    <span className="text-xs text-gray-400">Variant {i + 1}</span>
                  </div>
                </div>
                {b.script && b.script.length > 0 ? (
                  /* Video brief — beat-by-beat script + production notes */
                  <div className="space-y-2 text-sm">
                    {b.concept && (
                      <div className="text-gray-700">
                        <span className="text-gray-500">Concept </span>{b.concept}
                        {b.duration_sec ? <span className="text-gray-400"> · ~{b.duration_sec}s</span> : null}
                      </div>
                    )}
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs border border-gray-100">
                        <thead className="bg-gray-50 text-gray-500">
                          <tr>
                            <th className="text-left px-2 py-1 w-16">Time</th>
                            <th className="text-left px-2 py-1">Visual</th>
                            <th className="text-left px-2 py-1">On-screen</th>
                            <th className="text-left px-2 py-1">Voiceover</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100 align-top">
                          {b.script.map((s, si) => (
                            <tr key={si}>
                              <td className="px-2 py-1 font-mono text-gray-500 whitespace-nowrap">{s.time}</td>
                              <td className="px-2 py-1 text-gray-700">{s.visual}</td>
                              <td className="px-2 py-1 text-gray-700">{s.on_screen_text}</td>
                              <td className="px-2 py-1 text-gray-700">{s.voiceover}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {b.production && (
                      <div className="text-xs text-gray-600 space-y-0.5 bg-gray-50 rounded p-2">
                        {b.production.voiceover && <div><span className="text-gray-400">VO: </span>{b.production.voiceover}</div>}
                        {b.production.music && <div><span className="text-gray-400">Music: </span>{b.production.music}</div>}
                        {b.production.captions && <div><span className="text-gray-400">Captions: </span>{b.production.captions}</div>}
                        {b.production.cta && <div><span className="text-gray-400">CTA: </span>{b.production.cta}</div>}
                      </div>
                    )}
                    <KeypointChips keypoints={b.keypoints} perf={result.patterns.keypoint_performance} />
                  </div>
                ) : (
                  /* Image brief */
                  <>
                    <div className="space-y-1.5 text-sm">
                      {b.hook && <div><span className="text-gray-500 w-20 inline-block">Hook</span><span className="font-medium">{b.hook}</span></div>}
                      {b.subhead && <div><span className="text-gray-500 w-20 inline-block">Subhead</span>{b.subhead}</div>}
                      {b.cta && <div><span className="text-gray-500 w-20 inline-block">CTA</span><span className="font-medium text-purple-700">{b.cta}</span></div>}
                      {b.angle && <div><span className="text-gray-500 w-20 inline-block">Angle</span>{b.angle}</div>}
                      {b.keypoints?.length > 0 && (
                        <div className="flex">
                          <span className="text-gray-500 w-20 inline-block align-top shrink-0">Keypoints</span>
                          <KeypointChips keypoints={b.keypoints} perf={result.patterns.keypoint_performance} />
                        </div>
                      )}
                      {b.visual_description && (
                        <div className="flex">
                          <span className="text-gray-500 w-20 inline-block align-top shrink-0">Visual</span>
                          <span className="text-gray-700">{b.visual_description}</span>
                        </div>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-1.5 mt-3">
                      {b.visual_direction && Object.entries(b.visual_direction).map(([k, v]) => v && (
                        <span key={k} className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600">
                          {k.replace('_', ' ')}: {v}
                        </span>
                      ))}
                    </div>
                  </>
                )}
                {b.rationale && <p className="text-xs text-gray-500 mt-2 italic">{b.rationale}</p>}
              </div>
            ))}
            {result.briefs.length === 0 && !result.warning && (
              <p className="text-sm text-gray-500">No briefs returned — the model may have failed to produce valid output. Try again.</p>
            )}
          </div>
        </>
      )}

      {sendLark && (
        <SendToLarkModal
          brief={sendLark}
          branchId={branchId}
          branchName={result?.branch_name || ''}
          country={country}
          ta={ta}
          adFormat={adFormat}
          referenceLinks={selectedCreatives
            .filter(s => s.file_url)
            .map(s => ({ name: s.ad_name || s.combo_id, url: s.file_url as string, roas: s.roas }))}
          overrideKeypoints={selectedKeypoints}
          onClose={() => setSendLark(null)}
          onCreated={(_recordId, taskName) => {
            setSendLark(null)
            setLarkMsg(`Lark task created: ${taskName}`)
          }}
        />
      )}
    </div>
  )
}

function KeypointChips({ keypoints, perf }: { keypoints: string[]; perf?: Record<string, KeypointPerf> }) {
  if (!keypoints?.length) return null
  return (
    <div className="flex flex-wrap gap-1.5">
      {keypoints.map((kp, ki) => {
        const r = perf?.[kp]?.roas
        return (
          <span key={ki} className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-700">
            {kp}{r != null && <span className="ml-1 font-mono text-green-700">ROAS {r.toFixed(2)}</span>}
          </span>
        )
      })}
    </div>
  )
}

function PerfBlock({
  title, dist, perf, selectable, selected, onToggle,
}: {
  title: string
  dist: Record<string, number>
  perf?: Record<string, KeypointPerf>
  selectable?: boolean
  selected?: string[]
  onToggle?: (label: string) => void
}) {
  const entries = Object.entries(dist || {})
  return (
    <div>
      <div className="font-medium text-gray-600 mb-1">{title}</div>
      {entries.length === 0 ? (
        <div className="text-gray-400">—</div>
      ) : (
        <ul className="space-y-0.5">
          {entries.map(([k, count]) => {
            const roas = perf?.[k]?.roas
            const row = (
              <>
                <span className="text-gray-700 truncate pr-1 flex-1" title={k}>{k}</span>
                {roas != null
                  ? <span className="text-green-700 font-mono shrink-0" title="ROAS">{roas.toFixed(2)}</span>
                  : <span className="text-gray-400 font-mono shrink-0" title="winners using it">×{count}</span>}
              </>
            )
            return selectable ? (
              <li key={k}>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={selected?.includes(k) || false}
                    onChange={() => onToggle?.(k)}
                    className="rounded border-gray-300 shrink-0"
                  />
                  {row}
                </label>
              </li>
            ) : (
              <li key={k} className="flex items-center gap-1.5">{row}</li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

function PatternBlock({ title, dist }: { title: string; dist: Record<string, number> }) {
  const entries = Object.entries(dist || {})
  return (
    <div>
      <div className="font-medium text-gray-600 mb-1">{title}</div>
      {entries.length === 0 ? (
        <div className="text-gray-400">—</div>
      ) : (
        <ul className="space-y-0.5">
          {entries.map(([k, v]) => (
            <li key={k} className="flex justify-between">
              <span className="text-gray-700 truncate pr-2">{k}</span>
              <span className="text-gray-400 font-mono">{v}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
