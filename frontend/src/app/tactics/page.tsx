'use client'

import { Fragment, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  Plus, Trash2, X, ChevronDown, ChevronRight, AlertCircle, CheckCircle2,
  Power, PowerOff, TrendingUp, TrendingDown, Bell, ScrollText,
} from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line,
} from 'recharts'
import { useAuth } from '@/components/AuthContext'
import SurfRunsPanel from '@/components/tactics/SurfRunsPanel'
import {
  STATUS_STYLES, ago, describeAction, describeRule, describeTactic, entityWord,
  humanizeFailExample, metricLabel, tacticStatus,
  type LastError, type LastEvaluation, type RuleSummary,
} from '@/lib/tacticExplain'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type Condition = {
  metric: string
  operator: string
  threshold?: number
  days?: number
  compare_metric?: string
  compare_period_from?: number
  compare_period_to?: number
}

type Preset = {
  preset_type: string
  name: string
  description: string
  default_config: Record<string, any>
  revert_policy: 'none' | 'next_day' | 'on_recovery'
  valid_platforms: string[]
}

type Tactic = {
  id: string
  name: string
  preset_type: string
  platform: string
  account_id: string | null
  config: Record<string, any>
  is_active: boolean
  last_run_at: string | null
  rule_count: number
  created_at: string | null
  // Health fields (GET /api/tactics) — drive the "what it does" / "status"
  // columns so the table explains itself without expanding a row.
  rules_summary?: RuleSummary[]
  last_evaluation?: LastEvaluation | null
  last_error?: LastError | null
}

type TacticDetail = Tactic & {
  rules: Array<{
    id: string
    name: string
    entity_level: string
    action: string
    is_active: boolean
    conditions: any[]
    action_params: Record<string, any> | null
  }>
}

type Diagnostics = {
  tactic_id: string
  tactic_name: string
  is_active: boolean
  last_run_at: string | null
  rules: Array<{
    rule_id: string
    rule_name: string
    entity_level: string
    action: string
    is_active: boolean
    last_evaluated_at: string | null
    last_evaluation: {
      executed_at: string | null
      entities_checked: number | null
      actions_taken: number | null
      top_fail_reason: string | null
      fail_breakdown: Record<string, number> | null
      fail_examples: Array<{
        entity_id: string | null
        entity_name: string | null
        failed_at: string | null
        reason: string | null
      }>
      funnel_stage: string | null
      dynamic: {
        dynamic_mode: boolean
        funnel_stage: string | null
        lookback_days: number
        baselines: Record<string, number>
        effective_thresholds: Record<string, { value: number; source: string }>
      } | null
      error_message: string | null
    } | null
    recent_actions: Array<{
      executed_at: string | null
      action: string
      entity_name: string
      success: boolean
      error_message: string | null
    }>
  }>
}

type Account = { id: string; account_name: string; platform: string }

type Overview = {
  totals: {
    start: number
    pause: number
    increase_budget: number
    decrease_budget: number
    alert: number
    total: number
  }
  daily: Array<{
    date: string
    start: number
    pause: number
    increase_budget: number
    decrease_budget: number
    alert: number
  }>
  per_tactic: Array<{
    tactic_id: string
    automated_assets: number
    daily_actions: number[]
    total_actions: number
  }>
}

const REVERT_LABELS: Record<string, string> = {
  none: 'Permanent',
  next_day: 'Auto-revert next day',
  on_recovery: 'Reverses when REVIVE fires',
}

const HIDDEN_CONFIG_KEYS = new Set(['_preset_type', '_revert_policy'])

const ENTITY_LEVELS = [
  { value: 'campaign', label: 'Campaign Level' },
  { value: 'ad_set', label: 'Ad Set Level' },
  { value: 'ad', label: 'Ad Level' },
]

const METRICS = [
  'spend', 'revenue', 'roas', 'ctr', 'cpc', 'cpa',
  'impressions', 'clicks', 'conversions', 'frequency',
  'add_to_cart', 'checkouts', 'searches', 'leads',
  'hours_since_creation', 'active_ads_in_adset',
]
const OPERATORS = ['>', '<', '>=', '<=', '==']

const CAMPAIGN_ACTIONS = [
  { value: 'send_alert', label: 'Send Alert (log only)' },
  { value: 'pause_campaign', label: 'Pause Campaign' },
  { value: 'enable_campaign', label: 'Enable Campaign' },
  { value: 'adjust_budget', label: 'Adjust Budget' },
]
const ADSET_ACTIONS = [
  { value: 'send_alert', label: 'Send Alert (log only)' },
  { value: 'pause_adset', label: 'Pause Ad Set' },
  { value: 'enable_adset', label: 'Enable Ad Set' },
  { value: 'adjust_budget', label: 'Adjust Ad Set Budget' },
]
const AD_ACTIONS = [
  { value: 'send_alert', label: 'Send Alert (log only)' },
  { value: 'pause_ad', label: 'Pause Ad' },
  { value: 'enable_ad', label: 'Enable Ad' },
]

function actionsForLevel(level: string) {
  if (level === 'ad') return AD_ACTIONS
  if (level === 'ad_set') return ADSET_ACTIONS
  return CAMPAIGN_ACTIONS
}

/**
 * Every fetch on this page goes through here. The old code swallowed failures
 * (`.catch(() => {})`), so a 403 or a dead API looked exactly like "you have no
 * tactics" — which is the one thing the page must never do.
 */
async function loadJson(url: string): Promise<{ data?: any; error?: string }> {
  let res: Response
  try {
    res = await fetch(url, { credentials: 'include' })
  } catch (e: any) {
    return { error: `Cannot reach the API at ${API_BASE} (${e?.message || 'network error'}).` }
  }
  let body: any = null
  try {
    body = await res.json()
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    const detail = body?.detail || body?.error
    if (res.status === 401) return { error: 'You are not signed in (401). Log in again, then reload.' }
    if (res.status === 403) {
      return { error: `Your account has no access to the Automation section (403).${detail ? ` ${detail}` : ''}` }
    }
    return { error: `Request failed: HTTP ${res.status}${detail ? ` — ${detail}` : ''}` }
  }
  if (body && body.success === false) {
    return { error: body.error || 'The server returned an error with no message.' }
  }
  return { data: body?.data }
}

/** "3 ads" / "1 ad set" / "2 items" — whatever this tactic actually touches. */
function targetNoun(t: Tactic, count: number): string {
  const levels = new Set((t.rules_summary || []).map(r => r.entity_level))
  if (levels.size === 1) return entityWord(Array.from(levels)[0], count !== 1)
  return count === 1 ? 'item' : 'items'
}

function formatConfigValue(v: unknown): string {
  if (typeof v === 'number') return v.toLocaleString()
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  return String(v)
}

export default function TacticsPage() {
  const { canEditSection } = useAuth()
  const canEdit = canEditSection('automation')

  const [tactics, setTactics] = useState<Tactic[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Record<string, { detail?: TacticDetail; diagnostics?: Diagnostics } | 'loading'>>({})
  // Keyed by what failed, so a dead endpoint says so instead of rendering "0".
  const [errors, setErrors] = useState<Record<string, string>>({})

  // Account filter (table + overview both read this).
  const [filterAccountId, setFilterAccountId] = useState<string>('')
  // Show only active (toggled-on) tactics. Default on.
  const [activeOnly, setActiveOnly] = useState(true)

  // Overview dashboard state.
  const [overview, setOverview] = useState<Overview | null>(null)
  const [overviewDays, setOverviewDays] = useState<7 | 30>(7)
  const [overviewLoading, setOverviewLoading] = useState(false)

  // Create-tactic form state.
  const [showForm, setShowForm] = useState(false)
  const [formPreset, setFormPreset] = useState('')
  const [formName, setFormName] = useState('')
  const [formAccountId, setFormAccountId] = useState('')
  const [formOverrides, setFormOverrides] = useState<Record<string, string>>({})

  // Custom-preset-only state (full rule builder).
  const [customEntityLevel, setCustomEntityLevel] = useState('ad')
  const [customConditions, setCustomConditions] = useState<Condition[]>([
    { metric: 'roas', operator: '<', threshold: 1, days: 7 },
  ])
  const [customAction, setCustomAction] = useState('send_alert')
  const [customBudgetMultiplier, setCustomBudgetMultiplier] = useState(0.5)

  const currentPreset = useMemo(
    () => presets.find(p => p.preset_type === formPreset) || null,
    [presets, formPreset],
  )
  const isCustom = formPreset === 'custom_rule'

  const setError = (key: string, message?: string) => {
    setErrors(prev => {
      const next = { ...prev }
      if (message) next[key] = message
      else delete next[key]
      return next
    })
  }

  const fetchTactics = async () => {
    setLoading(true)
    const { data, error } = await loadJson(`${API_BASE}/api/tactics`)
    setError('tactics', error)
    if (data) setTactics(data)
    setLoading(false)
  }

  const fetchOverview = async (days: number, accountId: string) => {
    setOverviewLoading(true)
    const qs = new URLSearchParams({ days: String(days) })
    if (accountId) qs.set('account_id', accountId)
    const { data, error } = await loadJson(`${API_BASE}/api/tactics/overview?${qs.toString()}`)
    setError('overview', error)
    if (data) setOverview(data)
    setOverviewLoading(false)
  }

  useEffect(() => {
    fetchTactics()
    loadJson(`${API_BASE}/api/tactics/presets`).then(({ data, error }) => {
      setError('presets', error)
      if (data) setPresets(data)
    })
    loadJson(`${API_BASE}/api/accounts`).then(({ data, error }) => {
      setError('accounts', error)
      if (data) setAccounts(data)
    })
  }, [])

  useEffect(() => {
    fetchOverview(overviewDays, filterAccountId)
  }, [overviewDays, filterAccountId])

  // Client-side account filter — tactics list comes back unfiltered so we
  // don't have to re-query when the user toggles the dropdown.
  const filteredTactics = useMemo(() => {
    return tactics.filter(t =>
      (!filterAccountId || t.account_id === filterAccountId) &&
      (!activeOnly || t.is_active)
    )
  }, [tactics, filterAccountId, activeOnly])

  const perTacticById = useMemo(() => {
    const map: Record<string, Overview['per_tactic'][number]> = {}
    overview?.per_tactic.forEach(p => { map[p.tactic_id] = p })
    return map
  }, [overview])

  const resetForm = () => {
    setFormPreset('')
    setFormName('')
    setFormAccountId('')
    setFormOverrides({})
    setCustomEntityLevel('ad')
    setCustomConditions([{ metric: 'roas', operator: '<', threshold: 1, days: 7 }])
    setCustomAction('send_alert')
    setCustomBudgetMultiplier(0.5)
    setShowForm(false)
  }

  // When the user picks a non-custom preset, seed overrides with defaults so
  // the threshold editor renders with real values instead of empty inputs.
  useEffect(() => {
    if (!currentPreset || isCustom) return
    const seed: Record<string, string> = {}
    Object.entries(currentPreset.default_config).forEach(([k, v]) => {
      if (HIDDEN_CONFIG_KEYS.has(k)) return
      seed[k] = String(v)
    })
    setFormOverrides(seed)
  }, [currentPreset?.preset_type, isCustom])

  // Reset action when entity level changes (Custom).
  useEffect(() => {
    if (!isCustom) return
    const actions = actionsForLevel(customEntityLevel)
    if (!actions.find(a => a.value === customAction)) {
      setCustomAction(actions[0].value)
    }
  }, [customEntityLevel, isCustom])

  const submitCreate = () => {
    if (!formPreset) return
    let overrides: Record<string, any>
    if (isCustom) {
      const action_params = customAction === 'adjust_budget'
        ? { budget_multiplier: customBudgetMultiplier }
        : null
      overrides = {
        entity_level: customEntityLevel,
        conditions: customConditions,
        action: customAction,
        action_params,
      }
    } else {
      overrides = {}
      Object.entries(formOverrides).forEach(([k, raw]) => {
        const num = Number(raw)
        overrides[k] = !Number.isNaN(num) && raw.trim() !== '' ? num : raw
      })
    }
    fetch(`${API_BASE}/api/tactics`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        preset_type: formPreset,
        name: formName || null,
        platform: 'meta',
        account_id: formAccountId || null,
        config_overrides: overrides,
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          resetForm()
          fetchTactics()
        } else {
          alert(`Create failed: ${data.error}`)
        }
      })
      .catch(e => alert(`Create failed: ${e?.message || e}`))
  }

  const toggle = async (t: Tactic) => {
    const res = await fetch(`${API_BASE}/api/tactics/${t.id}/toggle`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !t.is_active }),
    }).then(r => r.json()).catch(e => ({ success: false, error: String(e?.message || e) }))
    setError('toggle', res.success ? undefined : `Could not switch "${t.name}": ${res.error}`)
    if (res.success) fetchTactics()
  }

  const remove = async (t: Tactic) => {
    if (!confirm(`Delete tactic "${t.name}"? Its ${t.rule_count} linked rule(s) will be removed too.`)) return
    const res = await fetch(`${API_BASE}/api/tactics/${t.id}`, {
      method: 'DELETE',
      credentials: 'include',
    }).then(r => r.json()).catch(e => ({ success: false, error: String(e?.message || e) }))
    setError('delete', res.success ? undefined : `Could not delete "${t.name}": ${res.error}`)
    if (res.success) fetchTactics()
  }

  const toggleExpand = async (t: Tactic) => {
    if (expanded[t.id]) {
      setExpanded(prev => ({ ...prev, [t.id]: undefined as any }))
      return
    }
    setExpanded(prev => ({ ...prev, [t.id]: 'loading' }))
    const [detailRes, diagRes] = await Promise.all([
      loadJson(`${API_BASE}/api/tactics/${t.id}`),
      loadJson(`${API_BASE}/api/tactics/${t.id}/diagnostics`),
    ])
    setError('detail', detailRes.error || diagRes.error)
    setExpanded(prev => ({
      ...prev,
      [t.id]: { detail: detailRes.data, diagnostics: diagRes.data },
    }))
  }

  const accountName = (id: string | null) => {
    if (!id) return 'All accounts'
    return accounts.find(a => a.id === id)?.account_name || id
  }

  // Custom-preset condition builder helpers
  const updateCondition = (idx: number, patch: Partial<Condition>) => {
    setCustomConditions(prev => prev.map((c, i) => i === idx ? { ...c, ...patch } : c))
  }
  const addCondition = () => {
    setCustomConditions(prev => [...prev, { metric: 'roas', operator: '<', threshold: 1, days: 7 }])
  }
  const removeCondition = (idx: number) => {
    setCustomConditions(prev => prev.filter((_, i) => i !== idx))
  }

  const tooltipDateLabel = (iso: string) => {
    const d = new Date(`${iso}T00:00:00`)
    return d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' })
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold">Tactics</h1>
          <p className="text-sm text-gray-500">
            Rules that watch your Meta ads and change them for you. They run once a day at
            17:00 UTC (midnight Vietnam time) — never more often, so budget changes don't stack up.
          </p>
        </div>
        {canEdit && (
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1 px-3 py-2 bg-blue-600 text-white rounded text-sm hover:bg-blue-700"
          >
            <Plus className="w-4 h-4" />
            New Tactic
          </button>
        )}
      </div>

      {/* Anything that failed to load says so here — never a silent zero. */}
      {Object.keys(errors).length > 0 && (
        <div className="mb-4 border border-red-200 bg-red-50 rounded-lg p-3">
          <div className="flex items-center gap-2 text-sm font-medium text-red-800 mb-1">
            <AlertCircle className="w-4 h-4" />
            Something on this page failed to load — the numbers below are incomplete.
          </div>
          <ul className="text-xs text-red-700 space-y-0.5 ml-6 list-disc">
            {Object.entries(errors).map(([key, msg]) => (
              <li key={key}><b>{key}</b>: {msg}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Overview dashboard: what tactics did over the last N days. */}
      <div className="border rounded-lg bg-white p-5 mb-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold">What your automations did for you</h2>
            <p className="text-xs text-gray-500">
              Changes actually pushed to Meta in this window. All zeros means no tactic
              hit its threshold — check each row's status below for the reason.
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-gray-600">
            <span>Timeframe:</span>
            <select
              value={overviewDays}
              onChange={e => setOverviewDays(parseInt(e.target.value, 10) as 7 | 30)}
              className="border rounded px-2 py-1 text-xs"
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2 mb-4">
          <SummaryCard
            label="Start"
            icon={<Power className="w-4 h-4 text-blue-600" />}
            value={overview?.totals.start ?? 0}
            loading={overviewLoading}
          />
          <SummaryCard
            label="Pause"
            icon={<PowerOff className="w-4 h-4 text-orange-500" />}
            value={overview?.totals.pause ?? 0}
            loading={overviewLoading}
          />
          <SummaryCard
            label="Increase Budget"
            icon={<TrendingUp className="w-4 h-4 text-green-600" />}
            value={overview?.totals.increase_budget ?? 0}
            loading={overviewLoading}
          />
          <SummaryCard
            label="Decrease Budget"
            icon={<TrendingDown className="w-4 h-4 text-red-500" />}
            value={overview?.totals.decrease_budget ?? 0}
            loading={overviewLoading}
          />
          <SummaryCard
            label="Alerts"
            icon={<Bell className="w-4 h-4 text-violet-600" />}
            value={overview?.totals.alert ?? 0}
            loading={overviewLoading}
          />
          <SummaryCard
            label="Total actions"
            icon={<CheckCircle2 className="w-4 h-4 text-gray-700" />}
            value={overview?.totals.total ?? 0}
            loading={overviewLoading}
            emphasis
          />
        </div>

        <div className="h-56">
          {overview && overview.totals.total === 0 && !overviewLoading ? (
            <div className="h-full flex flex-col items-center justify-center text-center text-sm text-gray-500 border border-dashed rounded">
              <span>No automated changes in the last {overviewDays} days.</span>
              <span className="text-xs mt-1">
                That is not an error by itself — a tactic only acts when an ad crosses its
                threshold. The Status column below says what each tactic found on its last run.
              </span>
            </div>
          ) : overview && (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={overview.daily} margin={{ top: 6, right: 12, left: -10, bottom: 0 }}>
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11 }}
                  tickFormatter={(d: string) => {
                    const dt = new Date(`${d}T00:00:00`)
                    return `${dt.getDate().toString().padStart(2, '0')}/${(dt.getMonth() + 1).toString().padStart(2, '0')}`
                  }}
                />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip
                  cursor={{ fill: 'rgba(0,0,0,0.04)' }}
                  contentStyle={{ fontSize: 12 }}
                  labelFormatter={(label: string) => tooltipDateLabel(label)}
                  formatter={(value: number, name: string) => {
                    const labels: Record<string, string> = {
                      start: 'Start',
                      pause: 'Pause',
                      increase_budget: 'Increase Budget',
                      decrease_budget: 'Decrease Budget',
                      alert: 'Alerts',
                    }
                    return [value, labels[name] || name]
                  }}
                />
                <Bar dataKey="start" stackId="a" fill="#2563eb" />
                <Bar dataKey="pause" stackId="a" fill="#f97316" />
                <Bar dataKey="increase_budget" stackId="a" fill="#16a34a" />
                <Bar dataKey="decrease_budget" stackId="a" fill="#ef4444" />
                <Bar dataKey="alert" stackId="a" fill="#8b5cf6" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Account filter for the tactics table below. */}
      <div className="flex items-center gap-3 mb-3">
        <label className="text-xs text-gray-600">Account:</label>
        <select
          value={filterAccountId}
          onChange={e => setFilterAccountId(e.target.value)}
          className="border rounded px-2 py-1 text-sm bg-white"
        >
          <option value="">All accounts</option>
          {accounts.map(a => (
            <option key={a.id} value={a.id}>
              {a.account_name} ({a.platform})
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={e => setActiveOnly(e.target.checked)}
            className="cursor-pointer"
          />
          Active only
        </label>
        <span className="text-xs text-gray-500">
          {filteredTactics.length} of {tactics.length} tactics
        </span>
      </div>

      {loading ? (
        <div className="p-8 text-center text-gray-400">Loading…</div>
      ) : filteredTactics.length === 0 ? (
        <div className="p-8 text-center border border-dashed rounded text-sm">
          {errors.tactics ? (
            <div className="text-red-700">
              The tactic list could not be loaded, so this is <b>not</b> proof that you have none.
              <div className="text-xs mt-1">{errors.tactics}</div>
            </div>
          ) : tactics.length === 0 ? (
            <div className="text-gray-500">
              You have no tactics at all. Nothing is automated right now — create one with
              <b> New Tactic</b>.
            </div>
          ) : (
            <div className="text-gray-500">
              You have {tactics.length} tactic{tactics.length === 1 ? '' : 's'}, but none match
              the current filter.
              {activeOnly && (
                <button
                  onClick={() => setActiveOnly(false)}
                  className="ml-1 text-blue-600 hover:underline"
                >
                  Show switched-off tactics too
                </button>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="border rounded overflow-hidden bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-3 py-2 w-8"></th>
                <th className="text-left px-3 py-2">Tactic</th>
                <th className="text-left px-3 py-2">What it does</th>
                <th className="text-left px-3 py-2 w-72">Status</th>
                <th className="text-left px-3 py-2">Changes ({overviewDays}d)</th>
                <th className="text-left px-3 py-2">On</th>
                <th className="text-right px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {filteredTactics.map(t => {
                const preset = presets.find(p => p.preset_type === t.preset_type)
                const exp = expanded[t.id]
                const isLoading = exp === 'loading'
                const expData = (exp && exp !== 'loading') ? exp : null
                return (
                  // Fragment needs the key — the rows inside are siblings.
                  <Fragment key={t.id}>
                    <tr className="border-t hover:bg-gray-50">
                      <td className="px-3 py-2">
                        <button onClick={() => toggleExpand(t)} className="text-gray-500 hover:text-gray-900">
                          {exp ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                        </button>
                      </td>
                      <td className="px-3 py-2 align-top">
                        <div className="font-medium">{t.name}</div>
                        <div className="text-xs text-gray-500">
                          {/* Most tactics are named after their preset — don't say it twice. */}
                          {(preset?.name || t.preset_type) !== t.name
                            ? `${preset?.name || t.preset_type} · ${accountName(t.account_id)}`
                            : accountName(t.account_id)}
                        </div>
                      </td>
                      <td className="px-3 py-2 align-top text-gray-700 max-w-md">
                        <ul className="space-y-0.5">
                          {describeTactic(t.rules_summary || []).map((line, i) => (
                            <li key={i} className="leading-snug">{line}</li>
                          ))}
                        </ul>
                        {preset?.revert_policy && preset.revert_policy !== 'none' && (
                          <div className="text-xs text-gray-500 mt-1">
                            {REVERT_LABELS[preset.revert_policy]}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2 align-top">
                        <StatusCell tactic={t} />
                      </td>
                      <td className="px-3 py-2 align-top">
                        <SparklineCell
                          daily={perTacticById[t.id]?.daily_actions}
                          total={perTacticById[t.id]?.total_actions ?? 0}
                        />
                        {(perTacticById[t.id]?.total_actions ?? 0) > 0 && (
                          <div className="text-xs text-gray-500">
                            on {perTacticById[t.id]?.automated_assets ?? 0}{' '}
                            {targetNoun(t, perTacticById[t.id]?.automated_assets ?? 0)}
                          </div>
                        )}
                      </td>
                      <td className="px-3 py-2 align-top">
                        <label className="inline-flex items-center cursor-pointer">
                          <input
                            type="checkbox"
                            checked={t.is_active}
                            onChange={() => canEdit && toggle(t)}
                            disabled={!canEdit}
                            className="sr-only peer"
                          />
                          <div className="relative w-9 h-5 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-blue-600 peer-disabled:opacity-50"></div>
                        </label>
                      </td>
                      <td className="px-3 py-2 text-right align-top">
                        <div className="inline-flex items-center gap-2">
                          <Link
                            href={`/tactics/${t.id}/log`}
                            className="text-gray-400 hover:text-indigo-600"
                            title="View change log"
                          >
                            <ScrollText className="w-4 h-4" />
                          </Link>
                          {canEdit && (
                            <button onClick={() => remove(t)} className="text-red-600 hover:text-red-800" title="Delete tactic">
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {isLoading && (
                      <tr key={`${t.id}-loading`} className="bg-gray-50 border-t">
                        <td colSpan={7} className="px-6 py-3 text-xs text-gray-500">Loading…</td>
                      </tr>
                    )}
                    {expData && (
                      <tr key={`${t.id}-detail`} className="bg-gray-50 border-t">
                        <td colSpan={7} className="px-6 py-4 text-xs">
                          <div>
                            <div className="font-medium text-gray-700 mb-1">Rules it runs every day</div>
                            <ul className="space-y-1">
                              {(expData.detail?.rules || []).map(r => (
                                <li key={r.id} className="bg-white border rounded p-2">
                                  <div>
                                    {describeRule({
                                      id: r.id,
                                      name: r.name,
                                      entity_level: r.entity_level,
                                      action: r.action,
                                      conditions: r.conditions,
                                      action_params: r.action_params,
                                      is_active: r.is_active,
                                    })}
                                  </div>
                                  <div className="text-gray-500 mt-0.5">
                                    Looks at every {entityWord(r.entity_level)} in scope
                                    {!r.is_active && ' · this rule is switched off'}
                                  </div>
                                </li>
                              ))}
                            </ul>
                            <details className="mt-2">
                              <summary className="cursor-pointer text-gray-500 hover:text-gray-700">
                                Raw settings (for debugging)
                              </summary>
                              <pre className="bg-white border rounded p-2 overflow-x-auto mt-1">
{JSON.stringify(
  Object.fromEntries(
    Object.entries(expData.detail?.config || {}).filter(([k]) => !HIDDEN_CONFIG_KEYS.has(k)),
  ),
  null, 2,
)}
                              </pre>
                            </details>
                          </div>

                          {/* SURF Intraday runs panel — only for engine-driven SURF intraday tactics. */}
                          {t.preset_type === 'surf_intraday_campaign' && (
                            <div className="mt-4">
                              <SurfRunsPanel tacticId={t.id} />
                            </div>
                          )}

                          {expData.diagnostics && (
                            <div className="mt-4">
                              <div className="font-medium text-gray-700 mb-2">What happened on the last run</div>
                              {expData.diagnostics.rules.map(r => (
                                <RuleRunReport key={r.rule_id} rule={r} />
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-3xl p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Create Tactic</h2>
              <button onClick={resetForm}><X className="w-5 h-5 text-gray-500" /></button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Preset</label>
                <select
                  value={formPreset}
                  onChange={e => setFormPreset(e.target.value)}
                  className="w-full border rounded px-2 py-1 text-sm"
                >
                  <option value="">— select —</option>
                  {presets.map(p => (
                    <option key={p.preset_type} value={p.preset_type}>{p.name}</option>
                  ))}
                </select>
                {currentPreset && (
                  <p className="text-xs text-gray-500 mt-1">{currentPreset.description}</p>
                )}
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Name (optional)</label>
                <input
                  value={formName}
                  onChange={e => setFormName(e.target.value)}
                  placeholder={currentPreset?.name || ''}
                  className="w-full border rounded px-2 py-1 text-sm"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Account</label>
                <select
                  value={formAccountId}
                  onChange={e => setFormAccountId(e.target.value)}
                  className="w-full border rounded px-2 py-1 text-sm"
                >
                  <option value="">All Meta accounts</option>
                  {accounts.filter(a => a.platform === 'meta').map(a => (
                    <option key={a.id} value={a.id}>{a.account_name}</option>
                  ))}
                </select>
              </div>

              {/* Threshold editor for preset-driven tactics. */}
              {currentPreset && !isCustom && (
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Thresholds & params</label>
                  <div className="grid grid-cols-2 gap-2">
                    {Object.entries(currentPreset.default_config)
                      .filter(([k]) => !HIDDEN_CONFIG_KEYS.has(k))
                      .map(([k, defaultVal]) => (
                        <div key={k}>
                          <label className="block text-xs text-gray-500">{k}</label>
                          <input
                            value={formOverrides[k] ?? String(defaultVal)}
                            onChange={e => setFormOverrides(prev => ({ ...prev, [k]: e.target.value }))}
                            className="w-full border rounded px-2 py-1 text-sm"
                            placeholder={formatConfigValue(defaultVal)}
                          />
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* Custom-preset builder. */}
              {isCustom && (
                <div className="space-y-3 border-t pt-3">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Entity Level</label>
                    <select
                      value={customEntityLevel}
                      onChange={e => setCustomEntityLevel(e.target.value)}
                      className="w-full border rounded px-2 py-1 text-sm"
                    >
                      {ENTITY_LEVELS.map(l => <option key={l.value} value={l.value}>{l.label}</option>)}
                    </select>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-xs font-medium text-gray-600">Conditions (ALL must match)</label>
                      <button onClick={addCondition} className="text-blue-600 text-xs hover:underline">+ Add</button>
                    </div>
                    <div className="space-y-2">
                      {customConditions.map((cond, idx) => (
                        <div key={idx} className="flex items-center gap-1 bg-gray-50 border rounded p-2">
                          <select
                            value={cond.metric}
                            onChange={e => updateCondition(idx, { metric: e.target.value })}
                            className="border rounded px-1 py-0.5 text-xs flex-1"
                          >
                            {METRICS.map(m => <option key={m} value={m}>{m}</option>)}
                          </select>
                          <select
                            value={cond.operator}
                            onChange={e => updateCondition(idx, { operator: e.target.value })}
                            className="border rounded px-1 py-0.5 text-xs"
                          >
                            {OPERATORS.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                          <input
                            type="number"
                            value={cond.threshold ?? ''}
                            onChange={e => updateCondition(idx, { threshold: parseFloat(e.target.value) })}
                            className="border rounded px-1 py-0.5 text-xs w-20"
                            placeholder="threshold"
                          />
                          <span className="text-xs text-gray-500">over</span>
                          <input
                            type="number"
                            value={cond.days ?? 7}
                            onChange={e => updateCondition(idx, { days: parseInt(e.target.value, 10) })}
                            className="border rounded px-1 py-0.5 text-xs w-14"
                          />
                          <span className="text-xs text-gray-500">d</span>
                          {customConditions.length > 1 && (
                            <button onClick={() => removeCondition(idx)} className="text-red-500 hover:text-red-700 ml-1">
                              <X className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">Action</label>
                    <select
                      value={customAction}
                      onChange={e => setCustomAction(e.target.value)}
                      className="w-full border rounded px-2 py-1 text-sm"
                    >
                      {actionsForLevel(customEntityLevel).map(a => (
                        <option key={a.value} value={a.value}>{a.label}</option>
                      ))}
                    </select>
                  </div>

                  {customAction === 'adjust_budget' && (
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Budget Multiplier</label>
                      <input
                        type="number"
                        step="0.05"
                        value={customBudgetMultiplier}
                        onChange={e => setCustomBudgetMultiplier(parseFloat(e.target.value))}
                        className="w-full border rounded px-2 py-1 text-sm"
                      />
                      <p className="text-xs text-gray-500 mt-1">e.g. 0.5 = halve budget · 1.5 = +50%. Single-step increases &gt; 25% are blocked unless this rule sits inside a preset tactic.</p>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <button onClick={resetForm} className="px-3 py-1.5 text-sm border rounded">Cancel</button>
              <button
                onClick={submitCreate}
                disabled={!formPreset}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded disabled:opacity-50"
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function SummaryCard({
  label,
  icon,
  value,
  loading,
  emphasis,
}: {
  label: string
  icon: React.ReactNode
  value: number
  loading?: boolean
  emphasis?: boolean
}) {
  return (
    <div className={`border rounded-md px-3 py-2 ${emphasis ? 'bg-gray-50' : 'bg-white'}`}>
      <div className="flex items-center gap-1.5 text-xs text-gray-600">
        {icon}
        <span>{label}</span>
      </div>
      <div className="mt-0.5 flex items-baseline justify-between">
        <span className={`font-semibold ${emphasis ? 'text-xl' : 'text-lg'}`}>
          {loading ? '…' : value.toLocaleString()}
        </span>
        <span className="text-[10px] text-gray-400">Actions triggered</span>
      </div>
    </div>
  )
}

/**
 * The whole point of the page: one badge + one sentence saying whether this
 * tactic did anything, and if not, why not.
 */
function StatusCell({ tactic }: { tactic: Tactic }) {
  const status = tacticStatus(tactic)
  return (
    <div>
      <span className={`inline-block px-2 py-0.5 rounded border text-xs font-medium ${STATUS_STYLES[status.tone]}`}>
        {status.label}
      </span>
      <div className="text-xs text-gray-600 mt-1 leading-snug">{status.detail}</div>
      {status.stale && (
        <div className="text-xs text-amber-700 mt-1">
          The daily run has not touched this in over 36h — the cron may not be running.
        </div>
      )}
    </div>
  )
}

/** Per-rule "what happened last night", in sentences rather than log codes. */
function RuleRunReport({ rule }: { rule: Diagnostics['rules'][number] }) {
  const ev = rule.last_evaluation
  const checked = ev?.entities_checked ?? 0
  const acted = ev?.actions_taken ?? 0

  return (
    <div className="bg-white border rounded p-3 mb-2">
      <div className="font-medium mb-2">{describeAction(rule.action, null)} · {entityWord(rule.entity_level)} level</div>

      {!ev ? (
        <div className="text-gray-600">
          Never evaluated. Either the daily cron has not run since this rule was created, or the
          sync has not produced metrics for it yet.
        </div>
      ) : (
        <div className="space-y-1">
          <div className="flex items-start gap-2">
            {acted > 0
              ? <CheckCircle2 className="w-3.5 h-3.5 text-green-600 mt-0.5 flex-shrink-0" />
              : <AlertCircle className="w-3.5 h-3.5 text-orange-500 mt-0.5 flex-shrink-0" />}
            <span>
              {ago(ev.executed_at)} it looked at <b>{checked}</b> {entityWord(rule.entity_level, checked !== 1)}
              {' and changed '}<b>{acted}</b>.
              {ev.funnel_stage && <> Only {ev.funnel_stage} entities are in scope for this tactic.</>}
            </span>
          </div>

          {checked === 0 && (
            <div className="text-gray-600 ml-5">
              Nothing was in scope. Usual causes: the tactic is pinned to an account with no
              matching {entityWord(rule.entity_level, true)}, the funnel filter excludes them all, or
              the sync has not written metrics yet.
            </div>
          )}

          {checked > 0 && acted === 0 && ev.top_fail_reason && (
            <div className="text-gray-700 ml-5">
              Nothing was changed because the {entityWord(rule.entity_level, true)} did not meet the
              condition on <b>{metricLabel(ev.top_fail_reason)}</b>
              {ev.fail_breakdown && Object.keys(ev.fail_breakdown).length > 1 && (
                <>
                  {' '}(others stopped at{' '}
                  {Object.entries(ev.fail_breakdown)
                    .filter(([k]) => k !== ev.top_fail_reason)
                    .map(([k, v]) => `${metricLabel(k)}: ${v}`)
                    .join(', ')})
                </>
              )}
              .
            </div>
          )}

          {ev.fail_examples && ev.fail_examples.length > 0 && (
            <div className="ml-5 mt-1">
              <div className="text-gray-600 mb-1">For example:</div>
              <ul className="space-y-0.5">
                {ev.fail_examples.slice(0, 5).map((ex, i) => (
                  <li key={i} className="text-gray-700">
                    <span className="font-medium">{ex.entity_name || ex.entity_id || 'unnamed'}</span>
                    {' — '}
                    <span className="text-gray-600">{humanizeFailExample(ex.reason, ex.failed_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {ev.dynamic && Object.keys(ev.dynamic.effective_thresholds || {}).length > 0 && (
            <div className="mt-2 p-2 bg-blue-50 border border-blue-200 rounded ml-5">
              <div className="text-blue-800 font-medium mb-1">
                This rule sets its own bar from your recent results
              </div>
              <ul className="space-y-0.5">
                {Object.entries(ev.dynamic.effective_thresholds).map(([metric, info]) => (
                  <li key={metric} className="text-gray-700">
                    {metricLabel(metric)} bar today = <b>{info.value.toFixed(2)}</b>
                    <div className="text-gray-500 ml-4">{info.source}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {ev.error_message && acted === 0 && checked === 0 && (
            <div className="text-red-700 ml-5">{ev.error_message}</div>
          )}
        </div>
      )}

      {rule.recent_actions.length > 0 && (
        <div className="mt-3">
          <div className="text-gray-700 font-medium mb-1">Changes it has made</div>
          <ul className="space-y-0.5">
            {rule.recent_actions.slice(0, 5).map((a, i) => (
              <li key={i} className="flex items-start gap-2">
                {a.success
                  ? <CheckCircle2 className="w-3.5 h-3.5 text-green-600 mt-0.5 flex-shrink-0" />
                  : <AlertCircle className="w-3.5 h-3.5 text-red-600 mt-0.5 flex-shrink-0" />}
                <div>
                  {describeAction(a.action, null)} — <span className="font-medium">{a.entity_name}</span>
                  {a.executed_at && <span className="text-gray-400 ml-2">{ago(a.executed_at)}</span>}
                  {!a.success && (
                    <div className="text-red-700 mt-0.5 break-words">
                      Failed: {a.error_message || 'Meta returned no error message.'}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function SparklineCell({ daily, total }: { daily?: number[]; total: number }) {
  if (!daily || daily.length === 0 || total === 0) {
    return <span className="text-xs text-gray-400">—</span>
  }
  const data = daily.map((v, i) => ({ i, v }))
  return (
    <div className="flex items-center gap-2">
      <div className="w-24 h-8">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 2, right: 2, left: 2, bottom: 2 }}>
            <Line
              type="monotone"
              dataKey="v"
              stroke="#2563eb"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <span className="text-xs text-gray-600 tabular-nums">{total}</span>
    </div>
  )
}
