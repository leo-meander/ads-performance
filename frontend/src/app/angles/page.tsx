'use client'

import { useEffect, useState } from 'react'
import { Plus, X } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Angle {
  id: string; angle_id: string; branch_id: string | null
  angle_type: string; angle_explain: string; hook_examples: string[]
  status: string; notes: string | null
  combos: number; spend: number; revenue: number; roas: number
  conversions: number; ctr: number
  linked_ads: { combo_id: string; ad_name: string | null; roas: number | null }[]
  avg_hook_rate: number | null; avg_thruplay_rate: number | null
  avg_engagement_rate: number | null
}
interface Account { id: string; account_name: string; platform: string }

const STATUS_COLORS: Record<string, string> = {
  WIN: 'bg-green-50 border-green-200', TEST: 'bg-yellow-50 border-yellow-200', LOSE: 'bg-red-50 border-red-200',
}
const STATUS_BADGE: Record<string, string> = {
  WIN: 'bg-green-100 text-green-700', TEST: 'bg-yellow-100 text-yellow-700', LOSE: 'bg-red-100 text-red-700',
}
const ANGLE_TYPE_LIST = [
  'Measure the size of the claim', 'Measure the speed of the claim', 'Use an authority',
  'Before and After', 'Compare the claim to its rival', 'Remove limitations from the claim',
  'State the claim as a question', 'Offer Information Directly in the claim',
  'Stress the newness of the claim', 'Stress the exclusiveness of the claim',
  "Challenge your prospect's beliefs", "Call out a solution or product they're currently using",
  'Call out the person directly',
]

export default function AnglesPage() {
  const [angles, setAngles] = useState<Angle[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [fStatus, setFStatus] = useState('')
  const [fBranch, setFBranch] = useState('')
  const [expandedAngle, setExpandedAngle] = useState<string | null>(null)

  const [formType, setFormType] = useState(ANGLE_TYPE_LIST[0])
  const [formExplain, setFormExplain] = useState('')
  const [formBranch, setFormBranch] = useState('')

  const accName = (id: string | null) => accounts.find(a => a.id === id)?.account_name || 'All'

  const fetchAngles = () => {
    setLoading(true)
    const p = new URLSearchParams()
    if (fStatus) p.set('status', fStatus)
    if (fBranch) p.set('branch_id', fBranch)
    fetch(`${API_BASE}/api/angles?${p}`)
      .then(r => r.json()).then(d => { if (d.success) setAngles(d.data) }).catch(() => {}).finally(() => setLoading(false))
  }

  useEffect(() => { fetch(`${API_BASE}/api/accounts`).then(r => r.json()).then(d => { if (d.success) setAccounts(d.data.filter((a: Account) => a.platform === 'meta')) }).catch(() => {}) }, [])
  useEffect(() => { fetchAngles() }, [fStatus, fBranch])

  const handleCreate = () => {
    fetch(`${API_BASE}/api/angles`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ branch_id: formBranch || null, angle_type: formType, angle_explain: formExplain, status: 'TEST' }),
    }).then(r => r.json()).then(d => { if (d.success) { setShowCreate(false); setFormExplain(''); fetchAngles() } })
  }

  const updateStatus = (angleId: string, s: string) => {
    fetch(`${API_BASE}/api/angles/${angleId}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: s }) }).then(() => fetchAngles())
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Ad Angles</h1>
        <button onClick={() => setShowCreate(true)} className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
          <Plus className="w-4 h-4" /> New Angle
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mb-4">
        <select value={fBranch} onChange={e => setFBranch(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="">All Branches</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </select>
        <select value={fStatus} onChange={e => setFStatus(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="">All Status</option>
          <option value="WIN">WIN</option><option value="TEST">TEST</option><option value="LOSE">LOSE</option>
        </select>
      </div>

      {showCreate && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <div className="flex justify-between mb-4"><h2 className="text-lg font-semibold">New Angle</h2><button onClick={() => setShowCreate(false)}><X className="w-5 h-5 text-gray-400" /></button></div>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div><label className="block text-xs text-gray-500 mb-1">Angle Type</label><select value={formType} onChange={e => setFormType(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">{ANGLE_TYPE_LIST.map(t => <option key={t}>{t}</option>)}</select></div>
              <div><label className="block text-xs text-gray-500 mb-1">Branch</label><select value={formBranch} onChange={e => setFormBranch(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"><option value="">All</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}</select></div>
            </div>
            <div><label className="block text-xs text-gray-500 mb-1">Strategic Approach</label><textarea value={formExplain} onChange={e => setFormExplain(e.target.value)} rows={2} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="1 sentence explaining WHY this approach works for this branch..." /></div>
            <button onClick={handleCreate} disabled={!formExplain} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">Create</button>
          </div>
        </div>
      )}

      {/* Verdict Rules */}
      <div className="bg-gray-50 rounded-lg border border-gray-200 p-3 mb-4 text-xs text-gray-600 flex flex-wrap gap-4">
        <span className="font-semibold text-gray-700">Angle Verdict Rules (2x Ad Name):</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-yellow-400 mr-1"></span><strong>TEST</strong> = Clicks ≤ 9,000 AND Bookings &lt; 10</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-green-500 mr-1"></span><strong>WIN</strong> = ROAS ≥ Account Benchmark</span>
        <span><span className="inline-block w-2 h-2 rounded-full bg-red-500 mr-1"></span><strong>LOSE</strong> = ROAS &lt; Account Benchmark</span>
      </div>

      {loading ? <div className="text-gray-500 text-center py-8">Loading...</div> : angles.length === 0 ? <div className="bg-white rounded-xl border p-8 text-center text-gray-400">No angles match filters.</div> : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {angles.map(a => (
            <div key={a.id} className={`rounded-xl border p-5 ${STATUS_COLORS[a.status] || 'bg-white border-gray-200'}`}>
              {/* Header */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs text-gray-500">{a.angle_id}</span>
                  <span className="text-[10px] text-gray-400">{accName(a.branch_id)}</span>
                </div>
                <select value={a.status} onChange={e => updateStatus(a.angle_id, e.target.value)} className={`text-xs px-2 py-0.5 rounded font-medium border-0 ${STATUS_BADGE[a.status] || ''}`}>
                  <option value="WIN">WIN</option><option value="TEST">TEST</option><option value="LOSE">LOSE</option>
                </select>
              </div>

              {/* Angle Type */}
              <p className="text-[10px] font-bold text-blue-700 uppercase tracking-wide mb-2">{a.angle_type}</p>

              {/* Strategic Approach (bold) */}
              <p className="text-sm font-semibold text-gray-900 leading-snug">{a.angle_explain}</p>

              {/* Hook Examples (smaller) */}
              {a.hook_examples && a.hook_examples.length > 0 && (
                <div className="mt-2">
                  <p className="text-[10px] text-gray-400 mb-1">Hook examples:</p>
                  <ul className="space-y-1">
                    {a.hook_examples.map((h, i) => (
                      <li key={i} className="text-xs text-gray-500 italic leading-snug">&ldquo;{h}&rdquo;</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Metrics */}
              {a.combos > 0 ? (
                <div className="pt-3 mt-3 border-t border-current/10">
                  <div className="grid grid-cols-3 gap-2 text-[11px]">
                    <div><p className="text-gray-400">ROAS</p><p className={`font-bold ${a.roas >= 1 ? 'text-green-700' : 'text-red-600'}`}>{a.roas.toFixed(2)}x</p></div>
                    <div><p className="text-gray-400">Bookings</p><p className="font-bold text-gray-800">{a.conversions}</p></div>
                    <div><p className="text-gray-400">CTR</p><p className="font-bold text-gray-800">{(a.ctr * 100).toFixed(2)}%</p></div>
                    {a.avg_hook_rate !== null && <div><p className="text-gray-400">Hook</p><p className="font-bold text-gray-800">{(a.avg_hook_rate * 100).toFixed(1)}%</p></div>}
                    {a.avg_engagement_rate !== null && <div><p className="text-gray-400">Eng.</p><p className="font-bold text-gray-800">{(a.avg_engagement_rate * 100).toFixed(1)}%</p></div>}
                    {a.avg_thruplay_rate !== null && <div><p className="text-gray-400">Thruplay</p><p className="font-bold text-gray-800">{(a.avg_thruplay_rate * 100).toFixed(1)}%</p></div>}
                  </div>
                  <button onClick={() => setExpandedAngle(expandedAngle === a.angle_id ? null : a.angle_id)} className="text-[10px] text-blue-600 hover:underline mt-2 cursor-pointer">
                    {expandedAngle === a.angle_id ? 'Hide' : `${a.combos} ads linked ▸`}
                  </button>
                  {expandedAngle === a.angle_id && a.linked_ads && (
                    <div className="mt-2 space-y-1 max-h-32 overflow-auto">
                      {a.linked_ads.map((ad, i) => (
                        <div key={i} className="flex items-center justify-between text-[10px] bg-white/60 rounded px-2 py-1">
                          <span className="text-gray-700 truncate mr-2">{ad.ad_name || ad.combo_id}</span>
                          {ad.roas !== null ? <span className={`font-bold shrink-0 ${ad.roas >= 1 ? 'text-green-600' : 'text-red-500'}`}>{ad.roas.toFixed(2)}x</span> : <span className="text-gray-300">—</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-[11px] text-gray-400 pt-3 mt-3 border-t border-current/10">No ads linked yet</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
