'use client'

import { useEffect, useState, useRef } from 'react'
import { Plus, X, ChevronDown, ChevronRight, Brain, Lightbulb, FlaskConical, BarChart3, HelpCircle } from 'lucide-react'
import { useAuth } from '@/components/AuthContext'

// ── Lightweight Tooltip ─────────────────────────────────────────────────────
function Tip({ text, wide }: { text: string; wide?: boolean }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  return (
    <div className="relative inline-flex items-center" ref={ref}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <HelpCircle className="w-3.5 h-3.5 text-gray-300 hover:text-gray-500 cursor-help shrink-0" />
      {open && (
        <div className={`absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 ${wide ? 'w-72' : 'w-56'}
          bg-gray-900 text-white text-xs rounded-lg px-3 py-2 shadow-xl leading-relaxed pointer-events-none`}>
          {text}
          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900" />
        </div>
      )}
    </div>
  )
}

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
  combo_id: string | null; ad_name: string | null
  combo_clicks: number | null; combo_conversions: number | null
  hypothesis_category: string | null; customer_insight: string | null
  human_desire: string | null; creative_angle: string | null
  target_audience: string | null; market: string | null
  hypothesis: string; variable_tested: string | null
  primary_kpi: string | null; secondary_kpi: string | null
  expected_outcome: string | null; status: string
  actual_ctr: number | null; actual_roas: number | null
  actual_spend: number | null
  learning: string | null; created_at: string
  brief_text: string | null; script_text: string | null
  evidence: string | null; creative_principle: string | null
  why_it_worked: string | null; human_moment: string | null
  approval_status: string | null
  confidence_score: number | null
  principle_id: string | null
  principle_title: string | null
  research_question_id: string | null
  knowledge_links: string[]
  parent_hypothesis_id: string | null
  // Layer A / B spec fields
  funnel_stage: string | null  // Stop|Hold|Click|Downstream
  format: string | null        // Image|Video
  primary_metric: string | null
  win_threshold: number | null
  min_sample: number
  layer_b_status: string | null  // pass|fail|insufficient
  layer_b_notes: string | null
}

interface Account { id: string; account_name: string; platform: string }

interface LearningDashboard {
  branch_name: string; total_experiments: number; total_running: number; total_validated: number; total_refuted: number; min_sample: number
  top_desires: { desire: string; win_rate: number; experiments: number; wins: number; sufficient: boolean }[]
  top_drivers: { category: string; raw: string; win_rate: number; experiments: number; sufficient: boolean }[]
  angle_win_rates: { angle: string; wins: number; total: number; win_rate: number; sufficient: boolean }[]
  funnel_failure_map: Record<string, { refutes: number; total: number; refute_rate: number }>
  recent_learnings: { hypothesis_id: string; learning: string; human_desire: string | null; funnel_stage: string | null; target_audience: string | null; market: string | null; validated_at: string | null }[]
}

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

const HYPOTHESIS_CATEGORIES: { value: string; label: string; desc: string; color: string }[] = [
  { value: 'identity', label: '🪞 Identity', desc: 'Who does the guest want to become?', color: 'bg-purple-50 text-purple-700 border-purple-200' },
  { value: 'decision_driver', label: '🎯 Decision Driver', desc: 'What makes them book NOW?', color: 'bg-orange-50 text-orange-700 border-orange-200' },
  { value: 'emotional_trigger', label: '❤️ Emotional Trigger', desc: 'Which emotion closes the booking?', color: 'bg-rose-50 text-rose-700 border-rose-200' },
  { value: 'travel_moment', label: '🗓️ Travel Moment', desc: 'Which stage of the journey?', color: 'bg-sky-50 text-sky-700 border-sky-200' },
  { value: 'social_proof', label: '👥 Social Proof', desc: 'Who do they trust?', color: 'bg-teal-50 text-teal-700 border-teal-200' },
  { value: 'experience', label: '✨ Experience', desc: 'What moment will they remember?', color: 'bg-amber-50 text-amber-700 border-amber-200' },
  { value: 'value_perception', label: '💰 Value Perception', desc: 'Is it worth the price?', color: 'bg-green-50 text-green-700 border-green-200' },
  { value: 'brand_territory', label: '🏔️ Brand Territory', desc: 'What only this hotel owns?', color: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
]
const CAT_COLOR: Record<string, string> = Object.fromEntries(HYPOTHESIS_CATEGORIES.map(c => [c.value, c.color]))

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

// Spec §3: funnel stage → primary metric mapping
const FUNNEL_METRICS: Record<string, Record<string, string>> = {
  Stop:       { Video: 'hook_rate',       Image: 'thumb_stop_rate' },
  Hold:       { Video: 'hold_rate',       Image: 'hold_rate' },
  Click:      { Video: 'CTR',             Image: 'CTR' },
  Downstream: { Video: 'booking_rate',    Image: 'booking_rate' },
}

type Tab = 'angles' | 'brand' | 'hypotheses' | 'dashboard'

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

  // Hypothesis filters (client-side)
  const [fHypoBranch, setFHypoBranch] = useState('')
  const [fHypoStatus, setFHypoStatus] = useState('')
  const [fHypoCategory, setFHypoCategory] = useState('')
  const [fHypoTA, setFHypoTA] = useState('')
  const [fHypoMarket, setFHypoMarket] = useState('')

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
    hypothesis_category: '', customer_insight: '',
    target_audience: '', market: '', hypothesis: '',
    variable_tested: '', primary_kpi: 'CTR', secondary_kpi: '',
    expected_outcome: '',
    funnel_stage: '', format: '', primary_metric: '',
    win_threshold: '', min_sample: '5',
  })

  // Learning dashboard state
  const [learningDashboard, setLearningDashboard] = useState<LearningDashboard | null>(null)
  const [ldBranch, setLdBranch] = useState('Meander Taipei')
  const [ldLoading, setLdLoading] = useState(false)

  // Analyze brief state
  const [analyzeTarget, setAnalyzeTarget] = useState<string | null>(null)
  const [analyzeMode, setAnalyzeMode] = useState<'brief' | 'vision'>('brief')
  const [analyzeForm, setAnalyzeForm] = useState({ brief_text: '', script_text: '' })
  const [visionUrls, setVisionUrls] = useState('')
  const [analyzeLoading, setAnalyzeLoading] = useState(false)

  const handleAnalyzeBrief = (hypId: string) => {
    setAnalyzeLoading(true)
    fetch(`${API_BASE}/api/hypotheses/${hypId}/analyze-brief`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(analyzeForm),
    }).then(r => r.json()).then(d => {
      if (d.success) { setAnalyzeTarget(null); setAnalyzeForm({ brief_text: '', script_text: '' }); fetchHypotheses() }
    }).catch(() => {}).finally(() => setAnalyzeLoading(false))
  }

  const handleAnalyzeVision = (hypId: string) => {
    setAnalyzeLoading(true)
    const urls = visionUrls.split('\n').map(u => u.trim()).filter(Boolean)
    fetch(`${API_BASE}/api/hypotheses/${hypId}/analyze-vision`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ image_urls: urls.length ? urls : null }),
    }).then(r => r.json()).then(d => {
      if (d.success) { setAnalyzeTarget(null); setVisionUrls(''); fetchHypotheses() }
    }).catch(() => {}).finally(() => setAnalyzeLoading(false))
  }

  // Auto-fetch benchmark win threshold
  const [benchmarkLoading, setBenchmarkLoading] = useState(false)
  const fetchBenchmark = (branch: string, metric: string) => {
    if (!branch || !metric) return
    setBenchmarkLoading(true)
    fetch(`${API_BASE}/api/hypotheses/benchmark/${encodeURIComponent(branch)}/${encodeURIComponent(metric)}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success && d.data.average !== null) {
          setHypoForm(p => ({ ...p, win_threshold: String(d.data.average) }))
        }
      })
      .catch(() => {})
      .finally(() => setBenchmarkLoading(false))
  }

  // AI suggestion state
  const [suggestions, setSuggestions] = useState<{hypothesis: string; variable_tested: string; expected_outcome: string; customer_insight?: string; rationale: string}[]>([])
  const [suggestLoading, setSuggestLoading] = useState(false)

  const handleSuggest = () => {
    if (!hypoForm.branch_name || !hypoForm.human_desire) return
    setSuggestLoading(true)
    setSuggestions([])
    fetch(`${API_BASE}/api/hypotheses/suggest`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        branch_name: hypoForm.branch_name,
        human_desire: hypoForm.human_desire,
        hypothesis_category: hypoForm.hypothesis_category || null,
        customer_insight: hypoForm.customer_insight || null,
        creative_angle: hypoForm.creative_angle || null,
        target_audience: hypoForm.target_audience || null,
        market: hypoForm.market || null,
        primary_kpi: hypoForm.primary_kpi,
        // Layer A binding constraints — AI writes to these, not primary_kpi
        funnel_stage: hypoForm.funnel_stage || null,
        format: hypoForm.format || null,
        primary_metric: hypoForm.primary_metric || null,
        win_threshold: hypoForm.win_threshold ? parseFloat(hypoForm.win_threshold) : null,
      }),
    }).then(r => r.json()).then(d => {
      if (d.success) setSuggestions(d.data.suggestions)
    }).catch(() => {}).finally(() => setSuggestLoading(false))
  }

  const applySuggestion = (s: typeof suggestions[0]) => {
    setHypoForm(p => ({
      ...p,
      hypothesis: s.hypothesis,
      variable_tested: s.variable_tested,
      expected_outcome: s.expected_outcome,
      customer_insight: s.customer_insight || p.customer_insight,
    }))
    setSuggestions([])
  }

  const selectedBrand = brandIdentities.find(b => b.branch_name === hypoForm.branch_name)
  const branchDesires = selectedBrand ? selectedBrand.human_desires : HUMAN_DESIRES

  const fetchLearningDashboard = (branch: string) => {
    setLdLoading(true)
    fetch(`${API_BASE}/api/hypotheses/learning-dashboard/${encodeURIComponent(branch)}`, { credentials: 'include' })
      .then(r => r.json()).then(d => { if (d.success) setLearningDashboard(d.data) }).catch(() => {}).finally(() => setLdLoading(false))
  }

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

  useEffect(() => { if (tab === 'dashboard') fetchLearningDashboard(ldBranch) }, [tab, ldBranch])
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
        setHypoForm({ branch_name: '', human_desire: '', creative_angle: '', hypothesis_category: '', customer_insight: '', target_audience: '', market: '', hypothesis: '', variable_tested: '', primary_kpi: 'CTR', secondary_kpi: '', expected_outcome: '', funnel_stage: '', format: '', primary_metric: '', win_threshold: '', min_sample: '5' })
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
      <div className="flex items-center justify-between mb-3">
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

      {/* System overview banner */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 mb-5 flex items-start gap-3">
        <HelpCircle className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
        <p className="text-xs text-blue-700 leading-relaxed">
          <strong>Cách dùng:</strong> Creative Angles → chọn góc tiếp cận.{' '}
          Hypotheses → đăng ký câu hỏi test <em>trước</em> khi chạy ad (Funnel Stage + Format → Primary Metric tự điền).{' '}
          Learning Dashboard → đọc win rate sau khi có đủ data.{' '}
          Layer A = creative verdict (hook/CTR), Layer B = downstream (ROAS/booking) — hai cái này độc lập với nhau.
          <span className="ml-1 text-blue-400">Hover vào icon <HelpCircle className="inline w-3 h-3" /> để xem giải thích chi tiết.</span>
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200 mb-6 overflow-x-auto">
        {([
          { key: 'angles', label: 'Creative Angles', icon: Lightbulb, tip: 'Danh sách các Creative Angle — góc tiếp cận sáng tạo. WIN = đang scale, TEST = đang chạy thử, LOSE = đã bỏ. Mỗi angle được nhóm theo Human Desire.' },
          { key: 'brand', label: 'Brand Intelligence', icon: Brain, tip: 'Bản đồ nhân cách thương hiệu từng branch — Desires, Emotional Themes, Always Say / Never Say. Dùng làm bộ lọc khi viết brief.' },
          { key: 'hypotheses', label: 'Hypotheses', icon: FlaskConical, tip: 'Mỗi ad idea phải có 1 hypothesis trước khi chạy. Hypothesis ghi lại câu hỏi, biến test, ngưỡng thắng — và kết luận sau khi có data.' },
          { key: 'dashboard', label: 'Learning Dashboard', icon: BarChart3, tip: 'Tổng hợp win rate theo Desire, Decision Driver, Angle và Funnel Stage. Đây là bộ não tích lũy — càng nhiều hypothesis concluded thì dashboard càng chính xác.' },
        ] as const).map(({ key, label, icon: Icon, tip }) => (
          <button key={key} onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap ${tab === key ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}>
            <Icon className="w-4 h-4" />{label}
            <span onClick={e => e.stopPropagation()}><Tip text={tip} wide /></span>
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
            <div className="flex items-center gap-1.5">
              <select value={fStatus} onChange={e => setFStatus(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
                <option value="">All Status</option>
                <option value="WIN">WIN</option><option value="TEST">TEST</option><option value="LOSE">LOSE</option>
              </select>
              <Tip text="WIN = angle đang work, đang scale budget. TEST = đang chạy thử, chưa kết luận. LOSE = đã test và không work, không chạy nữa." />
            </div>
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
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Branch *</label>
                    <select
                      value={hypoForm.branch_name}
                      onChange={e => setHypoForm(p => ({ ...p, branch_name: e.target.value, human_desire: '' }))}
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
                    >
                      <option value="">Select...</option>
                      {BRANCH_NAMES.map(b => <option key={b}>{b}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">
                      Human Desire
                      {selectedBrand && <span className="ml-1 text-purple-500">({branchDesires.length} for {hypoForm.branch_name.split(' ').pop()})</span>}
                    </label>
                    <select
                      value={hypoForm.human_desire}
                      onChange={e => setHypoForm(p => ({ ...p, human_desire: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
                      disabled={!hypoForm.branch_name}
                    >
                      <option value="">{hypoForm.branch_name ? 'Select...' : '← Pick branch first'}</option>
                      {branchDesires.map(d => <option key={d}>{d}</option>)}
                    </select>
                  </div>
                </div>

                <div>
                  <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">
                    Booking Decision Category
                    <Tip wide text="Khách sạn cần trả lời 8 câu hỏi trong đầu khách trước khi họ book. Chọn câu nào hypothesis này đang test. Dùng để group learnings và tìm ra loại message nào work nhất cho từng brand." />
                  </label>
                  <div className="grid grid-cols-4 gap-2">
                    {HYPOTHESIS_CATEGORIES.map(cat => (
                      <button
                        key={cat.value}
                        type="button"
                        onClick={() => setHypoForm(p => ({ ...p, hypothesis_category: p.hypothesis_category === cat.value ? '' : cat.value }))}
                        className={`text-left px-2.5 py-2 rounded-lg border text-xs transition-all ${
                          hypoForm.hypothesis_category === cat.value
                            ? cat.color + ' ring-1 ring-current'
                            : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'
                        }`}
                      >
                        <div className="font-medium leading-tight">{cat.label}</div>
                        <div className="text-[9px] opacity-70 mt-0.5 leading-tight">{cat.desc}</div>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <label className="block text-xs text-gray-500 mb-1">Customer Insight <span className="text-gray-300">(the belief underneath)</span></label>
                  <input
                    value={hypoForm.customer_insight}
                    onChange={e => setHypoForm(p => ({ ...p, customer_insight: e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
                    placeholder="e.g. Couples in their 30s don't want a 'luxurious' hotel — they want to feel like they made the right call."
                  />
                </div>
                <div className="grid grid-cols-4 gap-3">
                  <div><label className="block text-xs text-gray-500 mb-1">Creative Angle</label>
                    <select
                      value={hypoForm.creative_angle}
                      onChange={e => setHypoForm(p => ({ ...p, creative_angle: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
                    >
                      <option value="">— Any angle —</option>
                      {angles
                        .filter(a => !hypoForm.human_desire || a.human_desire === hypoForm.human_desire)
                        .filter(a => !a.applicable_to?.length || a.applicable_to.includes(hypoForm.branch_name))
                        .map(a => <option key={a.angle_id} value={a.angle_type}>{a.angle_type}</option>)
                      }
                    </select>
                  </div>
                  <div><label className="block text-xs text-gray-500 mb-1">Target Audience</label>
                    <select value={hypoForm.target_audience} onChange={e => setHypoForm(p => ({ ...p, target_audience: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                      <option value="">— All —</option>
                      {['Solo', 'Couple', 'Friend', 'Group', 'Business'].map(t => <option key={t}>{t}</option>)}
                    </select></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Market</label>
                    <select value={hypoForm.market} onChange={e => setHypoForm(p => ({ ...p, market: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                      <option value="">— All —</option>
                      {['VN', 'TW', 'JP', 'SG', 'HK', 'AU', 'US', 'GB', 'DE', 'FR', 'KR', 'TH', 'PH', 'MY', 'ID'].map(m => <option key={m}>{m}</option>)}
                    </select></div>
                  <div><label className="block text-xs text-gray-500 mb-1">Primary KPI (legacy)</label>
                    <select value={hypoForm.primary_kpi} onChange={e => setHypoForm(p => ({ ...p, primary_kpi: e.target.value }))} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                      {['CTR', 'CVR', 'ROAS', 'LPV', 'Hook Rate', 'Thruplay'].map(k => <option key={k}>{k}</option>)}
                    </select></div>
                </div>

                {/* Layer A verdict spec fields */}
                <div className="bg-blue-50 border border-blue-100 rounded-xl p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <p className="text-[10px] font-bold text-blue-600 uppercase tracking-wider">Layer A — Creative Verdict Gate</p>
                    <Tip wide text="Layer A đánh giá creative thuần túy — hook, hold, click. Không dùng ROAS hay booking. Verdict = primary metric có vượt ngưỡng sau đủ min_sample ads không? Layer B (downstream) là bước riêng, không bao giờ override Layer A." />
                  </div>
                  <div className="grid grid-cols-4 gap-3">
                    <div>
                      <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">Funnel Stage *<Tip text="Stop = giữ người không scroll qua (3s đầu). Hold = giữ người xem tiếp (thruplay). Click = thuyết phục click. Downstream = booking intent (Layer B)." wide /></label>
                      <select
                        value={hypoForm.funnel_stage}
                        onChange={e => {
                          const stage = e.target.value
                          const metric = FUNNEL_METRICS[stage]?.[hypoForm.format] || ''
                          setHypoForm(p => ({ ...p, funnel_stage: stage, primary_metric: metric, win_threshold: '' }))
                          if (hypoForm.branch_name && hypoForm.format && metric) fetchBenchmark(hypoForm.branch_name, metric)
                        }}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
                      >
                        <option value="">Select...</option>
                        {['Stop', 'Hold', 'Click', 'Downstream'].map(s => <option key={s}>{s}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">Format *<Tip text="Video hay Image. Kết hợp với Funnel Stage sẽ xác định Primary Metric tự động. Stop+Video → hook_rate, Stop+Image → thumb_stop_rate, Hold+Video → hold_rate, Click → CTR." wide /></label>
                      <select
                        value={hypoForm.format}
                        onChange={e => {
                          const fmt = e.target.value
                          const metric = FUNNEL_METRICS[hypoForm.funnel_stage]?.[fmt] || ''
                          setHypoForm(p => ({ ...p, format: fmt, primary_metric: metric, win_threshold: '' }))
                          if (hypoForm.branch_name && hypoForm.funnel_stage && metric) fetchBenchmark(hypoForm.branch_name, metric)
                        }}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
                      >
                        <option value="">Select...</option>
                        <option>Image</option>
                        <option>Video</option>
                      </select>
                    </div>
                    <div>
                      <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">Primary Metric<Tip text="Tự động điền từ Stage + Format. Đây là metric DUY NHẤT dùng để judge hypothesis này — AI suggestion cũng sẽ viết theo metric này, không phải CTR hay ROAS." wide /></label>
                      <input
                        value={hypoForm.primary_metric}
                        readOnly
                        className="w-full px-3 py-2 border border-gray-100 rounded-lg text-sm bg-blue-100 text-blue-800 font-medium"
                        placeholder="auto-set by stage + format"
                      />
                    </div>
                    <div>
                      <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">
                        Win Threshold
                        <Tip text="Ngưỡng để gọi là 'validated'. Tự động lấy từ average 60 ngày gần nhất của branch. Bạn có thể chỉnh lại nếu muốn set bar cao hơn hoặc thấp hơn." wide />
                        {benchmarkLoading && <span className="ml-1 text-blue-400 animate-pulse">fetching avg...</span>}
                        {!benchmarkLoading && hypoForm.win_threshold && <span className="ml-1 text-gray-300">(60d avg)</span>}
                      </label>
                      <input
                        type="number"
                        value={hypoForm.win_threshold}
                        onChange={e => setHypoForm(p => ({ ...p, win_threshold: e.target.value }))}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
                        placeholder={hypoForm.primary_metric ? `auto-fill on stage+format` : 'e.g. 3.5'}
                        step="0.01"
                      />
                    </div>
                  </div>
                  <div className="mt-2">
                    <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">Min Sample <Tip text="Số ads tối thiểu phải có verdict (validated hoặc refuted) trước khi hệ thống cho phép kết luận hypothesis. Mặc định 5. Dưới ngưỡng này → 'insufficient data', không kết luận." wide /></label>
                    <input
                      type="number"
                      value={hypoForm.min_sample}
                      onChange={e => setHypoForm(p => ({ ...p, min_sample: e.target.value }))}
                      className="w-32 px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
                      min="1"
                    />
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    onClick={handleSuggest}
                    disabled={!hypoForm.branch_name || !hypoForm.human_desire || !hypoForm.funnel_stage || !hypoForm.format || suggestLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-50 text-violet-700 border border-violet-200 rounded-lg text-xs font-medium hover:bg-violet-100 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {suggestLoading
                      ? <><span className="animate-spin inline-block w-3 h-3 border border-violet-400 border-t-transparent rounded-full" />Generating...</>
                      : <>✨ Suggest hypotheses with AI{hypoForm.primary_metric && <span className="ml-1 text-violet-400">→ {hypoForm.primary_metric}</span>}</>}
                  </button>
                  <Tip wide text="AI sẽ viết hypothesis, variable tested, và expected outcome theo đúng primary metric của Stage+Format bạn chọn. Ví dụ: Stop+Video → AI chỉ nói về hook_rate, không bao giờ dùng CTR hay ROAS." />
                  {(!hypoForm.funnel_stage || !hypoForm.format)
                    ? <span className="text-xs text-gray-400">Chọn Funnel Stage + Format trước — AI viết theo metric đó</span>
                    : !hypoForm.human_desire && <span className="text-xs text-gray-400">Chọn branch + desire trước</span>}
                </div>

                {suggestions.length > 0 && (
                  <div className="border border-violet-200 rounded-xl bg-violet-50 p-4 space-y-3">
                    <p className="text-xs font-semibold text-violet-700 uppercase tracking-wider">AI Suggestions — click to use</p>
                    {suggestions.map((s, i) => (
                      <button
                        key={i}
                        onClick={() => applySuggestion(s)}
                        className="w-full text-left bg-white rounded-lg border border-violet-100 p-3 hover:border-violet-400 hover:shadow-sm transition-all group"
                      >
                        <p className="text-sm text-gray-800 font-medium mb-1 group-hover:text-violet-800">{s.hypothesis}</p>
                        <div className="flex gap-4 text-xs text-gray-500 flex-wrap">
                          <span>Variable: <span className="text-gray-700">{s.variable_tested}</span></span>
                          <span>Expected: <span className="text-gray-700">{s.expected_outcome}</span></span>
                        </div>
                        <p className="text-[11px] text-violet-500 mt-1 italic">{s.rationale}</p>
                      </button>
                    ))}
                  </div>
                )}

                <div><label className="block text-xs text-gray-500 mb-1">Hypothesis *</label>
                  <textarea value={hypoForm.hypothesis} onChange={e => setHypoForm(p => ({ ...p, hypothesis: e.target.value }))} rows={2} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="We believe that showing guests recovering rather than arriving will resonate more with burnout-prone urban audiences." /></div>
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

          {/* Hypothesis filter bar */}
          <div className="flex flex-wrap gap-2 mb-4">
            <select value={fHypoBranch} onChange={e => setFHypoBranch(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All Branches</option>
              {BRANCH_NAMES.map(b => <option key={b}>{b}</option>)}
            </select>
            <select value={fHypoStatus} onChange={e => setFHypoStatus(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All Status</option>
              <option value="pending">Pending</option>
              <option value="running">Running</option>
              <option value="validated">Validated</option>
              <option value="refuted">Refuted</option>
              <option value="inconclusive">Inconclusive</option>
            </select>
            <select value={fHypoCategory} onChange={e => setFHypoCategory(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All Categories</option>
              {HYPOTHESIS_CATEGORIES.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
            <select value={fHypoTA} onChange={e => setFHypoTA(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All TA</option>
              {['Solo', 'Couple', 'Friend', 'Group', 'Business'].map(t => <option key={t}>{t}</option>)}
            </select>
            <select value={fHypoMarket} onChange={e => setFHypoMarket(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All Markets</option>
              {['VN', 'TW', 'JP', 'SG', 'HK', 'AU', 'US', 'GB', 'DE', 'FR', 'KR', 'TH'].map(m => <option key={m}>{m}</option>)}
            </select>
            {(fHypoBranch || fHypoStatus || fHypoCategory || fHypoTA || fHypoMarket) && (
              <button onClick={() => { setFHypoBranch(''); setFHypoStatus(''); setFHypoCategory(''); setFHypoTA(''); setFHypoMarket('') }}
                className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded-lg">
                Clear filters
              </button>
            )}
          </div>

          {hypotheses.length === 0 ? (
            <div className="bg-white rounded-xl border p-8 text-center text-gray-400">
              <FlaskConical className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p>No hypotheses yet.</p>
              <p className="text-xs mt-1">Each ad idea should have a hypothesis before it runs.</p>
            </div>
          ) : (() => {
            const filteredHypos = hypotheses
              .filter(h => !fHypoBranch || h.branch_name === fHypoBranch)
              .filter(h => !fHypoStatus || h.status === fHypoStatus)
              .filter(h => !fHypoCategory || h.hypothesis_category === fHypoCategory)
              .filter(h => !fHypoTA || h.target_audience === fHypoTA)
              .filter(h => !fHypoMarket || h.market === fHypoMarket)

            const concluded = filteredHypos.filter(h => ['validated','refuted'].includes(h.status))
            const running = filteredHypos.filter(h => h.status === 'running')
            const validated = filteredHypos.filter(h => h.status === 'validated')
            const learningsByDesire: Record<string, Hypothesis[]> = {}
            concluded.filter(h => h.learning).forEach(h => {
              const k = h.human_desire || 'General'
              ;(learningsByDesire[k] = learningsByDesire[k] || []).push(h)
            })
            return (
              <div className="space-y-6">
                <div className="grid grid-cols-4 gap-3">
                  {[
                    { label: 'Total', value: filteredHypos.length, cls: 'text-gray-800' },
                    { label: 'Running', value: running.length, cls: 'text-blue-700' },
                    { label: 'Validated', value: validated.length, cls: 'text-green-700' },
                    { label: 'Refuted', value: filteredHypos.filter(h=>h.status==='refuted').length, cls: 'text-red-600' },
                  ].map(s => (
                    <div key={s.label} className="bg-white rounded-xl border border-gray-200 p-4 text-center">
                      <p className={`text-2xl font-bold ${s.cls}`}>{s.value}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{s.label}</p>
                    </div>
                  ))}
                </div>

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

                <div className="space-y-3">
                  {filteredHypos.length === 0 && (fHypoBranch || fHypoStatus || fHypoCategory || fHypoTA || fHypoMarket) && (
                    <div className="text-center text-gray-400 py-8 text-sm">No hypotheses match the current filters.</div>
                  )}
                  {filteredHypos.map(h => {
                    const hasResult = h.actual_roas !== null || h.actual_ctr !== null
                    const clicks = h.combo_clicks ?? 0
                    const bookings = h.combo_conversions ?? 0
                    const clicksLeft = Math.max(0, 4500 - clicks)
                    const bookingsLeft = Math.max(0, 5 - bookings)

                    const metric = h.primary_metric || h.primary_kpi || 'primary metric'
                    const threshold = h.win_threshold ? ` (threshold: ${h.win_threshold})` : ''
                    const nextStep = (() => {
                      if (h.status === 'validated') return { color: 'bg-green-50 border-green-200 text-green-800', icon: '✅', text: `Layer A validated — ${metric} cleared${threshold}. Check Layer B for downstream impact.` }
                      if (h.status === 'refuted') return { color: 'bg-red-50 border-red-200 text-red-800', icon: '🔄', text: `Layer A refuted — ${metric} did not clear${threshold}. Pivot the creative variable.` }
                      if (h.status === 'inconclusive') return { color: 'bg-orange-50 border-orange-200 text-orange-800', icon: '⚠️', text: 'No spend detected on this combo. Check if the ad is active.' }
                      if (h.status === 'running') {
                        if (clicks === 0) return { color: 'bg-gray-50 border-gray-200 text-gray-600', icon: '⏳', text: 'No data yet — waiting for ad to run.' }
                        const minSample = h.min_sample || 5
                        return { color: 'bg-blue-50 border-blue-200 text-blue-700', icon: '📊', text: `Running — needs ${minSample} concluded ads to reach verdict gate. Tracking: ${metric}.` }
                      }
                      return null
                    })()

                    return (
                    <div key={h.id} className={`bg-white rounded-xl border p-5 ${h.status === 'validated' ? 'border-green-200' : h.status === 'refuted' ? 'border-red-200' : 'border-gray-200'}`}>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap mb-2">
                          <span className="font-mono text-xs text-gray-400">{h.hypothesis_id}</span>
                          <span className="text-xs text-gray-500">{h.branch_name}</span>
                          {h.hypothesis_category && (
                            <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${CAT_COLOR[h.hypothesis_category] || 'bg-gray-50 text-gray-600 border-gray-200'}`}>
                              {HYPOTHESIS_CATEGORIES.find(c => c.value === h.hypothesis_category)?.label || h.hypothesis_category}
                            </span>
                          )}
                          {h.human_desire && <span className="text-xs bg-purple-50 text-purple-700 px-2 py-0.5 rounded-full">{h.human_desire}</span>}
                          {h.creative_angle && <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">{h.creative_angle}</span>}
                          {h.funnel_stage && <span className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full font-medium">{h.funnel_stage}</span>}
                          {h.format && <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{h.format}</span>}
                          {h.target_audience && <span className="text-xs text-gray-400">{h.target_audience}</span>}
                          {h.market && <span className="text-xs text-gray-400">{h.market}</span>}
                          <span className="flex items-center gap-1">
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${HYPO_STATUS_BADGE[h.status] || 'bg-gray-100 text-gray-600'}`}>Layer A: {h.status}</span>
                            <Tip text={`Layer A = creative verdict. Đánh giá ${h.primary_metric || h.primary_kpi || 'primary metric'} có vượt ngưỡng (${h.win_threshold ?? '—'}) sau ${h.min_sample} ads không. Không liên quan ROAS hay booking.`} wide />
                          </span>
                          {h.layer_b_status && (
                            <span className="flex items-center gap-1">
                              <span className={`text-xs px-2 py-0.5 rounded-full font-medium border ${
                                h.layer_b_status === 'pass' ? 'bg-green-50 text-green-700 border-green-200' :
                                h.layer_b_status === 'fail' ? 'bg-red-50 text-red-600 border-red-200' :
                                'bg-gray-50 text-gray-500 border-gray-200'
                              }`}>Layer B: {h.layer_b_status}</span>
                              <Tip text="Layer B = downstream verdict (ROAS, booking rate). Độc lập với Layer A — một creative có thể Layer A pass (hook tốt) nhưng Layer B fail (offer/landing page kém)." wide />
                            </span>
                          )}
                          {h.approval_status && (
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium border ${
                              h.approval_status === 'APPROVED' ? 'bg-green-50 text-green-700 border-green-200' :
                              'bg-orange-50 text-orange-700 border-orange-200'
                            }`}>
                              {h.approval_status === 'APPROVED' ? '✓ Approved' : '⏳ In Review'}
                            </span>
                          )}
                        </div>

                        {h.combo_id && (
                          <a
                            href={`/creative?combo=${h.combo_id}`}
                            className="inline-flex items-center gap-1.5 mb-2 text-xs text-gray-500 hover:text-blue-600 bg-gray-50 hover:bg-blue-50 border border-gray-200 hover:border-blue-200 rounded-lg px-2.5 py-1 transition-colors"
                          >
                            <span className="font-mono text-gray-400">{h.combo_id}</span>
                            {h.ad_name && <span className="truncate max-w-[300px]">{h.ad_name}</span>}
                            <span className="text-gray-300">→ Creative Library</span>
                          </a>
                        )}

                        {h.customer_insight && (
                          <p className="text-[11px] text-gray-400 italic mb-1">"{h.customer_insight}"</p>
                        )}
                        <p className="text-sm font-medium text-gray-800 mb-3">{h.hypothesis}</p>

                        {(h.variable_tested || h.expected_outcome || hasResult) && (
                          <div className="grid grid-cols-2 gap-3 mb-3">
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
                              {h.actual_spend !== null && <p className="text-xs text-gray-400">Spend: ${h.actual_spend.toLocaleString()}</p>}
                              {clicks > 0 && <p className="text-xs text-gray-400">{clicks.toLocaleString()} clicks · {bookings} bookings</p>}
                              {!hasResult && <p className="text-xs text-gray-400 italic">Waiting for data...</p>}
                            </div>
                          </div>
                        )}

                        {h.learning && (
                          <div className={`rounded-lg px-3 py-2 mb-3 ${h.status === 'validated' ? 'bg-green-50' : 'bg-orange-50'}`}>
                            <p className={`text-[10px] font-semibold uppercase tracking-wider mb-0.5 ${h.status === 'validated' ? 'text-green-600' : 'text-orange-600'}`}>Learning</p>
                            <p className={`text-xs ${h.status === 'validated' ? 'text-green-800' : 'text-orange-800'}`}>{h.learning}</p>
                          </div>
                        )}

                        {(h.evidence || h.creative_principle) && (
                          <div className="border border-indigo-100 rounded-xl bg-indigo-50 p-4 mb-3 space-y-2">
                            {h.human_moment && (
                              <span className="inline-block text-[10px] font-bold uppercase tracking-widest text-indigo-500 bg-indigo-100 px-2 py-0.5 rounded-full">{h.human_moment}</span>
                            )}
                            {h.evidence && (
                              <div>
                                <p className="text-[10px] text-indigo-400 uppercase tracking-wider mb-0.5">Evidence</p>
                                <p className="text-xs text-indigo-900">{h.evidence}</p>
                              </div>
                            )}
                            {h.why_it_worked && (
                              <div>
                                <p className="text-[10px] text-indigo-400 uppercase tracking-wider mb-0.5">Why it worked</p>
                                <p className="text-xs text-indigo-800 italic">{h.why_it_worked}</p>
                              </div>
                            )}
                            {h.creative_principle && (
                              <div className="border-t border-indigo-200 pt-2">
                                <p className="text-[10px] text-indigo-400 uppercase tracking-wider mb-0.5">Creative Principle</p>
                                <p className="text-sm font-semibold text-indigo-900">"{h.creative_principle}"</p>
                              </div>
                            )}
                          </div>
                        )}

                        {analyzeTarget === h.hypothesis_id ? (
                          <div className="border border-indigo-200 rounded-xl bg-white p-4 mb-3">
                            <div className="flex justify-between items-center mb-3">
                              <div className="flex gap-1 bg-indigo-50 rounded-lg p-0.5">
                                <button
                                  onClick={() => setAnalyzeMode('brief')}
                                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${analyzeMode === 'brief' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
                                >
                                  🔬 Brief + Script
                                </button>
                                <button
                                  onClick={() => setAnalyzeMode('vision')}
                                  className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${analyzeMode === 'vision' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
                                >
                                  🖼️ Images
                                </button>
                              </div>
                              <button onClick={() => setAnalyzeTarget(null)} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
                            </div>

                            {analyzeMode === 'brief' ? (
                              <div className="space-y-2">
                                <div>
                                  <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Creative Brief</label>
                                  <textarea
                                    value={analyzeForm.brief_text}
                                    onChange={e => setAnalyzeForm(p => ({ ...p, brief_text: e.target.value }))}
                                    rows={3}
                                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm text-gray-800 placeholder-gray-400"
                                    placeholder="What is this ad trying to do? Who is it for? What feeling should the viewer have?"
                                  />
                                </div>
                                <div>
                                  <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Script / Scene Description / Dialogue</label>
                                  <textarea
                                    value={analyzeForm.script_text}
                                    onChange={e => setAnalyzeForm(p => ({ ...p, script_text: e.target.value }))}
                                    rows={4}
                                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm text-gray-800 placeholder-gray-400"
                                    placeholder="Paste the actual script, scene breakdown, or lời thoại here..."
                                  />
                                </div>
                                <button
                                  onClick={() => handleAnalyzeBrief(h.hypothesis_id)}
                                  disabled={!analyzeForm.brief_text || !analyzeForm.script_text || analyzeLoading}
                                  className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50"
                                >
                                  {analyzeLoading
                                    ? <><span className="animate-spin inline-block w-3 h-3 border border-white border-t-transparent rounded-full" />Analyzing...</>
                                    : <>🔬 Extract Evidence &amp; Principle</>}
                                </button>
                              </div>
                            ) : (
                              <div className="space-y-2">
                                <p className="text-[11px] text-gray-500">
                                  {h.combo_id
                                    ? `Linked to ${h.combo_id} — images will be pulled automatically. Or paste URLs below to override.`
                                    : 'Paste image URLs (one per line). Supports base64 data: URLs or https:// links. Multiple = carousel.'}
                                </p>
                                <div>
                                  <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Image URLs (optional override)</label>
                                  <textarea
                                    value={visionUrls}
                                    onChange={e => setVisionUrls(e.target.value)}
                                    rows={4}
                                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono text-gray-800 placeholder-gray-400"
                                    placeholder={"https://... or data:image/jpeg;base64,...\n(one URL per line for carousel)"}
                                  />
                                </div>
                                <button
                                  onClick={() => handleAnalyzeVision(h.hypothesis_id)}
                                  disabled={analyzeLoading || (!h.combo_id && !visionUrls.trim())}
                                  className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 text-white rounded-lg text-xs font-medium hover:bg-indigo-700 disabled:opacity-50"
                                >
                                  {analyzeLoading
                                    ? <><span className="animate-spin inline-block w-3 h-3 border border-white border-t-transparent rounded-full" />Analyzing...</>
                                    : <>🖼️ Analyze Visual Creative</>}
                                </button>
                              </div>
                            )}
                          </div>
                        ) : (
                          <div className="flex items-center gap-1.5 mb-3">
                            <button
                              onClick={() => { setAnalyzeTarget(h.hypothesis_id); setAnalyzeMode('brief'); setAnalyzeForm({ brief_text: h.brief_text || '', script_text: h.script_text || '' }) }}
                              className="text-xs text-indigo-500 hover:text-indigo-700 underline underline-offset-2"
                            >
                              {h.evidence ? '✏️ Re-analyze' : '🔬 Analyze creative'}
                            </button>
                            <Tip text="Paste brief + script hoặc image URL để AI trích xuất Evidence, Why It Worked, và Creative Principle — giúp biết tại sao ad work/không work ở mức tâm lý." wide />
                          </div>
                        )}

                        {nextStep && (
                          <div className={`rounded-lg px-3 py-2 border text-xs ${nextStep.color}`}>
                            <span className="mr-1">{nextStep.icon}</span>
                            <span className="font-semibold">Next: </span>{nextStep.text}
                          </div>
                        )}
                      </div>
                    </div>
                  )})}
                </div>
              </div>
            )
          })()}
        </>
      )}

      {/* ── TAB: LEARNING DASHBOARD ── */}
      {tab === 'dashboard' && (
        <>
          <div className="flex items-center gap-3 mb-6">
            <select value={ldBranch} onChange={e => setLdBranch(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm font-medium">
              {BRANCH_NAMES.map(b => <option key={b}>{b}</option>)}
            </select>
            {ldLoading && <span className="text-xs text-gray-400">Loading...</span>}
          </div>

          {!learningDashboard || ldLoading ? (
            <div className="text-center text-gray-400 py-12">
              {ldLoading ? 'Loading knowledge base...' : 'Select a branch to see the learning dashboard.'}
            </div>
          ) : (
            <div className="space-y-6">
              <div className="grid grid-cols-4 gap-4">
                {[
                  { label: 'Concluded', value: learningDashboard.total_experiments, color: 'text-gray-800' },
                  { label: 'Running', value: learningDashboard.total_running, color: 'text-blue-600' },
                  { label: 'Validated', value: learningDashboard.total_validated, color: 'text-green-700' },
                  { label: 'Refuted', value: learningDashboard.total_refuted, color: 'text-red-600' },
                ].map(s => (
                  <div key={s.label} className="bg-white rounded-xl border border-gray-200 p-5 text-center">
                    <p className={`text-3xl font-bold ${s.color}`}>{s.value}</p>
                    <p className="text-xs text-gray-400 mt-1">{s.label}</p>
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Desire Win Rate */}
                <div className="bg-white rounded-xl border border-gray-200 p-5">
                  <div className="flex items-center gap-2 mb-4">
                    <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">Desire Win Rate</h3>
                    <Tip text="Win rate = validated ÷ (validated + refuted). Chỉ tính concluded ads, không tính pending/running. Greyed = chưa đủ min_sample — chưa thể kết luận." wide />
                  </div>
                  {learningDashboard.top_desires.length === 0 ? <p className="text-xs text-gray-400">No data yet.</p> : (
                    <div className="space-y-3">
                      {learningDashboard.top_desires.map(d => (
                        <div key={d.desire} className={d.sufficient ? '' : 'opacity-50'}>
                          <div className="flex items-center justify-between mb-1">
                            <span className={`text-sm font-medium ${d.sufficient ? 'text-gray-800' : 'text-gray-400'}`}>{d.desire}</span>
                            <span className={`text-sm font-bold ${!d.sufficient ? 'text-gray-400' : d.win_rate >= 60 ? 'text-green-600' : d.win_rate >= 40 ? 'text-amber-600' : 'text-red-500'}`}>
                              {d.sufficient ? `${d.win_rate}%` : '—'}
                            </span>
                          </div>
                          {d.sufficient && (
                            <div className="h-1.5 bg-gray-100 rounded-full">
                              <div className={`h-full rounded-full ${d.win_rate >= 60 ? 'bg-green-500' : d.win_rate >= 40 ? 'bg-amber-500' : 'bg-red-400'}`}
                                style={{ width: `${d.win_rate}%` }} />
                            </div>
                          )}
                          <p className="text-[10px] text-gray-400 mt-0.5">
                            {d.wins}/{d.experiments} concluded
                            {!d.sufficient && ` · needs ${learningDashboard.min_sample} min`}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Decision Driver Win Rate */}
                <div className="bg-white rounded-xl border border-gray-200 p-5">
                  <div className="flex items-center gap-2 mb-4">
                    <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">Decision Driver Win Rate</h3>
                    <Tip text="Hypothesis Category (Identity, Emotional Trigger, Social Proof...) nào đang work nhất cho branch này. Dùng để ưu tiên loại test tiếp theo." wide />
                  </div>
                  {learningDashboard.top_drivers.length === 0 ? <p className="text-xs text-gray-400">No data yet.</p> : (
                    <div className="space-y-3">
                      {learningDashboard.top_drivers.map(d => (
                        <div key={d.raw} className={d.sufficient ? '' : 'opacity-50'}>
                          <div className="flex items-center justify-between mb-1">
                            <span className={`text-sm font-medium ${d.sufficient ? 'text-gray-800' : 'text-gray-400'}`}>{d.category}</span>
                            <span className={`text-sm font-bold ${!d.sufficient ? 'text-gray-400' : d.win_rate >= 60 ? 'text-green-600' : d.win_rate >= 40 ? 'text-amber-600' : 'text-red-500'}`}>
                              {d.sufficient ? `${d.win_rate}%` : '—'}
                            </span>
                          </div>
                          {d.sufficient && (
                            <div className="h-1.5 bg-gray-100 rounded-full">
                              <div className={`h-full rounded-full ${d.win_rate >= 60 ? 'bg-indigo-500' : d.win_rate >= 40 ? 'bg-amber-500' : 'bg-red-400'}`}
                                style={{ width: `${d.win_rate}%` }} />
                            </div>
                          )}
                          <p className="text-[10px] text-gray-400 mt-0.5">
                            {d.experiments} concluded{!d.sufficient && ` · needs ${learningDashboard.min_sample} min`}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Angle Win Rate — ONE table */}
                <div className="bg-white rounded-xl border border-gray-200 p-5 lg:col-span-2">
                  <div className="flex items-center gap-2 mb-4">
                    <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">Angle Win Rate</h3>
                    <Tip wide text="Mỗi creative angle xuất hiện đúng 1 lần. Win rate = validated ÷ (validated + refuted). Dòng mờ = chưa đủ min_sample ads, chưa thể kết luận. Sort: đủ sample trước, sau đó theo win rate cao nhất." />
                  </div>
                  {learningDashboard.angle_win_rates.length === 0 ? <p className="text-xs text-gray-400">No concluded angles yet.</p> : (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-[10px] text-gray-400 uppercase tracking-wider border-b border-gray-100">
                            <th className="text-left pb-2 font-medium">Angle</th>
                            <th className="text-right pb-2 font-medium w-20">Wins</th>
                            <th className="text-right pb-2 font-medium w-20">Total</th>
                            <th className="text-right pb-2 font-medium w-24">Win Rate</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-50">
                          {learningDashboard.angle_win_rates.map(a => (
                            <tr key={a.angle} className={a.sufficient ? '' : 'opacity-45'}>
                              <td className={`py-2 pr-4 font-medium ${a.sufficient ? 'text-gray-800' : 'text-gray-400'}`}>{a.angle}</td>
                              <td className="py-2 text-right text-green-700 font-medium">{a.wins}</td>
                              <td className="py-2 text-right text-gray-500">{a.total}</td>
                              <td className="py-2 text-right">
                                {a.sufficient ? (
                                  <span className={`font-bold ${a.win_rate >= 60 ? 'text-green-600' : a.win_rate >= 40 ? 'text-amber-600' : 'text-red-500'}`}>{a.win_rate}%</span>
                                ) : (
                                  <span className="text-gray-300 text-xs">insufficient</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                {/* Funnel-Stage Failure Map */}
                <div className="bg-white rounded-xl border border-gray-200 p-5">
                  <div className="flex items-center gap-2 mb-1">
                    <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">Funnel-Stage Failure Map</h3>
                    <Tip wide text="% hypothesis bị refuted tại mỗi stage. Nếu Stop có fail rate cao → creative không đủ mạnh để giữ người. Nếu Click cao → hook tốt nhưng offer không thuyết phục. Dùng để biết team nên fix cái gì trước." />
                  </div>
                  <p className="text-[10px] text-gray-400 mb-4">Where do most hypotheses get refuted?</p>
                  {Object.keys(learningDashboard.funnel_failure_map).length === 0 ? <p className="text-xs text-gray-400">No data yet — add funnel_stage to hypotheses first.</p> : (
                    <div className="space-y-3">
                      {(['Stop', 'Hold', 'Click', 'Downstream'] as const).map(stage => {
                        const d = learningDashboard.funnel_failure_map[stage]
                        if (!d) return null
                        return (
                          <div key={stage}>
                            <div className="flex items-center justify-between mb-1">
                              <span className="text-sm font-medium text-gray-700">{stage}</span>
                              <span className={`text-sm font-bold ${d.refute_rate >= 60 ? 'text-red-600' : d.refute_rate >= 40 ? 'text-amber-600' : 'text-green-600'}`}>{d.refute_rate}% fail</span>
                            </div>
                            <div className="h-2 bg-gray-100 rounded-full">
                              <div className={`h-full rounded-full ${d.refute_rate >= 60 ? 'bg-red-400' : d.refute_rate >= 40 ? 'bg-amber-400' : 'bg-green-400'}`}
                                style={{ width: `${d.refute_rate}%` }} />
                            </div>
                            <p className="text-[10px] text-gray-400 mt-0.5">{d.refutes}/{d.total} refuted</p>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>

                {/* Recent Learnings */}
                {learningDashboard.recent_learnings.length > 0 && (
                  <div className="bg-violet-50 rounded-xl border border-violet-100 p-5">
                    <h3 className="text-sm font-bold text-violet-700 uppercase tracking-wider mb-4">Recent Learnings</h3>
                    <div className="space-y-2">
                      {learningDashboard.recent_learnings.map(l => (
                        <div key={l.hypothesis_id} className="flex items-start gap-3">
                          <span className="w-1.5 h-1.5 rounded-full bg-violet-400 shrink-0 mt-1.5" />
                          <div className="flex-1 min-w-0">
                            <p className="text-sm text-violet-900">{l.learning}</p>
                            <p className="text-[10px] text-violet-400 mt-0.5">
                              {[l.funnel_stage, l.human_desire, l.target_audience, l.market].filter(Boolean).join(' · ')}
                              {l.validated_at && ` · ${new Date(l.validated_at).toLocaleDateString()}`}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
