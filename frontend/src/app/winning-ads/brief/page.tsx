'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Sparkles, Send, ListChecks } from 'lucide-react'
import SendToFigmaModal from '@/components/SendToFigmaModal'
import SendToLarkModal from '@/components/SendToLarkModal'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Account { id: string; account_name: string; platform: string }

interface Brief {
  title: string
  hook: string
  subhead: string
  cta: string
  angle: string
  keypoints: string[]
  visual_direction: {
    scene: string
    human_presence: string
    color_palette: string
    emotional_angle: string
  }
  rationale: string
}

interface BriefResult {
  branch_name: string
  patterns: {
    sample_size: number
    angle_distribution: Record<string, number>
    keypoint_distribution: Record<string, number>
    visual_distribution: Record<string, number>
    headline_examples: string[]
  }
  briefs: Brief[]
  templates: { id: string; name: string; size: string; placeholder_keys: string[] }[]
  warning?: string
  error?: string
}

const TA_LIST = ['Solo', 'Couple', 'Friend', 'Group', 'Business']

export default function AIBriefPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [branchId, setBranchId] = useState('')
  const [ta, setTa] = useState('')
  const [country, setCountry] = useState('')
  const [vibe, setVibe] = useState('')
  const [nVariants, setNVariants] = useState(3)
  const [goal, setGoal] = useState('roas')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BriefResult | null>(null)
  const [err, setErr] = useState('')
  const [sendBrief, setSendBrief] = useState<Brief | null>(null)
  const [queuedMsg, setQueuedMsg] = useState('')
  const [sourceComboId, setSourceComboId] = useState('')
  const [sendLark, setSendLark] = useState<Brief | null>(null)
  const [larkMsg, setLarkMsg] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setAccounts(d.data.filter((a: Account) => a.platform === 'meta')) })
  }, [])

  // Pre-fill from query params when arriving via "Brief" on the Figma list
  // (e.g. /winning-ads/brief?branch_id=...&ta=Couple&combo_id=AbC123). Reads
  // window.location directly so we don't need a Suspense boundary for
  // useSearchParams. combo_id is the winning ad being reused — it rides through
  // to the render job as source_combo_id so it shows under "Figma only".
  useEffect(() => {
    const sp = new URLSearchParams(window.location.search)
    const b = sp.get('branch_id')
    const t = sp.get('ta')
    const c = sp.get('combo_id')
    if (b) setBranchId(b)
    if (t) setTa(t)
    if (c) setSourceComboId(c)
  }, [])

  const generate = async () => {
    if (!branchId) { setErr('Pick a branch'); return }
    setErr('')
    setLoading(true)
    setResult(null)
    try {
      const r = await fetch(`${API_BASE}/api/creative/brief`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          branch_id: branchId,
          target_audience: ta || null,
          country: country || null,
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

  return (
    <div className="p-6 max-w-5xl">
      <Link href="/winning-ads" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline mb-4">
        <ArrowLeft className="w-4 h-4" /> Back to Figma
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
            <input className="w-full border border-gray-300 rounded px-3 py-2 text-sm" placeholder="VN, JP, TW…" maxLength={2}
              value={country} onChange={e => setCountry(e.target.value.toUpperCase())} />
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
              <PatternBlock title="Top angles" dist={result.patterns.angle_distribution} />
              <PatternBlock title="Top keypoints" dist={result.patterns.keypoint_distribution} />
              <PatternBlock title="Top visual tags" dist={result.patterns.visual_distribution} />
            </div>
          </div>

          {queuedMsg && (
            <div className="bg-green-50 border border-green-200 rounded-lg p-3 mb-4 text-sm text-green-800">
              {queuedMsg}{' '}
              <Link href="/winning-ads/jobs" className="underline">View render jobs →</Link>
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
                    <button
                      onClick={() => { setQueuedMsg(''); setSendBrief(b) }}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs bg-purple-600 text-white rounded hover:bg-purple-700"
                    >
                      <Send className="w-3 h-3" /> Send to Figma
                    </button>
                    <span className="text-xs text-gray-400">Variant {i + 1}</span>
                  </div>
                </div>
                <div className="space-y-1.5 text-sm">
                  <div><span className="text-gray-500 w-20 inline-block">Hook</span><span className="font-medium">{b.hook}</span></div>
                  {b.subhead && <div><span className="text-gray-500 w-20 inline-block">Subhead</span>{b.subhead}</div>}
                  <div><span className="text-gray-500 w-20 inline-block">CTA</span><span className="font-medium text-purple-700">{b.cta}</span></div>
                  <div><span className="text-gray-500 w-20 inline-block">Angle</span>{b.angle}</div>
                  {b.keypoints?.length > 0 && (
                    <div><span className="text-gray-500 w-20 inline-block align-top">Keypoints</span>
                      <span>{b.keypoints.join(' · ')}</span>
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
                {b.rationale && <p className="text-xs text-gray-500 mt-2 italic">{b.rationale}</p>}
              </div>
            ))}
            {result.briefs.length === 0 && !result.warning && (
              <p className="text-sm text-gray-500">No briefs returned — the model may have failed to produce valid output. Try again.</p>
            )}
          </div>

          {/* Recommended templates */}
          {result.templates.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-lg p-4 mt-4">
              <h2 className="text-sm font-semibold text-gray-800 mb-2">Recommended Figma templates</h2>
              <div className="flex flex-wrap gap-2">
                {result.templates.map(t => (
                  <Link
                    key={t.id}
                    href="/winning-ads/templates"
                    className="text-xs border border-gray-200 rounded px-3 py-2 hover:bg-gray-50"
                  >
                    <span className="font-medium text-gray-800">{t.name}</span>
                    <span className="text-gray-400 ml-2">{t.size}</span>
                    <div className="text-gray-400 mt-0.5">{t.placeholder_keys.join(', ') || 'no slots'}</div>
                  </Link>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {sendBrief && (
        <SendToFigmaModal
          brief={sendBrief}
          branchId={branchId}
          sourceComboId={sourceComboId || undefined}
          onClose={() => setSendBrief(null)}
          onQueued={(jobId) => {
            setSendBrief(null)
            setQueuedMsg(`Render job queued (${jobId.slice(0, 8)}).`)
          }}
        />
      )}

      {sendLark && (
        <SendToLarkModal
          brief={sendLark}
          branchId={branchId}
          branchName={result?.branch_name || ''}
          country={country}
          ta={ta}
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
