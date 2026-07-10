'use client'

import { useEffect, useState, useRef, Suspense, useMemo } from 'react'
import { useSearchParams } from 'next/navigation'
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

interface LinkedCombo { combo_id: string; ad_name: string | null; verdict: string | null; roas: number | null }

interface Hypothesis {
  id: string; hypothesis_id: string; branch_name: string
  combo_id: string | null; ad_name: string | null
  combo_clicks: number | null; combo_conversions: number | null
  linked_combos?: LinkedCombo[]
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
  branch_name: string; total_hypotheses: number; total_pending: number; total_experiments: number; total_running: number; total_validated: number; total_refuted: number; min_sample: number
  pending_hypotheses: { hypothesis_id: string; hypothesis: string; hypothesis_category: string | null; human_desire: string | null; funnel_stage: string | null; format: string | null; target_audience: string | null }[]
  category_counts: Record<string, number>
  tested_desires: string[]
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
  { value: 'identity', label: '🪞 Self-Image', desc: 'Testing which identity the guest sees themselves as — the type of person who stays here (cultured traveler, intentional romantic, etc.)', color: 'bg-purple-50 text-purple-700 border-purple-200' },
  { value: 'decision_driver', label: '⚡ Reason to Book Now', desc: 'Testing what pushes them from "want to go" to "book" — price framing, urgency, exclusive access, limited availability', color: 'bg-orange-50 text-orange-700 border-orange-200' },
  { value: 'emotional_trigger', label: '😮 Closing Emotion', desc: 'Testing which emotion seals the booking — FOMO, nostalgia, feeling cared for, self-reward, belonging', color: 'bg-rose-50 text-rose-700 border-rose-200' },
  { value: 'travel_moment', label: '📍 Journey Stage', desc: 'Testing which stage of the decision journey this ad hits — dreaming, planning, or ready to book', color: 'bg-sky-50 text-sky-700 border-sky-200' },
  { value: 'social_proof', label: '👥 Social Proof', desc: 'Testing which proof type convinces — reviews, UGC, guest count, press mentions, familiar faces', color: 'bg-teal-50 text-teal-700 border-teal-200' },
  { value: 'experience', label: '🎬 Memorable Moment', desc: 'Testing which experience highlight drives the click — breakfast, room view, spa, common space, a specific activity', color: 'bg-amber-50 text-amber-700 border-amber-200' },
  { value: 'value_perception', label: '💰 Worth the Price', desc: 'Testing which value framing reduces friction — comparison to alternatives, bundle inclusions, "treat yourself" positioning', color: 'bg-green-50 text-green-700 border-green-200' },
  { value: 'brand_territory', label: '🏔️ Only We Have This', desc: 'Testing the one differentiator no competitor can claim for this specific branch — a space, a feeling, a ritual', color: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
]
const CAT_COLOR: Record<string, string> = Object.fromEntries(HYPOTHESIS_CATEGORIES.map(c => [c.value, c.color]))


// Spec §3: funnel stage → primary metric mapping
const FUNNEL_METRICS: Record<string, Record<string, string>> = {
  Stop:       { Video: 'hook_rate',       Image: 'thumb_stop_rate' },
  Hold:       { Video: 'hold_rate',       Image: 'hold_rate' },
  Click:      { Video: 'CTR',             Image: 'CTR' },
  Downstream: { Video: 'roas',            Image: 'roas' },
}

type Tab = 'angles' | 'brand' | 'hypotheses' | 'dashboard'

function AnglesPageInner() {
  const { canEditSection } = useAuth()
  const canEdit = canEditSection('meta_ads')
  const searchParams = useSearchParams()

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
    branch_name: '', creative_angle: '',
    hypothesis_category: '', customer_insight: '',
    target_audience: '', market: '', hypothesis: '',
    variable_tested: '', primary_kpi: 'CTR', secondary_kpi: '',
    expected_outcome: '',
    funnel_stage: '', format: '', primary_metric: '',
    win_threshold: '', min_sample: '5',
    combo_id: '', baseline: '',
  })
  const [selectedComboIds, setSelectedComboIds] = useState<string[]>([])

  // Bulk generate modal
  interface BulkProposal {
    hypothesis: string; hypothesis_category: string; customer_insight: string
    expected_outcome: string; rationale: string; branch_name: string
    target_audience: string | null; market: string | null; primary_metric: string
    combo_ids: string[]; cohort_label: string; cohort_size: number; top_combo: string | null
  }
  const [showBulkGen, setShowBulkGen] = useState(false)
  const [bulkBranch, setBulkBranch] = useState('')
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkProposals, setBulkProposals] = useState<BulkProposal[]>([])
  const [bulkSelected, setBulkSelected] = useState<Set<number>>(new Set())
  const [bulkSaving, setBulkSaving] = useState(false)
  const [bulkDone, setBulkDone] = useState(0)
  const [bulkSkipped, setBulkSkipped] = useState<number | null>(null)

  const handleBulkGenerate = () => {
    if (!bulkBranch) return
    setBulkLoading(true); setBulkProposals([]); setBulkSelected(new Set()); setBulkDone(0)
    fetch(`${API_BASE}/api/hypotheses/bulk-generate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ branch_name: bulkBranch }),
    }).then(r => r.json()).then(d => {
      if (d.success) {
        setBulkProposals(d.data.proposals)
        setBulkSkipped(d.data.skipped ?? null)
        setBulkSelected(new Set(d.data.proposals.map((_: BulkProposal, i: number) => i)))
      }
    }).catch(() => {}).finally(() => setBulkLoading(false))
  }

  const handleBulkSave = async () => {
    setBulkSaving(true)
    const toCreate = bulkProposals.filter((_, i) => bulkSelected.has(i))
    let done = 0
    for (const p of toCreate) {
      await fetch(`${API_BASE}/api/hypotheses`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          branch_name: p.branch_name,
          hypothesis: p.hypothesis,
          hypothesis_category: p.hypothesis_category,
          customer_insight: p.customer_insight,
          expected_outcome: p.expected_outcome,
          target_audience: p.target_audience,
          market: p.market,
          primary_metric: p.primary_metric,
          primary_kpi: p.primary_metric,
          combo_ids: p.combo_ids,
          status: 'pending',
        }),
      })
      done++
      setBulkDone(done)
    }
    setBulkSaving(false)
    setShowBulkGen(false)
    setBulkProposals([])
    fetchHypotheses()
  }

  // Learning dashboard state
  const [learningDashboard, setLearningDashboard] = useState<LearningDashboard | null>(null)
  const [ldBranch, setLdBranch] = useState('Meander Taipei')
  const [ldMarket, setLdMarket] = useState('')
  const [ldTA, setLdTA] = useState('')
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

  // Combo search for hypothesis linking
  const [comboSearch, setComboSearch] = useState('')
  const [comboResults, setComboResults] = useState<{combo_id: string; ad_name: string | null; verdict: string; roas: number | null; branch_id: string}[]>([])
  const [comboSearchLoading, setComboSearchLoading] = useState(false)
  const searchCombos = (q: string, branchId?: string) => {
    if (!q && !branchId) { setComboResults([]); return }
    setComboSearchLoading(true)
    const p = new URLSearchParams({ limit: '20' })
    if (branchId) p.set('branch_id', branchId)
    fetch(`${API_BASE}/api/combos?${p}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          const items = d.data.items as {combo_id: string; ad_name: string | null; verdict: string; roas: number | null; branch_id: string}[]
          setComboResults(q ? items.filter(i => (i.ad_name || '').toLowerCase().includes(q.toLowerCase()) || i.combo_id.toLowerCase().includes(q.toLowerCase())) : items)
        }
      })
      .catch(() => {})
      .finally(() => setComboSearchLoading(false))
  }

  // Auto-fetch benchmark win threshold
  const [benchmarkLoading, setBenchmarkLoading] = useState(false)
  const fetchBenchmark = (branch: string, metric: string, ta?: string, country?: string) => {
    if (!branch || !metric) return
    setBenchmarkLoading(true)
    const p = new URLSearchParams()
    if (ta) p.set('ta', ta)
    if (country) p.set('country', country)
    const qs = p.toString() ? `?${p}` : ''
    fetch(`${API_BASE}/api/hypotheses/benchmark/${encodeURIComponent(branch)}/${encodeURIComponent(metric)}${qs}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success && d.data.average !== null) {
          setHypoForm(prev => ({
            ...prev,
            win_threshold: String(d.data.average),
            baseline: `60-day avg ${metric}${ta ? ` · ${ta}` : ''}${country ? ` · ${country}` : ''} = ${d.data.average}% (n=${d.data.sample_size})`,
          }))
        }
      })
      .catch(() => {})
      .finally(() => setBenchmarkLoading(false))
  }

  // Edit hypothesis state
  const [editingHypoId, setEditingHypoId] = useState<string | null>(null)
  const [editHypoForm, setEditHypoForm] = useState<Partial<Hypothesis>>({})
  const [editSaving, setEditSaving] = useState(false)

  const openEditHypo = (h: Hypothesis) => {
    setEditingHypoId(h.hypothesis_id)
    setEditHypoForm({
      hypothesis: h.hypothesis,
      hypothesis_category: h.hypothesis_category || '',
      customer_insight: h.customer_insight || '',
      human_desire: h.human_desire || '',
      creative_angle: h.creative_angle || '',
      target_audience: h.target_audience || '',
      market: h.market || '',
      variable_tested: h.variable_tested || '',
      expected_outcome: h.expected_outcome || '',
      funnel_stage: h.funnel_stage || '',
      format: h.format || '',
      primary_kpi: h.primary_kpi || '',
      secondary_kpi: h.secondary_kpi || '',
    })
  }

  const saveEditHypo = (hypothesisId: string) => {
    setEditSaving(true)
    const body: Record<string, string | null> = {}
    for (const [k, v] of Object.entries(editHypoForm)) {
      body[k] = (v as string) || null
    }
    fetch(`${API_BASE}/api/hypotheses/${hypothesisId}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      credentials: 'include', body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          setHypotheses(prev => prev.map(h => h.hypothesis_id === hypothesisId ? { ...h, ...d.data } : h))
          setEditingHypoId(null)
        }
      })
      .catch(() => {})
      .finally(() => setEditSaving(false))
  }

  // AI suggestion state
  const [suggestions, setSuggestions] = useState<{hypothesis: string; variable_tested: string; expected_outcome: string; customer_insight?: string; rationale: string}[]>([])
  const [suggestLoading, setSuggestLoading] = useState(false)

  const handleSuggest = () => {
    if (!hypoForm.branch_name) return
    setSuggestLoading(true)
    setSuggestions([])
    fetch(`${API_BASE}/api/hypotheses/suggest`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        branch_name: hypoForm.branch_name,
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
  const branchDesires = selectedBrand?.human_desires ?? []

  // Cohort rankings: group by (branch + TA + market + primary_metric), rank by actual metric desc
  const cohortRankMap = useMemo(() => {
    const metricVal = (h: Hypothesis): number | null => {
      const m = h.primary_metric || h.primary_kpi || ''
      if (m === 'roas' || m === 'ROAS') return h.actual_roas ?? null
      if (m === 'CTR' || m === 'ctr') return h.actual_ctr ?? null
      if (m === 'hook_rate') return h.actual_ctr ?? null  // best proxy available
      return h.actual_roas ?? h.actual_ctr ?? null
    }
    const groups: Record<string, Hypothesis[]> = {}
    hypotheses.forEach(h => {
      if (metricVal(h) === null) return
      const key = [h.branch_name, h.target_audience || '', h.market || '', h.primary_metric || h.primary_kpi || ''].join('|')
      ;(groups[key] = groups[key] || []).push(h)
    })
    const map: Record<string, { rank: number; total: number; label: string; value: number; metric: string }> = {}
    Object.entries(groups).forEach(([, members]) => {
      const sorted = [...members].sort((a, b) => (metricVal(b) ?? 0) - (metricVal(a) ?? 0))
      sorted.forEach((h, i) => {
        const m = h.primary_metric || h.primary_kpi || ''
        const parts = [h.market || h.target_audience ? `${h.market}` : '', h.target_audience || ''].filter(Boolean)
        map[h.hypothesis_id] = {
          rank: i + 1,
          total: sorted.length,
          label: parts.join(' · '),
          value: metricVal(h) ?? 0,
          metric: m,
        }
      })
    })
    return map
  }, [hypotheses])

  const fetchLearningDashboard = (branch: string, market?: string, ta?: string) => {
    setLdLoading(true)
    const p = new URLSearchParams()
    if (market) p.set('market', market)
    if (ta) p.set('target_audience', ta)
    const qs = p.toString() ? `?${p}` : ''
    fetch(`${API_BASE}/api/hypotheses/learning-dashboard/${encodeURIComponent(branch)}${qs}`, { credentials: 'include' })
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

  useEffect(() => { if (tab === 'dashboard') fetchLearningDashboard(ldBranch, ldMarket, ldTA) }, [tab, ldBranch, ldMarket, ldTA])

  // Pre-fill from URL params: /angles?tab=hypotheses&combo_id=CMB-XXX
  useEffect(() => {
    const paramTab = searchParams.get('tab')
    const paramCombo = searchParams.get('combo_id')
    if (paramTab === 'hypotheses') {
      setTab('hypotheses')
      setShowCreateHypo(true)
      if (paramCombo) setSelectedComboIds([paramCombo])
    }
  }, [searchParams])
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
    const { combo_id: _ignored, ...rest } = hypoForm
    fetch(`${API_BASE}/api/hypotheses`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ ...rest, combo_ids: selectedComboIds.length ? selectedComboIds : null }),
    }).then(r => r.json()).then(d => {
      if (d.success) {
        setShowCreateHypo(false)
        setHypoForm({ branch_name: '', creative_angle: '', hypothesis_category: '', customer_insight: '', target_audience: '', market: '', hypothesis: '', variable_tested: '', primary_kpi: 'CTR', secondary_kpi: '', expected_outcome: '', funnel_stage: '', format: '', primary_metric: '', win_threshold: '', min_sample: '5', combo_id: '', baseline: '' })
        setSelectedComboIds([])
        setComboSearch(''); setComboResults([])
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
  const desireOrder = [...(branchDesires ?? []), 'Uncategorized']
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
            <>
              <button onClick={() => setShowBulkGen(true)} className="inline-flex items-center gap-2 px-4 py-2 bg-violet-50 text-violet-700 border border-violet-200 rounded-lg text-sm font-medium hover:bg-violet-100">
                ✨ Generate
              </button>
              <button onClick={() => setShowCreateHypo(true)} className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 text-white rounded-lg text-sm font-medium hover:bg-violet-700">
                <Plus className="w-4 h-4" /> New Hypothesis
              </button>
            </>
          )}
        </div>
      </div>

      {/* System overview banner */}
      <div className="bg-blue-50 border border-blue-100 rounded-xl px-4 py-3 mb-5 flex items-start gap-3">
        <HelpCircle className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
        <p className="text-xs text-blue-700 leading-relaxed">
          <strong>How to use:</strong> Creative Angles → pick your angle strategy.{' '}
          Hypotheses → register a test question <em>before</em> running an ad (Funnel Stage + Format auto-fills the Primary Metric).{' '}
          Learning Dashboard → read win rates once you have enough concluded data.{' '}
          Layer A = creative verdict (hook/CTR only), Layer B = downstream (ROAS/booking) — these are independent.
          <span className="ml-1 text-blue-400">Hover <HelpCircle className="inline w-3 h-3" /> icons for details.</span>
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200 mb-6 overflow-x-auto">
        {([
          { key: 'angles', label: 'Creative Angles', icon: Lightbulb, tip: 'Library of creative angles. WIN = scaling, TEST = in trial, LOSE = retired. Angles are grouped by Human Desire.' },
          { key: 'brand', label: 'Brand Intelligence', icon: Brain, tip: 'Brand personality map per branch — Desires, Emotional Themes, Always Say / Never Say. Use as a filter when writing briefs.' },
          { key: 'hypotheses', label: 'Hypotheses', icon: FlaskConical, tip: 'Every ad idea should have a hypothesis before it runs. A hypothesis records the question, variable tested, win threshold — and the verdict once data comes in.' },
          { key: 'dashboard', label: 'Learning Dashboard', icon: BarChart3, tip: 'Aggregated win rates by Desire, Decision Driver, Angle, and Funnel Stage. The more concluded hypotheses, the more reliable the dashboard.' },
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
              {(branchDesires ?? []).map((d: string) => <option key={d}>{d}</option>)}
            </select>
            <div className="flex items-center gap-1.5">
              <select value={fStatus} onChange={e => setFStatus(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
                <option value="">All Status</option>
                <option value="WIN">WIN</option><option value="TEST">TEST</option><option value="LOSE">LOSE</option>
              </select>
              <Tip text="WIN = angle is working, scaling budget. TEST = in trial, no verdict yet. LOSE = tested and did not work, retired." />
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
                      <option value="">Select...</option>{(branchDesires ?? []).map((d: string) => <option key={d}>{d}</option>)}
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
                const colorCls = 'bg-gray-50 border-gray-200 text-gray-700'
                const dotCls = 'bg-gray-400'
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
                      onChange={e => setHypoForm(p => ({ ...p, branch_name: e.target.value }))}
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
                    >
                      <option value="">Select...</option>
                      {BRANCH_NAMES.map(b => <option key={b}>{b}</option>)}
                    </select>
                  </div>
                </div>

                <div>
                  <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">
                    Booking Decision Category
                    <Tip wide text="Hotels must answer 8 mental questions guests ask before booking. Pick which question this hypothesis is testing. Used to group learnings and identify which message type works best per brand." />
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
                <div className="grid grid-cols-3 gap-3">
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
                    <Tip wide text="Layer A judges the creative only — hook, hold, click. Never uses ROAS or booking. Verdict = did the primary metric exceed the threshold after min_sample concluded ads? Layer B (downstream) is a separate step and never overrides Layer A." />
                  </div>
                  <div className="grid grid-cols-4 gap-3">
                    <div>
                      <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">Funnel Stage *<Tip text="Stop = prevent scroll-past (first 3 seconds). Hold = keep watching (thruplay). Click = persuade the click (CTA/offer). Downstream = booking intent (Layer B)." wide /></label>
                      <select
                        value={hypoForm.funnel_stage}
                        onChange={e => {
                          const stage = e.target.value
                          const metric = FUNNEL_METRICS[stage]?.[hypoForm.format] || ''
                          setHypoForm(p => ({ ...p, funnel_stage: stage, primary_metric: metric, win_threshold: '' }))
                          if (hypoForm.branch_name && hypoForm.format && metric) fetchBenchmark(hypoForm.branch_name, metric, hypoForm.target_audience || undefined, hypoForm.market || undefined)
                        }}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
                      >
                        <option value="">Select...</option>
                        {['Stop', 'Hold', 'Click', 'Downstream'].map(s => <option key={s}>{s}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">Format *<Tip text="Video or Image. Combined with Funnel Stage, this auto-determines the Primary Metric. Stop+Video → hook_rate, Stop+Image → thumb_stop_rate, Hold+Video → hold_rate, Click → CTR." wide /></label>
                      <select
                        value={hypoForm.format}
                        onChange={e => {
                          const fmt = e.target.value
                          const metric = FUNNEL_METRICS[hypoForm.funnel_stage]?.[fmt] || ''
                          setHypoForm(p => ({ ...p, format: fmt, primary_metric: metric, win_threshold: '' }))
                          if (hypoForm.branch_name && hypoForm.funnel_stage && metric) fetchBenchmark(hypoForm.branch_name, metric, hypoForm.target_audience || undefined, hypoForm.market || undefined)
                        }}
                        className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm bg-white"
                      >
                        <option value="">Select...</option>
                        <option>Image</option>
                        <option>Video</option>
                      </select>
                    </div>
                    <div>
                      <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">Primary Metric<Tip text="Auto-filled from Stage + Format. This is the ONLY metric used to judge this hypothesis — AI suggestions also write to this metric, never CTR or ROAS." wide /></label>
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
                        <Tip text="The threshold to call a hypothesis 'validated'. Auto-filled from the branch's 60-day average for this metric. You can edit it to set the bar higher or lower." wide />
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
                    <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">Min Sample <Tip text="Minimum number of ads that must have a verdict (validated or refuted) before the system allows a hypothesis conclusion. Default 5. Below this → 'insufficient data', no verdict." wide /></label>
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
                    disabled={!hypoForm.branch_name || !hypoForm.funnel_stage || !hypoForm.format || suggestLoading}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-50 text-violet-700 border border-violet-200 rounded-lg text-xs font-medium hover:bg-violet-100 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {suggestLoading
                      ? <><span className="animate-spin inline-block w-3 h-3 border border-violet-400 border-t-transparent rounded-full" />Generating...</>
                      : <>✨ Suggest hypotheses with AI{hypoForm.primary_metric && <span className="ml-1 text-violet-400">→ {hypoForm.primary_metric}</span>}</>}
                  </button>
                  <Tip wide text="AI writes the hypothesis, variable tested, and expected outcome using only the primary metric for your chosen Stage+Format. Example: Stop+Video → AI only talks about hook_rate, never CTR or ROAS." />
                  {(!hypoForm.funnel_stage || !hypoForm.format)
                    ? <span className="text-xs text-gray-400">Pick Funnel Stage + Format first — AI writes to that metric</span>
                    : null}
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
                {/* Link to Creative Library combos (multi-select) */}
                <div>
                  <label className="flex items-center gap-1 text-xs text-gray-500 mb-1">
                    Link to Creatives
                    <Tip text="Link one or more ads from the Creative Library. The hypothesis will aggregate metrics across all linked combos." wide />
                  </label>
                  {selectedComboIds.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mb-2">
                      {selectedComboIds.map(cid => (
                        <div key={cid} className="flex items-center gap-1.5 bg-violet-50 border border-violet-200 rounded-lg px-2.5 py-1">
                          <span className="font-mono text-xs text-violet-700">{cid}</span>
                          <button onClick={() => setSelectedComboIds(p => p.filter(id => id !== cid))}
                            className="text-violet-400 hover:text-violet-700"><X className="w-3 h-3" /></button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="relative">
                    <input
                      value={comboSearch}
                      onChange={e => { setComboSearch(e.target.value); searchCombos(e.target.value, accounts.find(a => a.account_name === hypoForm.branch_name)?.id) }}
                      onFocus={() => { if (!comboSearch && hypoForm.branch_name) searchCombos('', accounts.find(a => a.account_name === hypoForm.branch_name)?.id) }}
                      placeholder="Search by ad name or combo ID…"
                      className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
                    />
                    {comboSearchLoading && <span className="absolute right-3 top-2 text-xs text-gray-400 animate-pulse">searching…</span>}
                    {comboResults.length > 0 && (
                      <div className="absolute z-20 top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-xl max-h-52 overflow-auto">
                        {comboResults.map(r => {
                          const isSelected = selectedComboIds.includes(r.combo_id)
                          return (
                            <button key={r.combo_id} onClick={() => {
                              setSelectedComboIds(p => isSelected ? p.filter(id => id !== r.combo_id) : [...p, r.combo_id])
                              setComboSearch('')
                              setComboResults([])
                            }}
                              className={`w-full text-left px-3 py-2 border-b border-gray-50 last:border-0 ${isSelected ? 'bg-violet-50' : 'hover:bg-violet-50'}`}>
                              <div className="flex items-center gap-2">
                                {isSelected && <span className="text-violet-500 text-xs font-bold">✓</span>}
                                <span className="font-mono text-[10px] text-gray-400">{r.combo_id}</span>
                                <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium ${r.verdict === 'WIN' ? 'bg-green-100 text-green-700' : r.verdict === 'LOSE' ? 'bg-red-100 text-red-600' : 'bg-yellow-100 text-yellow-700'}`}>{r.verdict}</span>
                                {r.roas && <span className="text-[10px] text-gray-500">{r.roas.toFixed(2)}x</span>}
                              </div>
                              <p className="text-xs text-gray-700 truncate mt-0.5">{r.ad_name || '(no name)'}</p>
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
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
            const learningsByCategory: Record<string, Hypothesis[]> = {}
            concluded.filter(h => h.learning).forEach(h => {
              const k = HYPOTHESIS_CATEGORIES.find(c => c.value === h.hypothesis_category)?.label || 'General'
              ;(learningsByCategory[k] = learningsByCategory[k] || []).push(h)
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

                {Object.keys(learningsByCategory).length > 0 && (
                  <div className="bg-violet-50 rounded-xl border border-violet-100 p-5">
                    <p className="text-xs font-semibold text-violet-700 uppercase tracking-wider mb-3">Validated Learnings</p>
                    <div className="space-y-3">
                      {Object.entries(learningsByCategory).map(([desire, items]) => (
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
                          {canEdit && editingHypoId !== h.hypothesis_id && (
                            <button onClick={() => openEditHypo(h)} className="text-gray-300 hover:text-blue-500 transition-colors" title="Edit hypothesis">
                              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" /></svg>
                            </button>
                          )}
                          <span className="text-xs text-gray-500">{h.branch_name}</span>
                          {h.hypothesis_category && (
                            <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${CAT_COLOR[h.hypothesis_category] || 'bg-gray-50 text-gray-600 border-gray-200'}`}>
                              {HYPOTHESIS_CATEGORIES.find(c => c.value === h.hypothesis_category)?.label || h.hypothesis_category}
                            </span>
                          )}
                          {h.human_desire && <span className="text-xs bg-gray-100 text-gray-400 px-2 py-0.5 rounded-full">{h.human_desire}</span>}
                          {h.creative_angle && <span className="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded-full">{h.creative_angle}</span>}
                          {h.funnel_stage && <span className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded-full font-medium">{h.funnel_stage}</span>}
                          {h.format && <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">{h.format}</span>}
                          {h.target_audience && <span className="text-xs text-gray-400">{h.target_audience}</span>}
                          {h.market && <span className="text-xs text-gray-400">{h.market}</span>}
                          <span className="flex items-center gap-1">
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${HYPO_STATUS_BADGE[h.status] || 'bg-gray-100 text-gray-600'}`}>Layer A: {h.status}</span>
                            <Tip text={`Layer A = creative verdict. Did ${h.primary_metric || h.primary_kpi || 'primary metric'} exceed the threshold (${h.win_threshold ?? '—'}) after ${h.min_sample} concluded ads? No ROAS or booking involved.`} wide />
                          </span>
                          {h.layer_b_status && (
                            <span className="flex items-center gap-1">
                              <span className={`text-xs px-2 py-0.5 rounded-full font-medium border ${
                                h.layer_b_status === 'pass' ? 'bg-green-50 text-green-700 border-green-200' :
                                h.layer_b_status === 'fail' ? 'bg-red-50 text-red-600 border-red-200' :
                                'bg-gray-50 text-gray-500 border-gray-200'
                              }`}>Layer B: {h.layer_b_status}</span>
                              <Tip text="Layer B = downstream verdict (ROAS, booking rate). Independent of Layer A — a creative can pass Layer A (great hook) but fail Layer B (weak offer/landing page)." wide />
                            </span>
                          )}
                          {cohortRankMap[h.hypothesis_id] && (() => {
                            const r = cohortRankMap[h.hypothesis_id]
                            const medal = r.rank === 1 ? '🥇' : r.rank === 2 ? '🥈' : r.rank === 3 ? '🥉' : `#${r.rank}`
                            const parts = [r.label, r.metric].filter(Boolean).join(' · ')
                            return (
                              <span className={`text-xs px-2 py-0.5 rounded-full font-medium border ${r.rank === 1 ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-gray-50 text-gray-500 border-gray-200'}`}>
                                {medal}{parts ? ` in ${parts}` : ''}
                              </span>
                            )
                          })()}
                          {h.approval_status && (
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium border ${
                              h.approval_status === 'APPROVED' ? 'bg-green-50 text-green-700 border-green-200' :
                              'bg-orange-50 text-orange-700 border-orange-200'
                            }`}>
                              {h.approval_status === 'APPROVED' ? '✓ Approved' : '⏳ In Review'}
                            </span>
                          )}
                        </div>

                        {(h.linked_combos && h.linked_combos.length > 0) ? (
                          <div className="flex flex-wrap gap-1.5 mb-2">
                            {h.linked_combos.map(lc => (
                              <a key={lc.combo_id} href={`/creative?combo=${lc.combo_id}`}
                                className="inline-flex items-center gap-1.5 text-xs text-gray-500 hover:text-blue-600 bg-gray-50 hover:bg-blue-50 border border-gray-200 hover:border-blue-200 rounded-lg px-2.5 py-1 transition-colors">
                                <span className="font-mono text-gray-400">{lc.combo_id}</span>
                                {lc.ad_name && <span className="truncate max-w-[200px]">{lc.ad_name}</span>}
                                {lc.verdict && <span className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium ${lc.verdict === 'WIN' ? 'bg-green-100 text-green-700' : lc.verdict === 'LOSE' ? 'bg-red-100 text-red-600' : 'bg-yellow-100 text-yellow-700'}`}>{lc.verdict}</span>}
                                {lc.roas && <span className="text-gray-400">{lc.roas.toFixed(2)}x</span>}
                              </a>
                            ))}
                          </div>
                        ) : h.combo_id ? (
                          <a
                            href={`/creative?combo=${h.combo_id}`}
                            className="inline-flex items-center gap-1.5 mb-2 text-xs text-gray-500 hover:text-blue-600 bg-gray-50 hover:bg-blue-50 border border-gray-200 hover:border-blue-200 rounded-lg px-2.5 py-1 transition-colors"
                          >
                            <span className="font-mono text-gray-400">{h.combo_id}</span>
                            {h.ad_name && <span className="truncate max-w-[300px]">{h.ad_name}</span>}
                            <span className="text-gray-300">→ Creative Library</span>
                          </a>
                        ) : null}

                        {/* 4-tier hypothesis display */}
                        <div className="space-y-2 mb-3">
                          {h.customer_insight && (
                            <div className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2">
                              <p className="text-[9px] font-bold text-blue-400 uppercase tracking-widest mb-0.5">1 · Belief</p>
                              <p className="text-xs text-blue-900">{h.customer_insight}</p>
                            </div>
                          )}
                          <div className="bg-gray-50 border border-gray-100 rounded-lg px-3 py-2">
                            <p className="text-[9px] font-bold text-gray-400 uppercase tracking-widest mb-0.5">2 · Why <span className="normal-case font-normal text-amber-500">⚠ unconfirmed</span></p>
                            <p className="text-xs text-gray-800">{h.hypothesis}</p>
                          </div>
                          {h.variable_tested && (
                            <div className="bg-violet-50 border border-violet-100 rounded-lg px-3 py-2">
                              <p className="text-[9px] font-bold text-violet-400 uppercase tracking-widest mb-0.5">3 · Test</p>
                              <p className="text-xs text-violet-900">{h.variable_tested}</p>
                            </div>
                          )}
                          {(h.expected_outcome || hasResult) && (
                            <div className={`border rounded-lg px-3 py-2 ${h.status === 'validated' ? 'bg-green-50 border-green-100' : h.status === 'refuted' ? 'bg-red-50 border-red-100' : 'bg-amber-50 border-amber-100'}`}>
                              <p className="text-[9px] font-bold text-amber-500 uppercase tracking-widest mb-1">4 · Success</p>
                              {h.expected_outcome && <p className="text-xs font-semibold text-gray-800 mb-1">{h.expected_outcome}</p>}
                              {hasResult && (
                                <div className="flex flex-wrap gap-3 mt-1 pt-1 border-t border-gray-200">
                                  {h.actual_roas !== null && <span className="text-xs font-bold text-gray-700">ROAS: {h.actual_roas.toFixed(2)}x</span>}
                                  {h.actual_ctr !== null && <span className="text-xs text-gray-600">CTR: {(h.actual_ctr * 100).toFixed(2)}%</span>}
                                  {h.actual_spend !== null && <span className="text-xs text-gray-400">Spend: ${h.actual_spend.toLocaleString()}</span>}
                                  {clicks > 0 && <span className="text-xs text-gray-400">{clicks.toLocaleString()} clicks</span>}
                                </div>
                              )}
                              {!hasResult && <p className="text-[10px] text-gray-400 italic">Waiting for data…</p>}
                            </div>
                          )}
                        </div>

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
                            <Tip text="Paste brief + script or image URLs so AI can extract Evidence, Why It Worked, and a Creative Principle — explains why the ad did or did not work at a psychological level." wide />
                          </div>
                        )}

                        {nextStep && (
                          <div className={`rounded-lg px-3 py-2 border text-xs ${nextStep.color}`}>
                            <span className="mr-1">{nextStep.icon}</span>
                            <span className="font-semibold">Next: </span>{nextStep.text}
                          </div>
                        )}

                        {editingHypoId === h.hypothesis_id && (
                          <div className="mt-4 border-t border-blue-100 pt-4 space-y-3">
                            <p className="text-[10px] text-blue-500 uppercase tracking-wider font-semibold">Edit Hypothesis</p>
                            <div>
                              <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Hypothesis statement</label>
                              <textarea rows={3} value={editHypoForm.hypothesis || ''} onChange={e => setEditHypoForm(p => ({ ...p, hypothesis: e.target.value }))}
                                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm text-gray-800" />
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                              <div>
                                <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Customer insight</label>
                                <input value={editHypoForm.customer_insight || ''} onChange={e => setEditHypoForm(p => ({ ...p, customer_insight: e.target.value }))}
                                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
                              </div>
                              <div>
                                <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Human desire</label>
                                <input value={editHypoForm.human_desire || ''} onChange={e => setEditHypoForm(p => ({ ...p, human_desire: e.target.value }))}
                                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
                              </div>
                              <div>
                                <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Creative angle</label>
                                <input value={editHypoForm.creative_angle || ''} onChange={e => setEditHypoForm(p => ({ ...p, creative_angle: e.target.value }))}
                                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
                              </div>
                              <div>
                                <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Variable tested</label>
                                <input value={editHypoForm.variable_tested || ''} onChange={e => setEditHypoForm(p => ({ ...p, variable_tested: e.target.value }))}
                                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
                              </div>
                              <div>
                                <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Expected outcome</label>
                                <input value={editHypoForm.expected_outcome || ''} onChange={e => setEditHypoForm(p => ({ ...p, expected_outcome: e.target.value }))}
                                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
                              </div>
                              <div>
                                <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Target audience</label>
                                <input value={editHypoForm.target_audience || ''} onChange={e => setEditHypoForm(p => ({ ...p, target_audience: e.target.value }))}
                                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
                              </div>
                              <div>
                                <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Market</label>
                                <input value={editHypoForm.market || ''} onChange={e => setEditHypoForm(p => ({ ...p, market: e.target.value }))}
                                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
                              </div>
                              <div>
                                <label className="block text-[10px] text-gray-500 uppercase tracking-wider mb-1">Primary KPI</label>
                                <input value={editHypoForm.primary_kpi || ''} onChange={e => setEditHypoForm(p => ({ ...p, primary_kpi: e.target.value }))}
                                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
                              </div>
                            </div>
                            <div className="flex gap-2 pt-1">
                              <button onClick={() => saveEditHypo(h.hypothesis_id)} disabled={editSaving}
                                className="px-4 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
                                {editSaving ? 'Saving…' : 'Save'}
                              </button>
                              <button onClick={() => setEditingHypoId(null)}
                                className="px-4 py-1.5 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
                                Cancel
                              </button>
                            </div>
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
          <div className="flex flex-wrap items-center gap-2 mb-6">
            <select value={ldBranch} onChange={e => setLdBranch(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm font-medium">
              {BRANCH_NAMES.map(b => <option key={b}>{b}</option>)}
            </select>
            <select value={ldTA} onChange={e => setLdTA(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All TA</option>
              {['Solo', 'Couple', 'Friend', 'Group', 'Business'].map(t => <option key={t}>{t}</option>)}
            </select>
            <select value={ldMarket} onChange={e => setLdMarket(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
              <option value="">All Markets</option>
              {['VN', 'TW', 'JP', 'SG', 'HK', 'AU', 'US', 'GB', 'DE', 'FR', 'KR', 'TH', 'PH', 'MY', 'ID'].map(m => <option key={m}>{m}</option>)}
            </select>
            {(ldTA || ldMarket) && (
              <button onClick={() => { setLdTA(''); setLdMarket('') }} className="px-2.5 py-1.5 text-xs text-gray-400 hover:text-gray-600 border border-gray-200 rounded-lg">
                Clear
              </button>
            )}
            {ldLoading && <span className="text-xs text-gray-400">Loading...</span>}
          </div>

          {!learningDashboard || ldLoading ? (
            <div className="text-center text-gray-400 py-12">
              {ldLoading ? 'Loading knowledge base...' : 'Select a branch to see the learning dashboard.'}
            </div>
          ) : (
            <div className="space-y-5">
              {/* ── PIPELINE ── Pending → Running → Concluded */}
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-4">Hypothesis Pipeline</h3>
                <div className="flex items-stretch gap-0">
                  {[
                    { label: 'Pending', value: learningDashboard.total_pending, color: 'bg-gray-50 border-gray-200', badge: 'text-gray-500', dot: 'bg-gray-300' },
                    { label: 'Running', value: learningDashboard.total_running, color: 'bg-blue-50 border-blue-200', badge: 'text-blue-600', dot: 'bg-blue-400' },
                    { label: 'Concluded', value: learningDashboard.total_experiments, color: 'bg-gray-50 border-gray-200', badge: 'text-gray-700', dot: 'bg-gray-400' },
                    { label: 'Validated ✓', value: learningDashboard.total_validated, color: 'bg-green-50 border-green-200', badge: 'text-green-700', dot: 'bg-green-400' },
                    { label: 'Refuted ✗', value: learningDashboard.total_refuted, color: 'bg-red-50 border-red-200', badge: 'text-red-600', dot: 'bg-red-400' },
                  ].map((s, i) => (
                    <div key={s.label} className="flex items-center">
                      <div className={`border rounded-lg px-4 py-3 text-center min-w-[90px] ${s.color}`}>
                        <p className={`text-2xl font-bold ${s.badge}`}>{s.value}</p>
                        <p className="text-[10px] text-gray-500 mt-0.5 whitespace-nowrap">{s.label}</p>
                      </div>
                      {i < 4 && <div className="text-gray-300 px-1.5 text-lg select-none">›</div>}
                    </div>
                  ))}
                  <div className="ml-auto flex items-center">
                    {learningDashboard.total_experiments > 0 && (
                      <span className={`text-sm font-bold px-3 py-1 rounded-full ${
                        Math.round(learningDashboard.total_validated / learningDashboard.total_experiments * 100) >= 60
                          ? 'bg-green-100 text-green-700' : Math.round(learningDashboard.total_validated / learningDashboard.total_experiments * 100) >= 40
                          ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-600'
                      }`}>
                        {Math.round(learningDashboard.total_validated / learningDashboard.total_experiments * 100)}% win rate
                      </span>
                    )}
                  </div>
                </div>

                {/* Pending queue */}
                {learningDashboard.pending_hypotheses.length > 0 && (
                  <div className="mt-4 border-t border-gray-100 pt-4">
                    <p className="text-[10px] text-gray-400 uppercase tracking-wider mb-2 font-medium">
                      {learningDashboard.pending_hypotheses.length} waiting to launch — go to Hypotheses tab to set status → Running
                    </p>
                    <div className="space-y-1.5">
                      {learningDashboard.pending_hypotheses.slice(0, 5).map(h => (
                        <div key={h.hypothesis_id} className="flex items-start gap-2 text-sm">
                          <span className="font-mono text-[10px] text-gray-300 mt-0.5 shrink-0">{h.hypothesis_id}</span>
                          <span className="text-gray-700 line-clamp-1">{h.hypothesis}</span>
                          <div className="flex items-center gap-1 ml-auto shrink-0">
                            {h.funnel_stage && <span className="text-[10px] bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded">{h.funnel_stage}</span>}
                            {h.format && <span className="text-[10px] bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded">{h.format}</span>}
                          </div>
                        </div>
                      ))}
                      {learningDashboard.pending_hypotheses.length > 5 && (
                        <p className="text-[10px] text-gray-400">+{learningDashboard.pending_hypotheses.length - 5} more</p>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* ── FOCUS NOW ── Computed action items */}
              {(() => {
                const actions: { icon: string; text: string; sub: string; color: string }[] = []

                // 1. Pending hypotheses to launch
                if (learningDashboard.total_pending > 0 && learningDashboard.total_running === 0) {
                  actions.push({
                    icon: '🚀',
                    text: `Launch ${learningDashboard.total_pending} pending hypothesis${learningDashboard.total_pending > 1 ? 'es' : ''}`,
                    sub: 'None are running yet — go to Hypotheses tab and set status to Running',
                    color: 'border-blue-200 bg-blue-50',
                  })
                } else if (learningDashboard.total_pending > 0) {
                  actions.push({
                    icon: '📋',
                    text: `${learningDashboard.total_pending} hypothesis${learningDashboard.total_pending > 1 ? 'es' : ''} pending`,
                    sub: 'Review and launch when ready in the Hypotheses tab',
                    color: 'border-gray-200 bg-gray-50',
                  })
                }

                // 2. Winning desire to double down on
                const topDesire = learningDashboard.top_desires.find(d => d.sufficient && d.win_rate >= 60)
                if (topDesire) {
                  actions.push({
                    icon: '🎯',
                    text: `Double down on "${topDesire.desire}"`,
                    sub: `${topDesire.win_rate}% win rate across ${topDesire.experiments} tests — keep testing this desire`,
                    color: 'border-green-200 bg-green-50',
                  })
                }

                // 3. Weakest desire to reconsider
                const worstDesire = learningDashboard.top_desires.find(d => d.sufficient && d.win_rate < 40)
                if (worstDesire) {
                  actions.push({
                    icon: '⚠️',
                    text: `Rethink "${worstDesire.desire}" messaging`,
                    sub: `${worstDesire.win_rate}% win rate — the angle isn't resonating, try a different insight`,
                    color: 'border-amber-200 bg-amber-50',
                  })
                }

                // 4. Funnel bottleneck
                const funnelEntries = Object.entries(learningDashboard.funnel_failure_map)
                const worstStage = funnelEntries.sort(([, a], [, b]) => b.refute_rate - a.refute_rate)[0]
                if (worstStage && worstStage[1].refute_rate >= 50 && worstStage[1].total >= 2) {
                  const stageHints: Record<string, string> = {
                    Stop: 'Hook is weak — first 3 seconds not stopping the scroll',
                    Hold: 'Hook works but body loses attention — tighten the middle',
                    Click: 'Good content but CTA or offer isn\'t converting',
                    Downstream: 'Ad works but landing page or booking flow is losing people',
                  }
                  actions.push({
                    icon: '🔧',
                    text: `Fix the ${worstStage[0]} stage`,
                    sub: stageHints[worstStage[0]] || `${worstStage[1].refute_rate}% of tests fail here`,
                    color: 'border-red-200 bg-red-50',
                  })
                }

                // 5. Untested category gap
                const CATS = ['identity', 'decision_driver', 'emotional_trigger', 'travel_moment', 'social_proof', 'objection_handler', 'aha_moment', 'aspiration']
                const untestedCat = CATS.find(c => !learningDashboard.category_counts[c])
                if (untestedCat && learningDashboard.total_hypotheses > 0) {
                  actions.push({
                    icon: '🧪',
                    text: `Explore "${untestedCat.replace('_', ' ')}" — never tested`,
                    sub: 'Create a hypothesis in this category to broaden your learning coverage',
                    color: 'border-violet-200 bg-violet-50',
                  })
                }

                // 6. Need more data
                if (learningDashboard.total_experiments === 0 && learningDashboard.total_running > 0) {
                  actions.push({
                    icon: '⏳',
                    text: `Wait for ${learningDashboard.total_running} running test${learningDashboard.total_running > 1 ? 's' : ''} to conclude`,
                    sub: `Need at least ${learningDashboard.min_sample} concluded ads per hypothesis to reach a verdict`,
                    color: 'border-gray-200 bg-gray-50',
                  })
                }

                if (actions.length === 0) return null
                return (
                  <div>
                    <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">Focus Now</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {actions.slice(0, 4).map((a, i) => (
                        <div key={i} className={`rounded-xl border p-4 flex gap-3 items-start ${a.color}`}>
                          <span className="text-xl shrink-0">{a.icon}</span>
                          <div>
                            <p className="text-sm font-semibold text-gray-800">{a.text}</p>
                            <p className="text-xs text-gray-500 mt-0.5">{a.sub}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )
              })()}

              {/* ── LEARNINGS — only when validated data exists ── */}
              {learningDashboard.recent_learnings.length > 0 && (
                <div className="bg-violet-50 rounded-xl border border-violet-200 p-5">
                  <h3 className="text-xs font-bold text-violet-600 uppercase tracking-wider mb-4">What We Know Works</h3>
                  <div className="space-y-3">
                    {learningDashboard.recent_learnings.map(l => (
                      <div key={l.hypothesis_id} className="flex items-start gap-3">
                        <span className="text-green-500 text-base shrink-0">✓</span>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-violet-900">{l.learning}</p>
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

              {/* ── ANALYTICS — collapsible, only meaningful when data exists ── */}
              {learningDashboard.total_experiments > 0 && (
                <div>
                  <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">Win Rate Analysis</h3>
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                    {/* Desire Win Rate */}
                    {learningDashboard.top_desires.length > 0 && (
                      <div className="bg-white rounded-xl border border-gray-200 p-5">
                        <div className="flex items-center gap-2 mb-4">
                          <h4 className="text-sm font-semibold text-gray-700">By Desire</h4>
                          <Tip text="Win rate = validated ÷ (validated + refuted). Greyed = below min_sample." wide />
                        </div>
                        <div className="space-y-3">
                          {learningDashboard.top_desires.map(d => (
                            <div key={d.desire} className={d.sufficient ? '' : 'opacity-50'}>
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-sm font-medium text-gray-800 truncate max-w-[200px]">{d.desire}</span>
                                <span className={`text-sm font-bold ml-2 shrink-0 ${!d.sufficient ? 'text-gray-400' : d.win_rate >= 60 ? 'text-green-600' : d.win_rate >= 40 ? 'text-amber-600' : 'text-red-500'}`}>
                                  {d.sufficient ? `${d.win_rate}%` : `${d.experiments}/${learningDashboard.min_sample}`}
                                </span>
                              </div>
                              <div className="h-1.5 bg-gray-100 rounded-full">
                                <div className={`h-full rounded-full ${d.sufficient ? (d.win_rate >= 60 ? 'bg-green-400' : d.win_rate >= 40 ? 'bg-amber-400' : 'bg-red-400') : 'bg-gray-200'}`}
                                  style={{ width: d.sufficient ? `${d.win_rate}%` : `${Math.round(d.experiments / learningDashboard.min_sample * 100)}%` }} />
                              </div>
                              <p className="text-[10px] text-gray-400 mt-0.5">{d.wins}/{d.experiments} concluded{!d.sufficient && ` · ${learningDashboard.min_sample - d.experiments} more needed`}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Decision Driver */}
                    {learningDashboard.top_drivers.length > 0 && (
                      <div className="bg-white rounded-xl border border-gray-200 p-5">
                        <div className="flex items-center gap-2 mb-4">
                          <h4 className="text-sm font-semibold text-gray-700">By Category</h4>
                          <Tip text="Which message type is working best for this branch." wide />
                        </div>
                        <div className="space-y-3">
                          {learningDashboard.top_drivers.map(d => (
                            <div key={d.raw} className={d.sufficient ? '' : 'opacity-50'}>
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-sm font-medium text-gray-800">{d.category}</span>
                                <span className={`text-sm font-bold ${!d.sufficient ? 'text-gray-400' : d.win_rate >= 60 ? 'text-green-600' : d.win_rate >= 40 ? 'text-amber-600' : 'text-red-500'}`}>
                                  {d.sufficient ? `${d.win_rate}%` : '—'}
                                </span>
                              </div>
                              <div className="h-1.5 bg-gray-100 rounded-full">
                                {d.sufficient && <div className={`h-full rounded-full ${d.win_rate >= 60 ? 'bg-indigo-400' : d.win_rate >= 40 ? 'bg-amber-400' : 'bg-red-400'}`}
                                  style={{ width: `${d.win_rate}%` }} />}
                              </div>
                              <p className="text-[10px] text-gray-400 mt-0.5">{d.experiments} concluded{!d.sufficient && ` · needs ${learningDashboard.min_sample} min`}</p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Funnel Failure Map */}
                    {Object.keys(learningDashboard.funnel_failure_map).length > 0 && (
                      <div className="bg-white rounded-xl border border-gray-200 p-5">
                        <div className="flex items-center gap-2 mb-4">
                          <h4 className="text-sm font-semibold text-gray-700">Where Tests Fail</h4>
                          <Tip wide text="Stop = hook weak. Hold = body loses attention. Click = offer weak. Downstream = landing page problem." />
                        </div>
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
                      </div>
                    )}

                    {/* Angle Win Rate */}
                    {learningDashboard.angle_win_rates.length > 0 && (
                      <div className="bg-white rounded-xl border border-gray-200 p-5">
                        <div className="flex items-center gap-2 mb-4">
                          <h4 className="text-sm font-semibold text-gray-700">By Angle</h4>
                          <Tip wide text="Faded = below min_sample. Sorted by win rate." />
                        </div>
                        <div className="overflow-x-auto">
                          <table className="w-full text-sm">
                            <thead>
                              <tr className="text-[10px] text-gray-400 uppercase tracking-wider border-b border-gray-100">
                                <th className="text-left pb-2 font-medium">Angle</th>
                                <th className="text-right pb-2 font-medium w-16">W/T</th>
                                <th className="text-right pb-2 font-medium w-20">Win %</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-50">
                              {learningDashboard.angle_win_rates.map(a => (
                                <tr key={a.angle} className={a.sufficient ? '' : 'opacity-45'}>
                                  <td className={`py-2 pr-4 font-medium text-sm ${a.sufficient ? 'text-gray-800' : 'text-gray-400'}`}>{a.angle}</td>
                                  <td className="py-2 text-right text-xs text-gray-500">{a.wins}/{a.total}</td>
                                  <td className="py-2 text-right">
                                    {a.sufficient
                                      ? <span className={`font-bold ${a.win_rate >= 60 ? 'text-green-600' : a.win_rate >= 40 ? 'text-amber-600' : 'text-red-500'}`}>{a.win_rate}%</span>
                                      : <span className="text-gray-300 text-xs">–</span>}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* ── COHORT BATTLES ── */}
              {(() => {
                const metricVal = (h: Hypothesis): number | null => {
                  const m = h.primary_metric || h.primary_kpi || ''
                  if (m === 'roas' || m === 'ROAS') return h.actual_roas ?? null
                  if (m === 'CTR' || m === 'ctr') return h.actual_ctr ?? null
                  return h.actual_roas ?? h.actual_ctr ?? null
                }
                const branchHypos = hypotheses.filter(h => h.branch_name === ldBranch && metricVal(h) !== null)
                if (branchHypos.length === 0) return null

                const groups: Record<string, Hypothesis[]> = {}
                branchHypos.forEach(h => {
                  const key = [h.target_audience || 'All TA', h.market || 'All', h.primary_metric || h.primary_kpi || 'metric'].join(' · ')
                  ;(groups[key] = groups[key] || []).push(h)
                })
                // Only show cohorts with ≥2 hypotheses
                const battles = Object.entries(groups)
                  .filter(([, members]) => members.length >= 2)
                  .map(([key, members]) => ({
                    key,
                    members: [...members].sort((a, b) => (metricVal(b) ?? 0) - (metricVal(a) ?? 0)),
                  }))
                if (battles.length === 0) return null

                return (
                  <div className="bg-white rounded-xl border border-gray-200 p-5">
                    <div className="flex items-center gap-2 mb-4">
                      <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wider">Cohort Battles</h3>
                      <Tip wide text="Hypotheses ranked head-to-head within the same TA · Market · Metric cohort. Same playing field = fair comparison. 🥇 = highest metric value in that cohort." />
                    </div>
                    <div className="space-y-6">
                      {battles.map(({ key, members }) => {
                        const metric = members[0].primary_metric || members[0].primary_kpi || ''
                        const isRoas = metric === 'roas' || metric === 'ROAS'
                        return (
                          <div key={key}>
                            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-2">{key}</p>
                            <div className="space-y-1.5">
                              {members.map((h, i) => {
                                const val = metricVal(h) ?? 0
                                const best = metricVal(members[0]) ?? 1
                                const pct = best > 0 ? (val / best) * 100 : 0
                                const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `#${i + 1}`
                                const catLabel = HYPOTHESIS_CATEGORIES.find(c => c.value === h.hypothesis_category)?.label || ''
                                return (
                                  <div key={h.hypothesis_id} className="flex items-center gap-3">
                                    <span className="text-sm w-7 shrink-0 text-center">{medal}</span>
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-center gap-2 mb-1">
                                        <span className="font-mono text-[10px] text-gray-400">{h.hypothesis_id}</span>
                                        {catLabel && <span className={`text-[9px] px-1.5 py-0.5 rounded-full border font-medium ${CAT_COLOR[h.hypothesis_category!] || 'bg-gray-50 text-gray-500 border-gray-200'}`}>{catLabel}</span>}
                                        <span className={`text-xs font-bold ml-auto shrink-0 ${i === 0 ? 'text-amber-600' : 'text-gray-500'}`}>
                                          {isRoas ? `${val.toFixed(2)}x` : `${(val * 100).toFixed(2)}%`}
                                        </span>
                                      </div>
                                      <p className="text-xs text-gray-700 truncate mb-1">{h.hypothesis}</p>
                                      <div className="h-1.5 bg-gray-100 rounded-full">
                                        <div className={`h-full rounded-full transition-all ${i === 0 ? 'bg-amber-400' : 'bg-gray-300'}`}
                                          style={{ width: `${pct}%` }} />
                                      </div>
                                    </div>
                                  </div>
                                )
                              })}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )
              })()}
            </div>
          )}
        </>
      )}
      {/* ── BULK GENERATE MODAL ── */}
      {showBulkGen && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <div>
                <h2 className="text-base font-bold text-gray-900">✨ Generate Hypotheses</h2>
                <p className="text-xs text-gray-400 mt-0.5">Groups combos by TA · Market · Metric and proposes one hypothesis per cohort</p>
              </div>
              <button onClick={() => { setShowBulkGen(false); setBulkProposals([]) }}
                className="text-gray-400 hover:text-gray-600"><X className="w-5 h-5" /></button>
            </div>

            {/* Branch picker + generate */}
            <div className="px-6 py-4 border-b border-gray-100 flex items-center gap-3">
              <select value={bulkBranch} onChange={e => setBulkBranch(e.target.value)}
                className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm">
                <option value="">Select branch…</option>
                {BRANCH_NAMES.map(b => <option key={b}>{b}</option>)}
              </select>
              <button onClick={handleBulkGenerate} disabled={!bulkBranch || bulkLoading}
                className="px-4 py-2 bg-violet-600 text-white rounded-lg text-sm font-medium hover:bg-violet-700 disabled:opacity-50 flex items-center gap-2">
                {bulkLoading
                  ? <><span className="animate-spin w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full inline-block" />Analyzing combos…</>
                  : '→ Generate'}
              </button>
            </div>

            {/* Proposals list */}
            <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
              {bulkSkipped !== null && bulkSkipped > 0 && (
                <div className="text-xs text-gray-400 bg-gray-50 rounded-lg px-3 py-2 flex items-center gap-1.5">
                  <span className="text-green-500">✓</span>
                  {bulkSkipped} combos already covered by existing hypotheses — skipped
                </div>
              )}
              {bulkProposals.length === 0 && !bulkLoading && (
                <p className="text-sm text-gray-400 text-center py-8">
                  {bulkBranch ? 'Click Generate to analyse combos and propose hypotheses.' : 'Select a branch first.'}
                </p>
              )}
              {bulkProposals.map((p, i) => {
                const checked = bulkSelected.has(i)
                const catMeta = HYPOTHESIS_CATEGORIES.find(c => c.value === p.hypothesis_category)
                return (
                  <div key={i} onClick={() => setBulkSelected(prev => {
                    const n = new Set(prev); if (n.has(i)) n.delete(i); else n.add(i); return n
                  })}
                    className={`rounded-xl border p-4 cursor-pointer transition-colors ${checked ? 'border-violet-300 bg-violet-50' : 'border-gray-200 bg-white hover:bg-gray-50'}`}>
                    <div className="flex items-start gap-3">
                      <div className={`mt-0.5 w-4 h-4 rounded border-2 shrink-0 flex items-center justify-center ${checked ? 'bg-violet-600 border-violet-600' : 'border-gray-300'}`}>
                        {checked && <span className="text-white text-[10px] font-bold">✓</span>}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5 mb-1.5">
                          <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">{p.cohort_label}</span>
                          <span className="text-[10px] text-gray-300">·</span>
                          <span className="text-[10px] text-gray-400">{p.cohort_size} combos</span>
                          {catMeta && (
                            <span className={`text-[9px] px-1.5 py-0.5 rounded-full border font-medium ${catMeta.color}`}>{catMeta.label}</span>
                          )}
                        </div>
                        <p className="text-[9px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">Hypothesis</p>
                        <p className="text-sm text-gray-900 font-semibold mb-2">{p.hypothesis}</p>
                        {p.customer_insight && (
                          <p className="text-xs text-blue-600 italic mb-2">"{p.customer_insight}"</p>
                        )}
                        {(p as BulkProposal & {variable_tested?: string}).variable_tested && (
                          <p className="text-xs text-violet-600 font-medium mb-1.5">
                            🔬 {(p as BulkProposal & {variable_tested?: string}).variable_tested}
                          </p>
                        )}
                        <p className="text-xs font-mono text-amber-700 bg-amber-50 rounded px-2 py-1">{p.expected_outcome}</p>
                        <div className="flex flex-wrap gap-1 mt-2">
                          {p.combo_ids.slice(0, 6).map(cid => (
                            <span key={cid} className="font-mono text-[9px] bg-gray-100 text-gray-400 px-1.5 py-0.5 rounded">{cid}</span>
                          ))}
                          {p.combo_ids.length > 6 && <span className="text-[9px] text-gray-400">+{p.combo_ids.length - 6} more</span>}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>

            {/* Footer */}
            {bulkProposals.length > 0 && (
              <div className="px-6 py-4 border-t border-gray-100 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-500">{bulkSelected.size} / {bulkProposals.length} selected</span>
                  <button onClick={() => setBulkSelected(new Set(bulkProposals.map((_, i) => i)))}
                    className="text-xs text-violet-500 hover:text-violet-700">Select all</button>
                  <button onClick={() => setBulkSelected(new Set())}
                    className="text-xs text-gray-400 hover:text-gray-600">Clear</button>
                </div>
                <button onClick={handleBulkSave} disabled={bulkSelected.size === 0 || bulkSaving}
                  className="px-5 py-2 bg-violet-600 text-white rounded-lg text-sm font-medium hover:bg-violet-700 disabled:opacity-50 flex items-center gap-2">
                  {bulkSaving
                    ? <><span className="animate-spin w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full inline-block" />{bulkDone}/{bulkSelected.size} creating…</>
                    : `Create ${bulkSelected.size} Hypotheses`}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default function AnglesPage() {
  return (
    <Suspense>
      <AnglesPageInner />
    </Suspense>
  )
}
