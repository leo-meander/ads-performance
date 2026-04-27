'use client'

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Plus, X, ArrowUpDown } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Combo {
  id: string; combo_id: string; branch_id: string; ad_name: string | null
  target_audience: string | null; country: string | null
  keypoint_ids: string[]; keypoint_titles: string[]
  angle_id: string | null; angle_type: string; angle_explain: string; angle_status: string
  copy_id: string; material_id: string; verdict: string
  spend: number | null; roas: number | null; cost_per_purchase: number | null; benchmark_roas: number
  conversions: number | null; ctr: number | null
  engagement_rate: number | null; hook_rate: number | null
  thruplay_rate: number | null; video_complete_rate: number | null
}
interface Copy { id: string; copy_id: string; branch_id: string; target_audience: string; headline: string; body_text: string; cta: string | null; language: string; derived_verdict: string | null }
interface Material { id: string; material_id: string; branch_id: string; material_type: string; file_url: string; description: string | null; target_audience: string | null; derived_verdict: string | null }
interface Account { id: string; account_name: string }
interface Keypoint { id: string; branch_id: string; category: string; title: string }
interface Angle { angle_id: string; branch_id: string | null; angle_type: string; status: string }

const VERDICT_COLORS: Record<string, string> = {
  WIN: 'bg-green-100 text-green-700', TEST: 'bg-yellow-100 text-yellow-700', LOSE: 'bg-red-100 text-red-700',
}
const TA_LIST = ['Solo', 'Couple', 'Friend', 'Group', 'Business']

function CreativePageInner() {
  const router = useRouter()
  // Deep-link inputs from /funnel-recommendations cards. Read once on mount;
  // subsequent URL edits don't fight the user's filter changes.
  const search = useSearchParams()
  const initialBranchHint = (search?.get('branches') || '').split(',').map(s => s.trim()).filter(Boolean)[0] || ''
  const initialTA = search?.get('ta') || ''
  const initialCountry = (search?.get('country') || '').toUpperCase()
  const initialVerdict = (search?.get('verdict') || '').toUpperCase()

  const [tab, setTab] = useState<'combos' | 'copies' | 'materials'>('combos')
  const [combos, setCombos] = useState<Combo[]>([])
  const [copies, setCopies] = useState<Copy[]>([])
  const [materials, setMaterials] = useState<Material[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [allKeypoints, setAllKeypoints] = useState<Keypoint[]>([])
  const [allAngles, setAllAngles] = useState<Angle[]>([])
  const [comboTotal, setComboTotal] = useState(0)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [classifyMsg, setClassifyMsg] = useState('')

  // Filters (shared across tabs)
  const [fBranch, setFBranch] = useState('')
  const [fTA, setFTA] = useState(initialTA)
  const [fCountry, setFCountry] = useState(initialCountry)
  const [fVerdict, setFVerdict] = useState(initialVerdict)

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
    fetch(`${API_BASE}/api/keypoints`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setAllKeypoints(d.data) }).catch(() => {})
    fetch(`${API_BASE}/api/angles`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setAllAngles(d.data) }).catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Fetch combos with filters + sort
  useEffect(() => {
    const params = new URLSearchParams()
    params.set('limit', '100')
    if (fBranch) params.set('branch_id', fBranch)
    if (fTA) params.set('target_audience', fTA)
    if (fCountry) params.set('country', fCountry)
    if (fVerdict) params.set('verdict', fVerdict)
    if (sortBy) { params.set('sort_by', sortBy); params.set('sort_dir', sortDir) }
    fetch(`${API_BASE}/api/combos?${params}`, { credentials: 'include' }).then(r => r.json()).then(d => {
      if (d.success) { setCombos(d.data.items); setComboTotal(d.data.total) }
    }).catch(() => {})
  }, [fBranch, fTA, fCountry, fVerdict, sortBy, sortDir])

  // Fetch copies + materials
  useEffect(() => {
    const params = new URLSearchParams()
    params.set('limit', '200')
    if (fBranch) params.set('branch_id', fBranch)
    fetch(`${API_BASE}/api/copies?${params}`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setCopies(d.data.items) }).catch(() => {})
    fetch(`${API_BASE}/api/materials?${params}`, { credentials: 'include' }).then(r => r.json()).then(d => { if (d.success) setMaterials(d.data.items) }).catch(() => {})
  }, [fBranch])

  const updateVerdict = (comboId: string, verdict: string) => {
    fetch(`${API_BASE}/api/combos/${comboId}/verdict`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify({ verdict }) })
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
          setSortBy(s => s) // trigger combos refetch
          setFBranch(b => b) // trigger copies/materials refetch
        } else {
          setClassifyMsg(`Error: ${d.error}`)
        }
      })
      .catch(() => setClassifyMsg('Re-parse failed'))
  }

  const updateCombo = (comboId: string, data: { angle_id?: string; keypoint_ids?: string[] }) => {
    fetch(`${API_BASE}/api/combos/${comboId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, credentials: 'include', body: JSON.stringify(data) })
      .then(() => { setEditingId(null); setSortBy(s => s) /* trigger refetch */ })
  }

  const toggleKeypoint = (combo: Combo, kpId: string) => {
    const current = combo.keypoint_ids || []
    const updated = current.includes(kpId) ? current.filter(id => id !== kpId) : [...current, kpId]
    updateCombo(combo.combo_id, { keypoint_ids: updated })
    // Optimistic update
    setCombos(prev => prev.map(c => c.combo_id === combo.combo_id ? { ...c, keypoint_ids: updated, keypoint_titles: updated.map(id => allKeypoints.find(k => k.id === id)?.title || '') } : c))
  }

  const accName = (id: string) => accounts.find(a => a.id === id)?.account_name || '—'

  // Get unique countries from combos for filter
  const countries = Array.from(new Set(combos.map(c => c.country).filter(Boolean))) as string[]

  // Sort header component
  const SortHeader = ({ col, label, className = '' }: { col: string; label: string; className?: string }) => (
    <th className={`py-2 px-2 text-gray-500 font-medium text-xs cursor-pointer hover:text-gray-700 select-none ${className}`} onClick={() => toggleSort(col)}>
      <span className="inline-flex items-center gap-0.5">
        {label}
        {sortBy === col && <ArrowUpDown className="w-3 h-3" />}
      </span>
    </th>
  )

  // Filter copies/materials by TA
  const filteredCopies = copies.filter(c => !fTA || c.target_audience === fTA)
  const filteredMaterials = materials.filter(m => !fTA || m.target_audience === fTA)

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Creative Library</h1>
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

      {/* Tabs */}
      <div className="flex gap-1 mb-4 bg-gray-100 rounded-lg p-1 w-fit">
        {[
          { key: 'combos' as const, label: 'Combos', count: comboTotal },
          { key: 'copies' as const, label: 'Copies', count: filteredCopies.length },
          { key: 'materials' as const, label: 'Materials', count: filteredMaterials.length },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} className={`px-4 py-2 rounded-md text-sm font-medium transition ${tab === t.key ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
            {t.label} ({t.count})
          </button>
        ))}
      </div>

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
        {tab === 'combos' && (
          <>
            <select value={fCountry} onChange={e => setFCountry(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All Countries</option>
              {countries.sort().map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={fVerdict} onChange={e => setFVerdict(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All Verdicts</option>
              <option value="WIN">WIN</option><option value="TEST">TEST</option><option value="LOSE">LOSE</option>
            </select>
          </>
        )}
      </div>

      {/* Verdict Rules */}
      {tab === 'combos' && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-3 mb-4 text-xs text-gray-600 flex flex-wrap gap-4">
          <span className="font-semibold text-gray-700">Verdict Rules:</span>
          <span><span className="inline-block w-2 h-2 rounded-full bg-yellow-400 mr-1"></span><strong>TEST</strong> = Clicks ≤ 4,500 AND Bookings &lt; 5</span>
          <span><span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1"></span><strong>WIN</strong> = ROAS ≥ Account Benchmark</span>
          <span><span className="inline-block w-2 h-2 rounded-full bg-red-500 mr-1"></span><strong>LOSE</strong> = ROAS &lt; Account Benchmark</span>
        </div>
      )}

      {/* Combos Tab */}
      {tab === 'combos' && (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {combos.length === 0 ? <div className="p-8 text-center text-gray-400">No combos match filters.</div> : (
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
                <tbody>{combos.map(c => (
                  <tr key={c.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-2 px-2">
                      <p className="text-sm font-medium text-gray-900 max-w-[180px] truncate" title={c.ad_name || ''}>{c.ad_name || '—'}</p>
                      <p className="text-[10px] text-gray-400 font-mono">{c.combo_id}</p>
                    </td>
                    <td className="py-2 px-2 text-xs text-gray-600">{accName(c.branch_id)}</td>
                    <td className="py-2 px-2"><span className="text-xs px-1.5 py-0.5 rounded bg-gray-100">{c.target_audience || '—'}</span></td>
                    <td className="py-2 px-2 text-xs text-gray-600">{c.country || '—'}</td>
                    <td className="py-2 px-2 text-xs max-w-[160px] relative">
                      {editingId === `kp-${c.combo_id}` ? (
                        <div className="absolute z-10 bg-white border border-gray-200 rounded-lg shadow-lg p-2 w-56 max-h-48 overflow-auto" style={{top: 0, left: 0}}>
                          <p className="text-[10px] text-gray-400 mb-1">Select keypoints:</p>
                          {allKeypoints.filter(k => k.branch_id === c.branch_id).map(k => (
                            <label key={k.id} className="flex items-center gap-1.5 py-1 text-[11px] cursor-pointer hover:bg-gray-50 rounded px-1">
                              <input type="checkbox" checked={(c.keypoint_ids || []).includes(k.id)} onChange={() => toggleKeypoint(c, k.id)} className="w-3 h-3" />
                              <span className="text-gray-400">[{k.category}]</span> {k.title}
                            </label>
                          ))}
                          <button onClick={() => setEditingId(null)} className="text-[10px] text-blue-600 mt-1">Done</button>
                        </div>
                      ) : null}
                      <div onClick={() => setEditingId(editingId === `kp-${c.combo_id}` ? null : `kp-${c.combo_id}`)} className="cursor-pointer min-h-[20px]">
                        {c.keypoint_titles.length > 0 ? c.keypoint_titles.map((t, i) => (
                          <span key={i} className="inline-block bg-blue-50 text-blue-700 rounded px-1 py-0.5 text-[10px] mr-1 mb-0.5">{t.length > 25 ? t.slice(0, 25) + '...' : t}</span>
                        )) : <span className="text-gray-300 text-[10px]">+ add keypoints</span>}
                      </div>
                    </td>
                    <td className="py-2 px-2 text-xs max-w-[140px] relative">
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
                    <td className="py-2 px-2 text-center">
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
      )}

      {/* Copies Tab */}
      {tab === 'copies' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {filteredCopies.length === 0 ? <div className="col-span-2 bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">No copies match filters.</div> :
            filteredCopies.map(c => (
              <div key={c.id} className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-mono text-xs text-gray-500">{c.copy_id}</span>
                  <span className="text-xs px-2 py-0.5 rounded bg-gray-100">{c.target_audience}</span>
                  <span className="text-xs text-gray-400">{c.language}</span>
                  {c.derived_verdict && <span className={`text-xs px-2 py-0.5 rounded font-medium ${VERDICT_COLORS[c.derived_verdict] || ''}`}>{c.derived_verdict}</span>}
                </div>
                <p className="font-medium text-gray-900 text-sm">{c.headline}</p>
                <p className="text-xs text-gray-600 mt-1 line-clamp-3">{c.body_text}</p>
                {c.cta && <p className="text-xs text-blue-600 mt-1">{c.cta}</p>}
                <p className="text-xs text-gray-400 mt-2">{accName(c.branch_id)}</p>
              </div>
            ))
          }
        </div>
      )}

      {/* Materials Tab */}
      {tab === 'materials' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {filteredMaterials.length === 0 ? <div className="col-span-3 bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">No materials match filters.</div> :
            filteredMaterials.map(m => (
              <div key={m.id} className="bg-white rounded-xl border border-gray-200 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-mono text-xs text-gray-500">{m.material_id}</span>
                  <span className="text-xs px-2 py-0.5 rounded bg-gray-100">{m.material_type}</span>
                  {m.target_audience && <span className="text-xs px-2 py-0.5 rounded bg-gray-100">{m.target_audience}</span>}
                  {m.derived_verdict && <span className={`text-xs px-2 py-0.5 rounded font-medium ${VERDICT_COLORS[m.derived_verdict] || ''}`}>{m.derived_verdict}</span>}
                </div>
                <p className="text-sm text-gray-600">{m.description || 'No description'}</p>
                <a href={m.file_url} target="_blank" rel="noopener noreferrer" className="text-xs text-blue-600 hover:underline mt-1 block truncate">{m.file_url}</a>
                <p className="text-xs text-gray-400 mt-2">{accName(m.branch_id)}</p>
              </div>
            ))
          }
        </div>
      )}
    </div>
  )
}

export default function CreativePage() {
  return (
    <Suspense fallback={<div className="p-6 text-gray-400">Loading...</div>}>
      <CreativePageInner />
    </Suspense>
  )
}
