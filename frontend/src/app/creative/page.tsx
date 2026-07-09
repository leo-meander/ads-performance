'use client'

import { Suspense, useEffect, useMemo, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Plus, ArrowUpDown, X, Sparkles, Film, Image as ImageIcon, LayoutGrid, ExternalLink } from 'lucide-react'
import KeypointDoubleCheckModal from '@/components/KeypointDoubleCheckModal'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Combo {
  id: string; combo_id: string; branch_id: string; ad_name: string | null
  target_audience: string | null; country: string | null
  keypoint_ids: string[]; keypoint_titles: string[]
  angle_id: string | null; angle_type: string; angle_explain: string; angle_status: string
  copy_id: string; material_id: string; material_type: string | null; material_url: string | null
  verdict: string
  spend: number | null; revenue: number | null; roas: number | null; cost_per_purchase: number | null; benchmark_roas: number
  conversions: number | null; ctr: number | null
  engagement_rate: number | null; hook_rate: number | null
  thruplay_rate: number | null; video_complete_rate: number | null
}
interface Account { id: string; account_name: string }
interface Angle { angle_id: string; branch_id: string | null; angle_type: string; status: string }

const VERDICT_COLORS: Record<string, string> = {
  WIN: 'bg-green-100 text-green-700', TEST: 'bg-yellow-100 text-yellow-700', LOSE: 'bg-red-100 text-red-700',
}
const TA_LIST = ['Solo', 'Couple', 'Friend', 'Group', 'Business']

const FORMAT_META: Record<string, { label: string; Icon: typeof Film }> = {
  video: { label: 'Video', Icon: Film },
  image: { label: 'Image', Icon: ImageIcon },
  carousel: { label: 'Carousel', Icon: LayoutGrid },
}

function CreativePageInner() {
  const router = useRouter()
  // Deep-link inputs from /funnel-recommendations cards. Read once on mount;
  // subsequent URL edits don't fight the user's filter changes.
  const search = useSearchParams()
  const initialBranchHint = (search?.get('branches') || '').split(',').map(s => s.trim()).filter(Boolean)[0] || ''
  const initialTA = search?.get('ta') || ''
  const initialCountry = (search?.get('country') || '').toUpperCase()
  const initialVerdict = (search?.get('verdict') || '').toUpperCase()

  const [combos, setCombos] = useState<Combo[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [allAngles, setAllAngles] = useState<Angle[]>([])
  const [comboTotal, setComboTotal] = useState(0)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [classifyMsg, setClassifyMsg] = useState('')
  const [detailId, setDetailId] = useState<string | null>(null)
  const [kpModalCombo, setKpModalCombo] = useState<Combo | null>(null)

  // Filters
  const [fBranch, setFBranch] = useState('')
  const [fTA, setFTA] = useState(initialTA)
  const [fCountry, setFCountry] = useState(initialCountry)
  const [fVerdict, setFVerdict] = useState(initialVerdict)
  const [fFormat, setFFormat] = useState('')

  // Sort
  const [sortBy, setSortBy] = useState('')
  const [sortDir, setSortDir] = useState('desc')

  const toggleSort = (col: string) => {
    if (sortBy === col) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    } else {
      setSortBy(col)
      setSortDir('desc')
    }
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (!d.success) return
        const metaAccounts = d.data.filter((a: any) => a.platform === 'meta')
        setAccounts(metaAccounts)
        // Resolve branch-name hint from URL → first matching Meta account
        if (initialBranchHint && !fBranch) {
          const hit = metaAccounts.find((a: Account) =>
            (a.account_name || '').toLowerCase().includes(initialBranchHint.toLowerCase()),
          )
          if (hit) setFBranch(hit.id)
        }
      })
      .catch(() => {})
    fetch(`${API_BASE}/api/angles`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setAllAngles(d.data) }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Fetch combos with filters + sort
  const refetchCombos = () => {
    const params = new URLSearchParams()
    params.set('limit', '200')
    if (fBranch) params.set('branch_id', fBranch)
    if (fTA) params.set('target_audience', fTA)
    if (fCountry) params.set('country', fCountry)
    if (fVerdict) params.set('verdict', fVerdict)
    if (sortBy) { params.set('sort_by', sortBy); params.set('sort_dir', sortDir) }
    fetch(`${API_BASE}/api/combos?${params}`, { credentials: 'include' }).then(r => r.json()).then(d => {
      if (d.success) { setCombos(d.data.items); setComboTotal(d.data.total) }
    }).catch(() => {})
  }
  useEffect(() => {
    refetchCombos()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fBranch, fTA, fCountry, fVerdict, sortBy, sortDir])

  const updateVerdict = (comboId: string, verdict: string) => {
    fetch(`${API_BASE}/api/combos/${comboId}/verdict`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ verdict }) })
    setCombos(prev => prev.map(c => c.combo_id === comboId ? { ...c, verdict } : c))
  }

  const reparseTA = () => {
    if (!confirm('Re-parse TA on all combos, copies, and materials using the canonical whitelist (Solo, Couple, Friend, Group, Business)?')) return
    setClassifyMsg('Re-parsing TA...')
    fetch(`${API_BASE}/api/creative/reparse-ta`, { method: 'POST', credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          const u = d.data
          setClassifyMsg(`Re-parsed TA: ${u.combos} combos, ${u.copies} copies, ${u.materials} materials updated.`)
          refetchCombos()
        } else {
          setClassifyMsg(`Error: ${d.error}`)
        }
      })
      .catch(() => setClassifyMsg('Re-parse failed'))
  }

  const updateCombo = (comboId: string, data: { angle_id?: string; keypoint_ids?: string[] }) => {
    fetch(`${API_BASE}/api/combos/${comboId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify(data) })
      .then(() => { setEditingId(null) })
  }

  const accName = (id: string) => accounts.find(a => a.id === id)?.account_name || '—'

  // Get unique countries from combos for filter
  const countries = Array.from(new Set(combos.map(c => c.country).filter(Boolean))) as string[]

  // Derive format from ad name: [Image] → image, [Carousel] → carousel, else → video
  const inferFormat = (adName: string | null): string => {
    if (!adName) return 'video'
    const lower = adName.toLowerCase()
    if (lower.includes('[image]')) return 'image'
    if (lower.includes('[carousel]')) return 'carousel'
    return 'video'
  }

  // Client-side format filter (format isn't a server param yet)
  const visibleCombos = useMemo(
    () => combos.filter(c => !fFormat || inferFormat(c.ad_name) === fFormat),
    [combos, fFormat],
  )

  // Format-insight aggregation: spend-weighted ROAS + win-rate per format.
  const formatStats = useMemo(() => {
    const acc: Record<string, { count: number; spend: number; revenue: number; wins: number; bookings: number }> = {}
    for (const c of combos) {
      const f = inferFormat(c.ad_name)
      if (!f) continue
      const a = acc[f] || (acc[f] = { count: 0, spend: 0, revenue: 0, wins: 0, bookings: 0 })
      a.count += 1
      a.spend += c.spend || 0
      a.revenue += c.revenue || 0
      a.bookings += c.conversions || 0
      if (c.verdict === 'WIN') a.wins += 1
    }
    const rows = Object.entries(acc).map(([fmt, a]) => ({
      fmt, ...a,
      roas: a.spend > 0 ? a.revenue / a.spend : null,
      winRate: a.count > 0 ? a.wins / a.count : 0,
    }))
    rows.sort((x, y) => (y.roas ?? -1) - (x.roas ?? -1))
    return rows
  }, [combos])
  const bestFormat = formatStats.find(r => r.roas !== null) || null

  // Sort header component
  const SortHeader = ({ col, label, className = '' }: { col: string; label: string; className?: string }) => (
    <th className={`py-2 px-2 text-gray-500 font-medium text-xs cursor-pointer hover:text-gray-700 select-none ${className}`} onClick={() => toggleSort(col)}>
      <span className="inline-flex items-center gap-0.5">
        {label}
        {sortBy === col && <ArrowUpDown className="w-3 h-3" />}
      </span>
    </th>
  )

  const FormatChip = ({ type }: { type: string | null }) => {
    if (!type || !FORMAT_META[type]) return null
    const { label, Icon } = FORMAT_META[type]
    return (
      <span className="inline-flex items-center gap-1 text-[10px] text-gray-500 bg-gray-100 rounded px-1.5 py-0.5">
        <Icon className="w-3 h-3" /> {label}
      </span>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Creative Library</h1>
          <p className="text-xs text-gray-500 mt-0.5">{comboTotal} combos · click any row to see the copy, creative & why it won</p>
        </div>
        <div className="flex items-center gap-2">
          {classifyMsg && <span className="text-xs text-gray-500">{classifyMsg}</span>}
          <button
            onClick={reparseTA}
            className="bg-gray-100 text-gray-700 px-3 py-2 rounded-lg text-xs font-medium hover:bg-gray-200"
            title="Re-parse TA on all rows using Solo/Couple/Friend/Group/Business whitelist"
          >
            Re-parse TA
          </button>
          <button
            onClick={() => router.push('/creative/submit')}
            className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" /> New Combo
          </button>
        </div>
      </div>

      {/* Format Insight bar — which creative format performs best */}
      {formatStats.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
          {['video', 'image', 'carousel'].map(fmt => {
            const row = formatStats.find(r => r.fmt === fmt)
            const meta = FORMAT_META[fmt]
            if (!meta) return null
            const Icon = meta.Icon
            const active = fFormat === fmt
            const isBest = bestFormat?.fmt === fmt && formatStats.length > 1
            return (
              <button
                key={fmt}
                onClick={() => setFFormat(active ? '' : fmt)}
                className={`text-left bg-white rounded-xl border p-3 transition ${active ? 'border-blue-400 ring-2 ring-blue-100' : 'border-gray-200 hover:border-gray-300'}`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-gray-800">
                    <Icon className="w-4 h-4 text-gray-500" /> {meta.label}
                  </span>
                  {isBest && <span className="text-[9px] font-bold text-green-700 bg-green-100 rounded px-1.5 py-0.5">BEST ROAS</span>}
                </div>
                {row ? (
                  <div className="flex items-end gap-3">
                    <div>
                      <p className="text-lg font-bold text-gray-900 leading-none">{row.roas !== null ? `${row.roas.toFixed(2)}x` : '—'}</p>
                      <p className="text-[10px] text-gray-400 mt-0.5">avg ROAS</p>
                    </div>
                    <div className="text-[10px] text-gray-500 leading-tight pb-0.5">
                      <p>{row.count} ads · {(row.winRate * 100).toFixed(0)}% win</p>
                      <p>{row.bookings} bookings</p>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-gray-300">No {meta.label.toLowerCase()} ads</p>
                )}
              </button>
            )
          })}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-2 mb-4">
        <select value={fBranch} onChange={e => setFBranch(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="">All Branches</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </select>
        <select value={fTA} onChange={e => setFTA(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="">All TA</option>
          {TA_LIST.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={fCountry} onChange={e => setFCountry(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="">All Countries</option>
          {countries.sort().map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={fVerdict} onChange={e => setFVerdict(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="">All Verdicts</option>
          <option value="WIN">WIN</option><option value="TEST">TEST</option><option value="LOSE">LOSE</option>
        </select>
        <select value={fFormat} onChange={e => setFFormat(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="">All Formats</option>
          <option value="video">Video</option><option value="image">Image</option><option value="carousel">Carousel</option>
        </select>
      </div>

      {/* Verdict Rules */}
      <div className="bg-gray-50 rounded-lg border border-gray-200 p-3 mb-4 text-xs text-gray-600 flex flex-wrap gap-4">
        <span className="font-semibold text-gray-700">Verdict Rules:</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-yellow-400 mr-1"></span><strong>TEST</strong> = Clicks ≤ 4,500 AND Bookings &lt; 5</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1"></span><strong>WIN</strong> = ROAS ≥ Account Benchmark</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-red-500 mr-1"></span><strong>LOSE</strong> = ROAS &lt; Account Benchmark</span>
      </div>

      {/* Combos table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {visibleCombos.length === 0 ? <div className="p-8 text-center text-gray-400">No combos match filters.</div> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="bg-gray-50 border-b">
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Ad Name</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Branch</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">TA</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Country</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs max-w-[140px]">Keypoints</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs max-w-[140px]">Angle</th>
                <th className="text-center py-2 px-2 text-gray-500 font-medium text-xs">Verdict</th>
                <SortHeader col="roas" label="ROAS" className="text-right" />
                <SortHeader col="cost_per_purchase" label="CPP" className="text-right" />
                <SortHeader col="conversions" label="Book." className="text-right" />
                <SortHeader col="ctr" label="CTR" className="text-right" />
                <SortHeader col="engagement_rate" label="Eng%" className="text-right" />
                <SortHeader col="hook_rate" label="Hook" className="text-right" />
                <SortHeader col="thruplay_rate" label="Thru" className="text-right" />
                <SortHeader col="video_complete_rate" label="Comp" className="text-right" />
              </tr></thead>
              <tbody>{visibleCombos.map(c => (
                <tr key={c.id} onClick={() => setDetailId(c.combo_id)} className={`border-b border-gray-50 hover:bg-blue-50/40 cursor-pointer ${detailId === c.combo_id ? 'bg-blue-50' : ''}`}>
                  <td className="py-2 px-2">
                    <p className="text-sm font-medium text-gray-900 max-w-[180px] truncate" title={c.ad_name || ''}>{c.ad_name || '—'}</p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <span className="text-[10px] text-gray-400 font-mono">{c.combo_id}</span>
                      <FormatChip type={inferFormat(c.ad_name)} />
                      <button
                        onClick={e => { e.stopPropagation(); router.push(`/angles?tab=hypotheses&combo_id=${c.combo_id}`) }}
                        className="text-[9px] text-violet-500 hover:text-violet-700 bg-violet-50 hover:bg-violet-100 border border-violet-100 rounded px-1 py-0.5 font-medium"
                        title="Create hypothesis for this ad"
                      >
                        + Hypothesis
                      </button>
                    </div>
                  </td>
                  <td className="py-2 px-2 text-xs text-gray-600">{accName(c.branch_id)}</td>
                  <td className="py-2 px-2"><span className="text-xs px-1.5 py-0.5 rounded bg-gray-100">{c.target_audience || '—'}</span></td>
                  <td className="py-2 px-2 text-xs text-gray-600">{c.country || '—'}</td>
                  <td className="py-2 px-2 text-xs max-w-[180px]" onClick={e => e.stopPropagation()}>
                    <div className="mb-1">
                      {c.keypoint_titles.length > 0 ? c.keypoint_titles.map((t, i) => (
                        <span key={i} className="inline-block bg-blue-50 text-blue-700 rounded px-1 py-0.5 text-[10px] mr-1 mb-0.5">{t.length > 25 ? t.slice(0, 25) + '...' : t}</span>
                      )) : <span className="text-gray-300 text-[10px]">No keypoints</span>}
                    </div>
                    <button
                      onClick={() => setKpModalCombo(c)}
                      className="inline-flex items-center gap-1 text-[10px] font-medium text-purple-700 bg-purple-50 hover:bg-purple-100 border border-purple-200 rounded px-1.5 py-0.5"
                    >
                      <Sparkles className="w-3 h-3" /> Double check
                    </button>
                  </td>
                  <td className="py-2 px-2 text-xs max-w-[140px] relative" onClick={e => e.stopPropagation()}>
                    {editingId === `ang-${c.combo_id}` ? (
                      <div className="absolute z-10 bg-white border border-gray-200 rounded-lg shadow-lg p-2 w-56 max-h-48 overflow-auto" style={{top: 0, left: 0}}>
                        <p className="text-[10px] text-gray-400 mb-1">Select angle:</p>
                        <div onClick={() => { updateCombo(c.combo_id, { angle_id: '' }); setCombos(prev => prev.map(x => x.combo_id === c.combo_id ? { ...x, angle_id: null, angle_type: '', angle_status: '' } : x)) }} className="py-1 px-1 text-[11px] text-gray-400 cursor-pointer hover:bg-gray-50 rounded">None</div>
                        {allAngles.filter(a => !a.branch_id || a.branch_id === c.branch_id).map(a => (
                          <div key={a.angle_id} onClick={() => { updateCombo(c.combo_id, { angle_id: a.angle_id }); setCombos(prev => prev.map(x => x.combo_id === c.combo_id ? { ...x, angle_id: a.angle_id, angle_type: a.angle_type, angle_status: a.status } : x)); setEditingId(null) }}
                            className={`py-1 px-1 text-[11px] cursor-pointer hover:bg-blue-50 rounded ${c.angle_id === a.angle_id ? 'bg-blue-100' : ''}`}>
                            <span className="font-mono text-gray-400">{a.angle_id}</span> {a.angle_type}
                          </div>
                        ))}
                      </div>
                    ) : null}
                    <div onClick={() => setEditingId(editingId === `ang-${c.combo_id}` ? null : `ang-${c.combo_id}`)} className="cursor-pointer min-h-[20px]">
                      {c.angle_id ? (
                        <div>
                          <span className={`inline-block text-[10px] px-1 py-0.5 rounded font-medium ${VERDICT_COLORS[c.angle_status] || 'bg-gray-100'}`}>{c.angle_id}</span>
                          <p className="text-[10px] text-blue-600 font-semibold truncate mt-0.5" title={c.angle_type}>{c.angle_type}</p>
                        </div>
                      ) : <span className="text-gray-300 text-[10px]">+ add angle</span>}
                    </div>
                  </td>
                  <td className="py-2 px-2 text-center" onClick={e => e.stopPropagation()}>
                    <select value={c.verdict} onChange={e => updateVerdict(c.combo_id, e.target.value)} className={`text-xs px-2 py-1 rounded-full font-medium border-0 ${VERDICT_COLORS[c.verdict] || ''}`}>
                      <option value="WIN">WIN</option><option value="TEST">TEST</option><option value="LOSE">LOSE</option>
                    </select>
                  </td>
                  <td className="py-2 px-2 text-right text-xs">
                    {c.roas ? (
                      <div>
                        <span className={`font-bold ${c.roas >= c.benchmark_roas ? 'text-green-600' : 'text-red-500'}`}>{c.roas.toFixed(2)}x</span>
                        <p className="text-[9px] text-gray-400">BM: {c.benchmark_roas.toFixed(2)}x</p>
                      </div>
                    ) : '—'}
                  </td>
                  <td className="py-2 px-2 text-right text-xs">{c.cost_per_purchase ? c.cost_per_purchase.toLocaleString() : '—'}</td>
                  <td className="py-2 px-2 text-right text-xs">{c.conversions ?? '—'}</td>
                  <td className="py-2 px-2 text-right text-xs">{c.ctr ? `${(c.ctr * 100).toFixed(2)}%` : '—'}</td>
                  <td className="py-2 px-2 text-right text-xs">{c.engagement_rate ? `${(c.engagement_rate * 100).toFixed(1)}%` : '—'}</td>
                  <td className="py-2 px-2 text-right text-xs">{c.hook_rate ? `${(c.hook_rate * 100).toFixed(1)}%` : '—'}</td>
                  <td className="py-2 px-2 text-right text-xs">{c.thruplay_rate ? `${(c.thruplay_rate * 100).toFixed(1)}%` : '—'}</td>
                  <td className="py-2 px-2 text-right text-xs">{c.video_complete_rate ? `${(c.video_complete_rate * 100).toFixed(1)}%` : '—'}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </div>

      {detailId && <ComboDrawer comboId={detailId} onClose={() => setDetailId(null)} />}

      {kpModalCombo && (
        <KeypointDoubleCheckModal
          comboId={kpModalCombo.combo_id}
          branchId={kpModalCombo.branch_id}
          adName={kpModalCombo.ad_name}
          initialKeypointIds={kpModalCombo.keypoint_ids || []}
          onClose={() => setKpModalCombo(null)}
          onSaved={() => { setKpModalCombo(null); refetchCombos() }}
        />
      )}
    </div>
  )
}

// ── Detail drawer ────────────────────────────────────────────

interface ComboDetail {
  combo: any
  copy: { copy_id: string; headline: string; body_text: string; cta: string | null; language: string } | null
  material: { material_id: string; material_type: string; file_url: string; description: string | null; vision_analyzed_at: string | null; tags: Record<string, { category: string; value: string; confidence: number | null }[]> } | null
  angle: { angle_id: string; angle_type: string; explain: string; status: string } | null
  keypoints: string[]
  branch_context: any
  insight: { headline: string; reasons: { key: string; label: string; value: string; reference: string; sentiment: string; text: string }[]; positive: number; negative: number }
  working_file: { url: string; label: string | null } | null
}

const SENTIMENT_CLS: Record<string, string> = {
  positive: 'bg-green-50 border-green-200 text-green-800',
  negative: 'bg-red-50 border-red-200 text-red-800',
  neutral: 'bg-gray-50 border-gray-200 text-gray-600',
}

function CreativePreview({ material, workingFile }: { material: ComboDetail['material']; workingFile?: ComboDetail['working_file'] }) {
  const [failed, setFailed] = useState(false)
  // Designer's working file (Google Drive etc.) — a durable link that doesn't
  // expire. Shown for videos (can't inline) and whenever a preview can't render.
  const workingFileLink = workingFile?.url ? (
    <a href={workingFile.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline mt-1.5">
      <ExternalLink className="w-3 h-3" /> {workingFile.label || 'Open working file'}
    </a>
  ) : null

  if (!material?.file_url) {
    if (workingFileLink) {
      return (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 flex flex-col items-center justify-center text-center h-40">
          <p className="text-xs text-gray-500">No preview — open the working file.</p>
          {workingFileLink}
        </div>
      )
    }
    return <div className="bg-gray-100 rounded-lg h-40 flex items-center justify-center text-xs text-gray-400">No creative linked</div>
  }
  const { material_type, file_url } = material
  // Frozen base64 snapshot (set at sync time so previews never expire). Always a
  // still image — render as <img> even for video materials (it's a poster frame).
  const isSnapshot = file_url.startsWith('data:image')
  const openLink = (
    <a href={file_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline mt-1.5">
      <ExternalLink className="w-3 h-3" /> Open original creative
    </a>
  )
  if (!failed && isSnapshot) {
    // eslint-disable-next-line @next/next/no-img-element
    return (
      <div>
        <img src={file_url} alt="creative" className="w-full max-h-72 object-contain rounded-lg bg-gray-50 border border-gray-100" onError={() => setFailed(true)} />
        {material_type === 'video' && <p className="text-[10px] text-gray-400 mt-1">Video — showing poster frame</p>}
        {material_type === 'carousel' && <p className="text-[10px] text-gray-400 mt-1">Carousel — showing first frame</p>}
        {/* Poster only — the working file is the way to actually watch the video. */}
        {material_type === 'video' && workingFileLink ? workingFileLink : openLink}
      </div>
    )
  }
  if (!failed && material_type === 'video') {
    return (
      <div>
        <video src={file_url} controls className="w-full max-h-72 rounded-lg bg-black" onError={() => setFailed(true)} />
        {workingFileLink || openLink}
      </div>
    )
  }
  if (!failed && (material_type === 'image' || material_type === 'carousel')) {
    // eslint-disable-next-line @next/next/no-img-element
    return (
      <div>
        <img src={file_url} alt="creative" className="w-full max-h-72 object-contain rounded-lg bg-gray-50 border border-gray-100" onError={() => setFailed(true)} />
        {material_type === 'carousel' && <p className="text-[10px] text-gray-400 mt-1">Carousel — showing first frame</p>}
        {openLink}
      </div>
    )
  }
  // Fallback: URL can't be embedded (e.g. expired link, Drive share link) —
  // offer the durable working file if we have one, else the original link.
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 flex flex-col items-center justify-center text-center h-40">
      <p className="text-xs text-gray-500">Preview unavailable for this link.</p>
      {workingFileLink}
      {openLink}
    </div>
  )
}

function ComboDrawer({ comboId, onClose }: { comboId: string; onClose: () => void }) {
  const [data, setData] = useState<ComboDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [aiText, setAiText] = useState('')
  const [aiLoading, setAiLoading] = useState(false)
  const [aiError, setAiError] = useState('')

  useEffect(() => {
    setLoading(true); setError(''); setData(null)
    setAiText(''); setAiError('')
    fetch(`${API_BASE}/api/creative/combos/${comboId}/detail`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setData(d.data); else setError(d.error || 'Failed to load') })
      .catch(() => setError('Failed to load'))
      .finally(() => setLoading(false))
  }, [comboId])

  // Close on Escape
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const runAI = () => {
    setAiLoading(true); setAiError(''); setAiText('')
    fetch(`${API_BASE}/api/creative/combos/${comboId}/why`, { method: 'POST', credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setAiText(d.data.analysis || ''); else setAiError(d.error || 'AI analysis failed') })
      .catch(() => setAiError('AI analysis failed'))
      .finally(() => setAiLoading(false))
  }

  const c = data?.combo
  const ctx = data?.branch_context
  const currency = c?.currency || ''
  const metric = (label: string, value: string, sub?: string, cls = 'text-gray-900') => (
    <div className="bg-gray-50 rounded-lg p-2">
      <p className="text-[10px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p className={`text-sm font-bold ${cls}`}>{value}</p>
      {sub && <p className="text-[9px] text-gray-400">{sub}</p>}
    </div>
  )
  const pct = (v: number | null | undefined) => v != null ? `${(v * 100).toFixed(1)}%` : '—'

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      {/* Drawer */}
      <div className="fixed top-0 right-0 h-full w-full max-w-md bg-white z-50 shadow-2xl flex flex-col">
        <div className="flex items-start justify-between p-4 border-b border-gray-100">
          <div className="min-w-0">
            <p className="text-sm font-bold text-gray-900 truncate">{c?.ad_name || comboId}</p>
            <div className="flex items-center gap-2 mt-0.5">
              <span className="text-[10px] font-mono text-gray-400">{comboId}</span>
              {c && <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${VERDICT_COLORS[c.verdict] || ''}`}>{c.verdict}</span>}
              {data?.material && <span className="text-[10px] text-gray-500 inline-flex items-center gap-1">{FORMAT_META[data.material.material_type]?.label || data.material.material_type}</span>}
            </div>
          </div>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400"><X className="w-5 h-5" /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {loading && <p className="text-sm text-gray-400">Loading…</p>}
          {error && <p className="text-sm text-red-500">{error}</p>}

          {data && c && (
            <>
              {/* Why this verdict */}
              <section>
                <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">Why {c.verdict}</h3>
                <p className="text-sm text-gray-800 mb-2">{data.insight.headline}</p>
                <div className="space-y-1.5">
                  {data.insight.reasons.length === 0 && <p className="text-xs text-gray-400">Not enough data to explain this verdict yet.</p>}
                  {data.insight.reasons.map(r => (
                    <div key={r.key} className={`text-xs rounded-lg border px-2.5 py-1.5 ${SENTIMENT_CLS[r.sentiment] || SENTIMENT_CLS.neutral}`}>
                      {r.text}
                    </div>
                  ))}
                </div>

                {/* AI deep analysis */}
                <div className="mt-3">
                  {!aiText && (
                    <button onClick={runAI} disabled={aiLoading}
                      className="inline-flex items-center gap-1.5 text-xs font-medium text-purple-700 bg-purple-50 hover:bg-purple-100 border border-purple-200 rounded-lg px-3 py-1.5 disabled:opacity-60">
                      <Sparkles className="w-3.5 h-3.5" /> {aiLoading ? 'Analyzing…' : 'Deep analysis with AI'}
                    </button>
                  )}
                  {aiError && <p className="text-xs text-red-500 mt-1">{aiError}</p>}
                  {aiText && (
                    <div className="mt-1 bg-purple-50 border border-purple-100 rounded-lg p-3">
                      <p className="text-[10px] font-semibold text-purple-700 uppercase tracking-wide mb-1 inline-flex items-center gap-1"><Sparkles className="w-3 h-3" /> AI analysis</p>
                      <div className="text-xs text-gray-700 whitespace-pre-line leading-relaxed"
                        dangerouslySetInnerHTML={{ __html: aiText.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>') }} />
                    </div>
                  )}
                </div>
              </section>

              {/* Creative preview */}
              <section>
                <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">Creative</h3>
                <CreativePreview material={data.material} workingFile={data.working_file} />
                {data.material?.description && <p className="text-xs text-gray-500 mt-1.5">{data.material.description}</p>}
              </section>

              {/* Ad copy */}
              {data.copy && (
                <section>
                  <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">Ad copy</h3>
                  <div className="bg-gray-50 rounded-lg p-3 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono text-gray-400">{data.copy.copy_id}</span>
                      <span className="text-[10px] text-gray-400">{data.copy.language}</span>
                    </div>
                    <p className="text-sm font-semibold text-gray-900">{data.copy.headline}</p>
                    {data.copy.body_text && <p className="text-xs text-gray-600 whitespace-pre-line">{data.copy.body_text}</p>}
                    {data.copy.cta && <p className="text-xs text-blue-600 font-medium">▸ {data.copy.cta}</p>}
                  </div>
                </section>
              )}

              {/* Metrics */}
              <section>
                <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">Performance</h3>
                <div className="grid grid-cols-3 gap-2">
                  {metric('ROAS', c.roas != null ? `${c.roas.toFixed(2)}x` : '—',
                    ctx?.benchmark_roas ? `BM ${ctx.benchmark_roas.toFixed(2)}x` : undefined,
                    c.roas != null && ctx?.benchmark_roas ? (c.roas >= ctx.benchmark_roas ? 'text-green-600' : 'text-red-500') : 'text-gray-900')}
                  {metric('Bookings', c.conversions != null ? String(c.conversions) : '—')}
                  {metric('Cost/Book', c.cost_per_purchase != null ? `${currency} ${c.cost_per_purchase.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—',
                    ctx?.avg_cost_per_purchase ? `avg ${ctx.avg_cost_per_purchase.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : undefined)}
                  {metric('Spend', c.spend != null ? `${currency} ${c.spend.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—')}
                  {metric('CTR', pct(c.ctr), ctx?.avg_ctr ? `avg ${pct(ctx.avg_ctr)}` : undefined)}
                  {metric('Eng%', pct(c.engagement_rate))}
                  {data.material?.material_type === 'video' && <>
                    {metric('Hook', pct(c.hook_rate), ctx?.avg_hook_rate ? `avg ${pct(ctx.avg_hook_rate)}` : undefined)}
                    {metric('Thru', pct(c.thruplay_rate), ctx?.avg_thruplay_rate ? `avg ${pct(ctx.avg_thruplay_rate)}` : undefined)}
                    {metric('Complete', pct(c.video_complete_rate))}
                  </>}
                </div>
              </section>

              {/* Angle + keypoints */}
              {(data.angle || data.keypoints.length > 0) && (
                <section>
                  <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">Strategy</h3>
                  {data.angle && (
                    <div className="mb-2">
                      <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded font-medium ${VERDICT_COLORS[data.angle.status] || 'bg-gray-100'}`}>{data.angle.angle_id}</span>
                      <span className="text-xs font-semibold text-blue-700 ml-1.5">{data.angle.angle_type}</span>
                      {data.angle.explain && <p className="text-xs text-gray-500 mt-1">{data.angle.explain}</p>}
                    </div>
                  )}
                  {data.keypoints.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {data.keypoints.map((k, i) => <span key={i} className="inline-block bg-blue-50 text-blue-700 rounded px-1.5 py-0.5 text-[10px]">{k}</span>)}
                    </div>
                  )}
                </section>
              )}

              {/* Visual tags */}
              {data.material && Object.keys(data.material.tags).length > 0 && (
                <section>
                  <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">Visual tags</h3>
                  <div className="space-y-1.5">
                    {Object.entries(data.material.tags).map(([cat, vals]) => (
                      <div key={cat} className="flex flex-wrap items-center gap-1">
                        <span className="text-[10px] text-gray-400 w-24 shrink-0">{cat.replace(/_/g, ' ')}</span>
                        {vals.map((v, i) => <span key={i} className="inline-block bg-gray-100 text-gray-600 rounded px-1.5 py-0.5 text-[10px]">{v.value}</span>)}
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </>
  )
}

export default function CreativePage() {
  return (
    <Suspense fallback={<div className="p-6 text-gray-400">Loading...</div>}>
      <CreativePageInner />
    </Suspense>
  )
}
