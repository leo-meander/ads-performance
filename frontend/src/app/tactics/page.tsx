'use client'

import { useEffect, useMemo, useState } from 'react'
import { Plus, Trash2, X, ChevronDown, ChevronRight, AlertCircle, CheckCircle2 } from 'lucide-react'
import { useAuth } from '@/components/AuthContext'

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

  const fetchTactics = () => {
    setLoading(true)
    fetch(`${API_BASE}/api/tactics`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setTactics(data.data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchTactics()
    fetch(`${API_BASE}/api/tactics/presets`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setPresets(data.data) })
      .catch(() => {})
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setAccounts(data.data) })
      .catch(() => {})
  }, [])

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
  }

  const toggle = (t: Tactic) => {
    fetch(`${API_BASE}/api/tactics/${t.id}/toggle`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !t.is_active }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.success) fetchTactics()
      })
  }

  const remove = (t: Tactic) => {
    if (!confirm(`Delete tactic "${t.name}"? Its ${t.rule_count} linked rule(s) will be removed too.`)) return
    fetch(`${API_BASE}/api/tactics/${t.id}`, {
      method: 'DELETE',
      credentials: 'include',
    })
      .then(r => r.json())
      .then(data => {
        if (data.success) fetchTactics()
      })
  }

  const toggleExpand = async (t: Tactic) => {
    if (expanded[t.id]) {
      setExpanded(prev => ({ ...prev, [t.id]: undefined as any }))
      return
    }
    setExpanded(prev => ({ ...prev, [t.id]: 'loading' }))
    const [detailRes, diagRes] = await Promise.all([
      fetch(`${API_BASE}/api/tactics/${t.id}`, { credentials: 'include' }).then(r => r.json()),
      fetch(`${API_BASE}/api/tactics/${t.id}/diagnostics`, { credentials: 'include' }).then(r => r.json()),
    ])
    setExpanded(prev => ({
      ...prev,
      [t.id]: {
        detail: detailRes.success ? detailRes.data : undefined,
        diagnostics: diagRes.success ? diagRes.data : undefined,
      },
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

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold">Tactics</h1>
          <p className="text-sm text-gray-500">
            Automation strategies (preset bundles + custom rules). Runs once daily at 17:00 UTC
            so budget mutations don't compound across intraday syncs.
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

      {loading ? (
        <div className="p-8 text-center text-gray-400">Loading…</div>
      ) : tactics.length === 0 ? (
        <div className="p-8 text-center text-gray-400 border border-dashed rounded">
          No tactics yet. Create one from a preset.
        </div>
      ) : (
        <div className="border rounded overflow-hidden bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-gray-600">
              <tr>
                <th className="text-left px-3 py-2 w-8"></th>
                <th className="text-left px-3 py-2">Name</th>
                <th className="text-left px-3 py-2">Preset</th>
                <th className="text-left px-3 py-2">Account</th>
                <th className="text-left px-3 py-2">Revert</th>
                <th className="text-left px-3 py-2">Rules</th>
                <th className="text-left px-3 py-2">Last run</th>
                <th className="text-left px-3 py-2">Active</th>
                <th className="text-right px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {tactics.map(t => {
                const preset = presets.find(p => p.preset_type === t.preset_type)
                const exp = expanded[t.id]
                const isLoading = exp === 'loading'
                const expData = (exp && exp !== 'loading') ? exp : null
                return (
                  <>
                    <tr key={t.id} className="border-t hover:bg-gray-50">
                      <td className="px-3 py-2">
                        <button onClick={() => toggleExpand(t)} className="text-gray-500 hover:text-gray-900">
                          {exp ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                        </button>
                      </td>
                      <td className="px-3 py-2 font-medium">{t.name}</td>
                      <td className="px-3 py-2 text-gray-600">{preset?.name || t.preset_type}</td>
                      <td className="px-3 py-2 text-gray-600">{accountName(t.account_id)}</td>
                      <td className="px-3 py-2 text-gray-600">
                        {REVERT_LABELS[preset?.revert_policy || 'none']}
                      </td>
                      <td className="px-3 py-2 text-gray-600">{t.rule_count}</td>
                      <td className="px-3 py-2 text-gray-600 text-xs">
                        {t.last_run_at ? new Date(t.last_run_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-3 py-2">
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
                      <td className="px-3 py-2 text-right">
                        {canEdit && (
                          <button onClick={() => remove(t)} className="text-red-600 hover:text-red-800">
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </td>
                    </tr>
                    {isLoading && (
                      <tr key={`${t.id}-loading`} className="bg-gray-50 border-t">
                        <td colSpan={9} className="px-6 py-3 text-xs text-gray-500">Loading…</td>
                      </tr>
                    )}
                    {expData && (
                      <tr key={`${t.id}-detail`} className="bg-gray-50 border-t">
                        <td colSpan={9} className="px-6 py-4 text-xs">
                          <div className="grid grid-cols-2 gap-6">
                            <div>
                              <div className="font-medium text-gray-700 mb-1">Config</div>
                              <pre className="bg-white border rounded p-2 overflow-x-auto">
{JSON.stringify(
  Object.fromEntries(
    Object.entries(expData.detail?.config || {}).filter(([k]) => !HIDDEN_CONFIG_KEYS.has(k)),
  ),
  null, 2,
)}
                              </pre>
                            </div>
                            <div>
                              <div className="font-medium text-gray-700 mb-1">Rules ({expData.detail?.rules?.length || 0})</div>
                              <ul className="space-y-1">
                                {(expData.detail?.rules || []).map(r => (
                                  <li key={r.id} className="bg-white border rounded p-2">
                                    <div className="font-medium">{r.name}</div>
                                    <div className="text-gray-500">
                                      level={r.entity_level} · action={r.action} · active={String(r.is_active)}
                                    </div>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          </div>

                          {expData.diagnostics && (
                            <div className="mt-4">
                              <div className="font-medium text-gray-700 mb-2">Why it did / didn't fire</div>
                              {expData.diagnostics.rules.map(r => (
                                <div key={r.rule_id} className="bg-white border rounded p-3 mb-2">
                                  <div className="font-medium mb-2">{r.rule_name}</div>
                                  {r.last_evaluation ? (
                                    <div className="space-y-1">
                                      <div className="flex items-center gap-2">
                                        {r.last_evaluation.actions_taken && r.last_evaluation.actions_taken > 0 ? (
                                          <CheckCircle2 className="w-3.5 h-3.5 text-green-600" />
                                        ) : (
                                          <AlertCircle className="w-3.5 h-3.5 text-orange-500" />
                                        )}
                                        <span>
                                          Last evaluated{' '}
                                          {r.last_evaluation.executed_at
                                            ? new Date(r.last_evaluation.executed_at).toLocaleString()
                                            : '—'}
                                          {' · '}
                                          checked <b>{r.last_evaluation.entities_checked ?? 0}</b> entities · acted on{' '}
                                          <b>{r.last_evaluation.actions_taken ?? 0}</b>
                                        </span>
                                      </div>
                                      {r.last_evaluation.top_fail_reason && (
                                        <div className="text-gray-600">
                                          Top fail reason: <code className="bg-gray-100 px-1 rounded">{r.last_evaluation.top_fail_reason}</code>
                                          {r.last_evaluation.fail_breakdown && (
                                            <span className="ml-2 text-gray-500">
                                              ({Object.entries(r.last_evaluation.fail_breakdown).map(([k, v]) => `${k}=${v}`).join(', ')})
                                            </span>
                                          )}
                                        </div>
                                      )}
                                      {r.last_evaluation.fail_examples && r.last_evaluation.fail_examples.length > 0 && (
                                        <div className="mt-1">
                                          <div className="text-gray-600 mb-1">Examples:</div>
                                          <ul className="ml-3 space-y-0.5">
                                            {r.last_evaluation.fail_examples.slice(0, 5).map((ex, i) => (
                                              <li key={i} className="text-gray-700">
                                                <code className="text-xs">{ex.entity_name || ex.entity_id || '—'}</code>
                                                {' — '}
                                                <span className="text-gray-500">{ex.reason || '(no detail)'}</span>
                                              </li>
                                            ))}
                                          </ul>
                                        </div>
                                      )}
                                    </div>
                                  ) : (
                                    <div className="text-gray-500">Never evaluated yet. Cron hasn't run or sync isn't producing metrics.</div>
                                  )}

                                  {r.recent_actions.length > 0 && (
                                    <div className="mt-3">
                                      <div className="text-gray-700 font-medium mb-1">Recent actions</div>
                                      <ul className="space-y-0.5">
                                        {r.recent_actions.slice(0, 5).map((a, i) => (
                                          <li key={i} className="flex items-start gap-2">
                                            {a.success ? (
                                              <CheckCircle2 className="w-3.5 h-3.5 text-green-600 mt-0.5 flex-shrink-0" />
                                            ) : (
                                              <AlertCircle className="w-3.5 h-3.5 text-red-600 mt-0.5 flex-shrink-0" />
                                            )}
                                            <div>
                                              <code className="text-xs">{a.action}</code>{' on '}
                                              <span>{a.entity_name}</span>
                                              {a.executed_at && (
                                                <span className="text-gray-400 text-xs ml-2">
                                                  {new Date(a.executed_at).toLocaleString()}
                                                </span>
                                              )}
                                              {!a.success && a.error_message && (
                                                <div className="text-red-700 mt-0.5 break-words">{a.error_message}</div>
                                              )}
                                            </div>
                                          </li>
                                        ))}
                                      </ul>
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </>
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
