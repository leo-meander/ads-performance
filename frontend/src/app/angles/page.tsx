'use client'

import { useEffect, useState } from 'react'
import { Plus, X, ChevronDown, ChevronRight, Brain, Lightbulb, FlaskConical } from 'lucide-react'
import { useAuth } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Angle {
  id: string; angle_id: string; branch_id: string | null
  angle_type: string; angle_explain: string; hook_examples: string[]
  human_desire: string | null; emotional_theme: string | null
  applicable_to: string[] | null; story_structure: string | null
  visual_patterns: string[] | null
  status: string; notes: string | null
  combos: number; spend: number; revenue: number; roas: number
  conversions: number; ctr: number
  linked_ads: { combo_id: string; ad_name: string | null; roas: number | null }[]
  avg_hook_rate: number | null; avg_thruplay_rate: number | null
  avg_engagement_rate: number | null
  branch_verdict: string | null; branch_benchmark: number | null
}

interface BrandIdentity {
  branch_name: string
  human_desires: string[]
  brand_territory: string | null
  brand_promise: string | null
  emotional_themes: string[]
  never_say: string[]
  always_say: string[]
  feeling_target: string | null
}

interface Hypothesis {
  id: string; hypothesis_id: string; branch_name: string
  human_desire: string | null; creative_angle: string | null
  target_audience: string | null; market: string | null
  hypothesis: string; variable_tested: string | null
  primary_kpi: string | null; secondary_kpi: string | null
  expected_outcome: string | null; status: string
  actual_ctr: number | null; actual_roas: number | null
  learning: string | null; created_at: string
}

interface Account { id: string; account_name: string; platform: string }

const STATUS_COLORS: Record<string, string> = {
  WIN: 'bg-green-50 border-green-200', TEST: 'bg-yellow-50 border-yellow-200', LOSE: 'bg-red-50 border-red-200',
}
const STATUS_BADGE: Record<string, string> = {
  WIN: 'bg-green-100 text-green-700', TEST: 'bg-yellow-100 text-yellow-700', LOSE: 'bg-red-100 text-red-700',
}
const HYPO_STATUS_BADGE: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-600',
  running: 'bg-blue-100 text-blue-700',
  validated: 'bg-green-100 text-green-700',
  refuted: 'bg-red-100 text-red-700',
  inconclusive: 'bg-orange-100 text-orange-700',
}

const HUMAN_DESIRES = [
  'Belonging', 'Discovery', 'Recovery', 'Fulfillment', 'Immersion',
  'Romance', 'Freedom', 'Calm', 'Adventure', 'Status',
  'Achievement', 'Escape', 'Curiosity', 'Play', 'Growth', 'Security', 'Nostalgia',
]
const STORY_STRUCTURES = [
  'Curiosity Loop', 'Slice of Life', 'Hero Journey',
  'Before vs After', 'Open Loop', '3 Act', 'Conversation', 'Voice Over',
]
const VISUAL_PATTERNS = [
  'POV', 'Interview', 'Mini Documentary', 'UGC',
  'Found Footage', 'Vlog', 'Static Camera', 'Drone', 'Timelapse',
]
const BRANCH_NAMES = ['Meander Taipei', 'Oani', 'Meander Osaka', 'Meander Saigon', 'Meander 1948']

const DESIRE_COLOR: Record<string, string> = {
  Belonging: 'bg-purple-50 border-purple-200 text-purple-800',
  Discovery: 'bg-amber-50 border-amber-200 text-amber-800',
  Recovery: 'bg-teal-50 border-teal-200 text-teal-800',
  Fulfillment: 'bg-orange-50 border-orange-200 text-orange-800',
  Immersion: 'bg-rose-50 border-rose-200 text-rose-800',
  Curiosity: 'bg-amber-50 border-amber-200 text-amber-800',
}
const DESIRE_DOT: Record<string, string> = {
  Belonging: 'bg-purple-400', Discovery: 'bg-amber-400', Recovery: 'bg-teal-400',
  Fulfillment: 'bg-orange-400', Immersion: 'bg-rose-400', Curiosity: 'bg-amber-400',
}

type Tab = 'angles' | 'brand' | 'hypotheses'

export default function AnglesPage() {
  const { canEditSection } = useAuth()
  const canEdit = canEditSection('meta_ads')

  const [tab, setTab] = useState<Tab>('angles')
  const [angles, setAngles] = useState<Angle[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [brandIdentities, setBrandIdentities] = useState<BrandIdentity[]>([])
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [showCreateHypo, setShowCreateHypo] = useState(false)
  const [fStatus, setFStatus] = useState('')
  const [fBranch, setFBranch] = useState('')
  const [fDesire, setFDesire] = useState('')
  const [expandedAngle, setExpandedAngle] = useState<string | null>(null)
  const [collapsedDesires, setCollapsedDesires] = useState<Set<string>>(new Set())

  // Create angle form
  const [formType, setFormType] = useState('')
  const [formExplain, setFormExplain] = useState('')
  const [formBranch, setFormBranch] = useState('')
  const [formDesire, setFormDesire] = useState('')
  const [formTheme, setFormTheme] = useState('')
  const [formStory, setFormStory] = useState('')
  const [formApplicable, setFormApplicable] = useState<string[]>([])
  const [formVisuals, setFormVisuals] = useState<string[]>([])

  // Create hypothesis form
  const [hypoForm, setHypoForm] = useState({
    branch_name: '', human_desire: '', creative_angle: '',
    target_audience: '', market: '', hypothesis: '',
    variable_tested: '', primary_kpi: 'CTR', secondary_kpi: '',
    expected_outcome: '',
  })

  const fetchAngles = () => {
    setLoading(true)
    const p = new URLSearchParams()
    if (fStatus) p.set('status', fStatus)
    if (fBranch) p.set('branch_id', fBranch)
    fetch(`${API_BASE}/api/angles?${p}`, { credentials: 'include' })
      .then(r => r.json()).then(d => { if (d.success) setAngles(d.data) }).catch(() => {}).finally(() => setLoading(false))
  }

  const fetchBrandIdentities = () => {
    fetch(`${API_BASE}/api/brand-intelligence`, { credentials: 'include' })
      .then(r => r.json()).then(d => { if (d.success) setBrandIdentities(d.data) }).catch(() => {})
  }

  const fetchHypotheses = () => {
    fetch(`${API_BASE}/api/hypotheses?limit=100`, { credentials: 'include' })
      .then(r => r.json()).then(d => { if (d.success) setHypotheses(d.data.items) }).catch(() => {})
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json()).then(d => { if (d.success) setAccounts(d.data.filter((a: Account) => a.platform === 'meta')) }).catch(() => {})
    fetchBrandIdentities()
    fetchHypotheses()
  }, [])

  useEffect(() => { fetchAngles() }, [fStatus, fBranch])

  const handleCreate = () => {
    fetch(`${API_BASE}/api/angles`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        branch_id: formBranch || null,
        angle_type: formType,
        angle_explain: formExplain,
        human_desire: formDesire || null,
        emotional_theme: formTheme || null,
        applicable_to: formApplicable.length ? formApplicable : null,
        story_structure: formStory || null,
        visual_patterns: formVisuals.length ? formVisuals : null,
        status: 'TEST',
      }),
    }).then(r => r.json()).then(d => {
      if (d.success) { setShowCreate(false); setFormType(''); setFormExplain(''); fetchAngles() }
    })
  }

  const handleCreateHypo = () => {
    fetch(`${API_BASE}/api/hypotheses`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(hypoForm),
    }).then(r => r.json()).then(d => {
      if (d.success) {
        setShowCreateHypo(false)
        setHypoForm({ branch_name: '', human_desire: '', creative_angle: '', target_audience: '', market: '', hypothesis: '', variable_tested: '', primary_kpi: 'CTR', secondary_kpi: '', expected_outcome: '' })
        fetchHypotheses()
      }
    })
  }

  const updateStatus = (angleId: string, s: string) => {
    fetch(`${API_BASE}/api/angles/${angleId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      credentials: 'include', body: JSON.stringify({ status: s }),
    }).then(() => fetchAngles())
  }

  const toggleDesire = (desire: string) => {
    setCollapsedDesires(prev => {
      const n = new Set(prev)
      if (n.has(desire)) n.delete(desire); else n.add(desire)
      return n
    })
  }

  // Group angles by Human Desire
  const filtered = angles.filter(a => !fDesire || a.human_desire === fDesire)
  const byDesire: Record<string, Angle[]> = {}
  filtered.forEach(a => {
    const key = a.human_desire || 'Uncategorized'
    ;(byDesire[key] = byDesire[key] || []).push(a)
  })
  const desireOrder = [...HUMAN_DESIRES, 'Uncategorized']
  const sortedDesires = Object.keys(byDesire).sort((a, b) => desireOrder.indexOf(a) - desireOrder.indexOf(b))

  const accName = (id: string | null) => accounts.find(a => a.id === id)?.account_name || 'All'

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Creative Intelligence</h1>
        <div className="flex gap-2">
          {canEdit && tab === 'angles' && (
            <button onClick={() => setShowCreate(true)} className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
              <Plus className="w-4 h-4" /> New Angle
            </button>
          )}
          {canEdit && tab === 'hypotheses' && (
            <button onClick={() => setShowCreateHypo(true)} className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 text-white rounded-lg text-sm font-medium hover:bg-violet-700">
              <Plus className="w-4 h-4" /> New Hypothesis
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200 mb-6">
        {([
          { key: 'angles', label: 'Creative Angles', icon: Lightbulb },
          { key: 'brand', label: 'Brand Intelligence', icon: Brain },
          { key: 'hypotheses', label: 'Hypotheses', icon: FlaskConical },
        ] as const).map(({ key, label, icon: Icon }) => (
          <button key={key} onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${tab === key ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            <Icon className="w-4 h-4" />{label}
          </button>
        ))}
      </div>

      {/* ── TAB: ANGLES ── */}
      {tab === 'angles' && (
        <>
          <div className="flex flex-wrap gap-2 mb-4">
            <select value={fBranch} onChange={e => setFBranch(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All Branches</option>
              {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
            </select>
            <select value={fDesire} onChange={e => setFDesire(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All Desires</option>
              {HUMAN_DESIRES.map(d => <option key={d}>{d}</option>)}
            </select>
            <select value={fStatus} onChange={e => setFStatus(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All Status</option>
              <option value="WIN">WIN</option><option value="TEST">TEST</option><option value="LOSE">LOSE</option>
            </select>
          </div>

          {showCreate && (
            <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
              <div className="flex justify-between mb-4">
                <h2 className="text-lg font-semibold">New Creative Angle</h2>
                <button onClick={() => setShowCreate(false)}><X className="w-5 h-5 text-gray-400" /></button>
              </div>
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div><label className="block text-xs text-gray-500 mb-1">Creative Angle Name *</label>
                    <input value={formType} onChange={e => setFormType(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="e.g. Strangers Become Friends" /></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Human Desire</label>
                    <select value={formDesire} onChange={e => setFormDesire(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                      <option value="">Select...</option>{HUMAN_DESIRES.map(d => <option key={d}>{d}</option>)}
                    </select></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Emotional Theme</label>
                    <input value={formTheme} onChange={e => setFormTheme(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="e.g. First Friend, Shared Meal" /></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Story Structure</label>
                    <select value={formStory} onChange={e => setFormStory(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                      <option value="">Select...</option>{STORY_STRUCTURES.map(s => <option key={s}>{s}</option>)}
                    </select></div>
                </div>
                <div><label className="block text-xs text-gray-500 mb-1">Strategic Approach *</label>
                  <textarea value={formExplain} onChange={e => setFormExplain(e.target.value)} rows={2} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="WHY this angle works — what emotion it targets and how..." /></div>
                <div><label className="block text-xs text-gray-500 mb-1">Applicable To (empty = universal)</label>
                  <div className="flex flex-wrap gap-2">{BRANCH_NAMES.map(b => (
                    <label key={b} className="flex items-center gap-1 text-xs cursor-pointer">
                      <input type="checkbox" checked={formApplicable.includes(b)} onChange={e => setFormApplicable(prev => e.target.checked ? [...prev, b] : prev.filter(x => x !== b))} />
                      {b}
                    </label>
                  ))}</div>
                </div>
                <div><label className="block text-xs text-gray-500 mb-1">Visual Patterns</label>
                  <div className="flex flex-wrap gap-2">{VISUAL_PATTERNS.map(v => (
                    <label key={v} className="flex items-center gap-1 text-xs cursor-pointer">
                      <input type="checkbox" checked={formVisuals.includes(v)} onChange={e => setFormVisuals(prev => e.target.checked ? [...prev, v] : prev.filter(x => x !== v))} />
                      {v}
                    </label>
                  ))}</div>
                </div>
                <div><label className="block text-xs text-gray-500 mb-1">Branch Account</label>
                  <select value={formBranch} onChange={e => setFormBranch(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                    <option value="">Universal (no branch)</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
                  </select></div>
                <button onClick={handleCreate} disabled={!formType || !formExplain} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">Create Angle</button>
              </div>
            </div>
          )}

          {loading ? <div className="text-gray-500 text-center py-8">Loading...</div> : sortedDesires.length === 0 ? (
            <div className="bg-white rounded-xl border p-8 text-center text-gray-400">No angles match filters.</div>
          ) : (
            <div className="space-y-6">
              {sortedDesires.map(desire => {
                const desireAngles = byDesire[desire]
                const colorCls = DESIRE_COLOR[desire] || 'bg-gray-50 border-gray-200 text-gray-700'
                const dotCls = DESIRE_DOT[desire] || 'bg-gray-400'
                const isCollapsed = collapsedDesires.has(desire)
                // Group by emotional theme within desire
                const byTheme: Record<string, Angle[]> = {}
                desireAngles.forEach(a => {
                  const t = a.emotional_theme || 'General'
                  ;(byTheme[t] = byTheme[t] || []).push(a)
                })
                return (
                  <div key={desire}>
                    <button onClick={() => toggleDesire(desire)}
                      className={`flex items-center gap-3 w-full text-left px-4 py-3 rounded-xl border font-semibold text-sm mb-3 ${colorCls}`}>
                      <span className={`w-2.5 h-2.5 rounded-full ${dotCls} shrink-0`} />
                      <span className="flex-1">Human Desire: {desire}</span>
                      <span className="text-xs font-normal opacity-70">{desireAngles.length} angles</span>
                      {isCollapsed ? <ChevronRight className="w-4 h-4 opacity-60" /> : <ChevronDown className="w-4 h-4 opacity-60" />}
                    </button>

                    {!isCollapsed && (
                      <div className="space-y-4 pl-2">
                        {Object.entries(byTheme).map(([theme, themeAngles]) => (
                          <div key={theme}>
                            {theme !== 'General' && (
                              <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-2 pl-1">{theme}</p>
                            )}
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                              {themeAngles.map(a => (
                                <div key={a.id} className={`rounded-xl border p-5 ${STATUS_COLORS[(fBranch && a.branch_verdict) || a.status] || 'bg-white border-gray-200'}`}>
                                  <div className="flex items-center justify-between mb-2">
                                    <div className="flex items-center gap-2">
                                      <span className="font-mono text-xs text-gray-400">{a.angle_id}</span>
                                      {a.applicable_to && a.applicable_to.length > 0 && (
                                        <span className="text-[9px] text-gray-400 italic">{a.applicable_to.join(', ')}</span>
                                      )}
                                    </div>
                                    {fBranch && a.branch_verdict ? (
                                      <span className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_BADGE[a.branch_verdict] || ''}`}>{a.branch_verdict}</span>
                                    ) : (
                                      <select value={a.status} onChange={e => updateStatus(a.angle_id, e.target.value)}
                                        className={`text-xs px-2 py-0.5 rounded font-medium border-0 ${STATUS_BADGE[a.status] || ''}`}>
                                        <option value="WIN">WIN</option><option value="TEST">TEST</option><option value="LOSE">LOSE</option>
                                      </select>
                                    )}
                                  </div>

                                  <p className="text-sm font-bold text-gray-900 leading-snug mb-1">{a.angle_type}</p>
                                  {a.story_structure && (
                                    <p className="text-[10px] text-blue-600 mb-2">↳ {a.story_structure}</p>
                                  )}
                                  <p className="text-xs text-gray-600 leading-relaxed">{a.angle_explain}</p>

                                  {a.visual_patterns && a.visual_patterns.length > 0 && (
                                    <div className="flex flex-wrap gap-1 mt-2">
                                      {a.visual_patterns.map(v => (
                                        <span key={v} className="text-[9px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{v}</span>
                                      ))}
                                    </div>
                                  )}

                                  {a.hook_examples && a.hook_examples.length > 0 && (
                                    <div className="mt-2 border-t border-current/10 pt-2">
                                      <p className="text-[10px] text-gray-400 mb-1">Hook examples:</p>
                                      <ul className="space-y-1">
                                        {a.hook_examples.map((h, i) => (
                                          <li key={i} className="text-xs text-gray-500 italic leading-snug">&ldquo;{h}&rdquo;</li>
                                        ))}
                                      </ul>
                                    </div>
                                  )}

                                  {a.combos > 0 ? (
                                    <div className="pt-3 mt-3 border-t border-current/10">
                                      <div className="grid grid-cols-3 gap-2 text-[11px]">
                                        <div><p className="text-gray-400">ROAS</p><p className={`font-bold ${a.roas >= 1 ? 'text-green-700' : 'text-red-600'}`}>{a.roas.toFixed(2)}x</p></div>
                                        <div><p className="text-gray-400">Bookings</p><p className="font-bold text-gray-800">{a.conversions}</p></div>
                                        <div><p className="text-gray-400">CTR</p><p className="font-bold text-gray-800">{(a.ctr * 100).toFixed(2)}%</p></div>
                                        {a.avg_hook_rate !== null && <div><p className="text-gray-400">Hook</p><p className="font-bold text-gray-800">{(a.avg_hook_rate * 100).toFixed(1)}%</p></div>}
                                      </div>
                                      <button onClick={() => setExpandedAngle(expandedAngle === a.angle_id ? null : a.angle_id)}
                                        className="text-[10px] text-blue-600 hover:underline mt-2 cursor-pointer">
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
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}

      {/* ── TAB: BRAND INTELLIGENCE ── */}
      {tab === 'brand' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {brandIdentities.length === 0 ? (
            <div className="col-span-2 text-center text-gray-400 py-8">No brand identities found. Run migration 052.</div>
          ) : brandIdentities.map(b => (
            <div key={b.branch_name} className="bg-white rounded-xl border border-gray-200 p-6">
              <div className="mb-4">
                <h2 className="text-lg font-bold text-gray-900">{b.branch_name}</h2>
                {b.brand_territory && <span className="text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full font-medium">{b.brand_territory}</span>}
              </div>

              {b.feeling_target && (
                <div className="bg-gray-50 rounded-lg p-3 mb-4">
                  <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Core Question</p>
                  <p className="text-sm text-gray-700 italic">{b.feeling_target}</p>
                </div>
              )}

              {b.brand_promise && (
                <div className="mb-4">
                  <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Brand Promise</p>
                  <p className="text-sm font-semibold text-gray-800">{b.brand_promise}</p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                {b.human_desires.length > 0 && (
                  <div>
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1.5">Human Desires</p>
                    <div className="flex flex-wrap gap-1">
                      {b.human_desires.map(d => <span key={d} className="text-xs bg-purple-50 text-purple-700 px-2 py-0.5 rounded-full">{d}</span>)}
                    </div>
                  </div>
                )}
                {b.emotional_themes.length > 0 && (
                  <div>
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1.5">Emotional Themes</p>
                    <div className="flex flex-wrap gap-1">
                      {b.emotional_themes.map(t => <span key={t} className="text-xs bg-amber-50 text-amber-700 px-2 py-0.5 rounded-full">{t}</span>)}
                    </div>
                  </div>
                )}
                {b.always_say.length > 0 && (
                  <div>
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1.5">Always Say</p>
                    <div className="flex flex-wrap gap-1">
                      {b.always_say.map(w => <span key={w} className="text-xs bg-green-50 text-green-700 px-2 py-0.5 rounded-full">{w}</span>)}
                    </div>
                  </div>
                )}
                {b.never_say.length > 0 && (
                  <div>
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1.5">Never Say</p>
                    <div className="flex flex-wrap gap-1">
                      {b.never_say.map(w => <span key={w} className="text-xs bg-red-50 text-red-700 px-2 py-0.5 rounded-full">{w}</span>)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── TAB: HYPOTHESES ── */}
      {tab === 'hypotheses' && (
        <>
          {showCreateHypo && (
            <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
              <div className="flex justify-between mb-4">
                <h2 className="text-lg font-semibold">New Creative Hypothesis</h2>
                <button onClick={() => setShowCreateHypo(false)}><X className="w-5 h-5 text-gray-400" /></button>
              </div>
              <div className="space-y-3">
                <div className="grid grid-cols-3 gap-3">
                  <div><label className="block text-xs text-gray-500 mb-1">Branch *</label>
                    <select value={hypoForm.branch_name} onChange={e => setHypoForm(p => ({ ...p, branch_name: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                      <option value="">Select...</option>{BRANCH_NAMES.map(b => <option key={b}>{b}</option>)}
                    </select></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Human Desire</label>
                    <select value={hypoForm.human_desire} onChange={e => setHypoForm(p => ({ ...p, human_desire: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                      <option value="">Select...</option>{HUMAN_DESIRES.map(d => <option key={d}>{d}</option>)}
                    </select></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Creative Angle</label>
                    <input value={hypoForm.creative_angle} onChange={e => setHypoForm(p => ({ ...p, creative_angle: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="e.g. Strangers Become Friends" /></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Target Audience</label>
                    <input value={hypoForm.target_audience} onChange={e => setHypoForm(p => ({ ...p, target_audience: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="Solo / Couple..." /></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Market</label>
                    <input value={hypoForm.market} onChange={e => setHypoForm(p => ({ ...p, market: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="US / VN / TW..." /></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Primary KPI</label>
                    <select value={hypoForm.primary_kpi} onChange={e => setHypoForm(p => ({ ...p, primary_kpi: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                      {['CTR', 'CVR', 'ROAS', 'LPV', 'Hook Rate', 'Thruplay'].map(k => <option key={k}>{k}</option>)}
                    </select></div>
                </div>
                <div><label className="block text-xs text-gray-500 mb-1">Hypothesis *</label>
                  <textarea value={hypoForm.hypothesis} onChange={e => setHypoForm(p => ({ ...p, hypothesis: e.target.value }))} rows={2} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="Solo travelers are more likely to click when they see real social interactions than room aesthetics." /></div>
                <div className="grid grid-cols-2 gap-3">
                  <div><label className="block text-xs text-gray-500 mb-1">Variable Tested</label>
                    <input value={hypoForm.variable_tested} onChange={e => setHypoForm(p => ({ ...p, variable_tested: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="Social scene vs Room scene" /></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Expected Outcome</label>
                    <input value={hypoForm.expected_outcome} onChange={e => setHypoForm(p => ({ ...p, expected_outcome: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="+20% CTR" /></div>
                </div>
                <button onClick={handleCreateHypo} disabled={!hypoForm.branch_name || !hypoForm.hypothesis}
                  className="px-4 py-2 bg-violet-600 text-white rounded-lg text-sm font-medium hover:bg-violet-700 disabled:opacity-50">Create Hypothesis</button>
              </div>
            </div>
          )}

          {hypotheses.length === 0 ? (
            <div className="bg-white rounded-xl border p-8 text-center text-gray-400">
              <FlaskConical className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p>No hypotheses yet.</p>
              <p className="text-xs mt-1">Each ad idea should have a hypothesis before it runs.</p>
            </div>
          ) : (() => {
            // Summary stats
            const concluded = hypotheses.filter(h => ['validated','refuted'].includes(h.status))
            const running = hypotheses.filter(h => h.status === 'running')
            const pending = hypotheses.filter(h => h.status === 'pending')
            const validated = hypotheses.filter(h => h.status === 'validated')
            // Group learnings by desire
            const learningsByDesire: Record<string, Hypothesis[]> = {}
            concluded.filter(h => h.learning).forEach(h => {
              const k = h.human_desire || 'General'
              ;(learningsByDesire[k] = learningsByDesire[k] || []).push(h)
            })
            return (
              <div className="space-y-6">
                {/* Summary bar */}
                <div className="grid grid-cols-4 gap-3">
                  {[
                    { label: 'Total', value: hypotheses.length, cls: 'text-gray-800' },
                    { label: 'Running', value: running.length, cls: 'text-blue-700' },
                    { label: 'Validated', value: validated.length, cls: 'text-green-700' },
                    { label: 'Refuted', value: hypotheses.filter(h=>h.status==='refuted').length, cls: 'text-red-600' },
                  ].map(s => (
                    <div key={s.label} className="bg-white rounded-xl border border-gray-200 p-4 text-center">
                      <p className={`text-2xl font-bold ${s.cls}`}>{s.value}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{s.label}</p>
                    </div>
                  ))}
                </div>

                {/* Learnings by Desire */}
                {Object.keys(learningsByDesire).length > 0 && (
                  <div className="bg-violet-50 rounded-xl border border-violet-100 p-5">
                    <p className="text-xs font-semibold text-violet-700 uppercase tracking-wider mb-3">Validated Learnings</p>
                    <div className="space-y-3">
                      {Object.entries(learningsByDesire).map(([desire, items]) => (
                        <div key={desire}>
                          <p className="text-[10px] font-bold text-violet-500 uppercase tracking-widest mb-1.5">{desire}</p>
                          {items.map(h => (
                            <div key={h.id} className="flex items-start gap-2 mb-1.5">
                              <span className={`mt-0.5 shrink-0 w-1.5 h-1.5 rounded-full ${h.status === 'validated' ? 'bg-green-500' : 'bg-red-400'}`} />
                              <p className="text-xs text-gray-700">{h.learning} <span className="text-gray-400">({h.creative_angle})</span></p>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Hypothesis list */}
                <div className="space-y-3">
                  {hypotheses.map(h => {
                    const hasResult = h.actual_roas !== null || h.actual_ctr !== null
                    return (
                    <div key={h.id} className={`bg-white rounded-xl border p-5 ${h.status === 'validated' ? 'border-green-200' : h.status === 'refuted' ? 'border-red-200' : 'border-gray-200'}`}>
                      <div className="flex items-start gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap mb-2">
                            <span className="font-mono text-xs text-gray-400">{h.hypothesis_id}</span>
                            <span className="text-xs text-gray-500">{h.branch_name}</span>
                            {h.human_desire && <span className="text-xs bg-purple-50 text-purple-700 px-2 py-0.5 rounded-full">{h.human_desire}</span>}
                            {h.creative_angle && <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">{h.creative_angle}</span>}
                            {h.target_audience && <span className="text-xs text-gray-400">{h.target_audience}</span>}
                            {h.market && <span className="text-xs text-gray-400">{h.market}</span>}
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${HYPO_STATUS_BADGE[h.status] || 'bg-gray-100 text-gray-600'}`}>{h.status}</span>
                          </div>
                          <p className="text-sm font-medium text-gray-800 mb-2">{h.hypothesis}</p>

                          {/* Expected vs Actual */}
                          {(h.variable_tested || h.expected_outcome || hasResult) && (
                            <div className="grid grid-cols-2 gap-3 mb-2">
                              <div className="bg-gray-50 rounded-lg p-3">
                                <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Expected</p>
                                {h.variable_tested && <p className="text-xs text-gray-600 mb-0.5">Variable: {h.variable_tested}</p>}
                                {h.primary_kpi && <p className="text-xs text-gray-600 mb-0.5">KPI: {h.primary_kpi}</p>}
                                {h.expected_outcome && <p className="text-xs font-semibold text-gray-800">{h.expected_outcome}</p>}
                              </div>
                              <div className={`rounded-lg p-3 ${h.status === 'validated' ? 'bg-green-50' : h.status === 'refuted' ? 'bg-red-50' : 'bg-gray-50'}`}>
                                <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-1">Actual</p>
                                {h.actual_roas !== null && <p className="text-xs font-bold text-gray-800">ROAS: {h.actual_roas.toFixed(2)}x</p>}
                                {h.actual_ctr !== null && <p className="text-xs text-gray-600">CTR: {(h.actual_ctr * 100).toFixed(2)}%</p>}
                                {!hasResult && <p className="text-xs text-gray-400 italic">Waiting for data...</p>}
                              </div>
                            </div>
                          )}

                          {h.learning && (
                            <div className={`rounded-lg px-3 py-2 ${h.status === 'validated' ? 'bg-green-50' : 'bg-orange-50'}`}>
                              <p className={`text-[10px] font-semibold uppercase tracking-wider mb-0.5 ${h.status === 'validated' ? 'text-green-600' : 'text-orange-600'}`}>Learning</p>
                              <p className={`text-xs ${h.status === 'validated' ? 'text-green-800' : 'text-orange-800'}`}>{h.learning}</p>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )})}
                </div>
              </div>
            )
          })()}
        </>
      )}
    </div>
  )
}
