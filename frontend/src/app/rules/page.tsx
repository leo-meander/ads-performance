'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Trash2, Play, X, FileText, Pencil } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Condition {
  metric: string
  operator: string
  threshold?: number
  days?: number
  // Cross-period comparison
  compare_metric?: string
  compare_period_from?: number
  compare_period_to?: number
}

interface Rule {
  id: string
  name: string
  platform: string
  account_id: string | null
  entity_level: string
  conditions: Condition[]
  action: string
  action_params: Record<string, any> | null
  is_active: boolean
  last_evaluated_at: string | null
  created_at: string | null
}

interface Account {
  id: string
  account_name: string
}

const ENTITY_LEVELS = [
  { value: 'campaign', label: 'Campaign Level' },
  { value: 'ad_set', label: 'Ad Set Level' },
  { value: 'ad', label: 'Ad Level' },
]

const BASE_METRICS = [
  'spend', 'revenue', 'roas', 'ctr', 'cpc', 'cpa',
  'impressions', 'clicks', 'conversions', 'frequency',
  'add_to_cart', 'checkouts', 'searches', 'leads',
  'hours_since_creation',
]
const ADSET_AD_METRICS = ['active_ads_in_adset']

const OPERATORS = ['>', '<', '>=', '<=', '==']
const PERIODS = [
  { value: 'today', label: 'Today', days: 0 },
  { value: 'last_7d', label: 'Last 7 days', days: 7 },
  { value: 'last_14d', label: 'Last 14 days', days: 14 },
  { value: 'last_30d', label: 'Last 30 days', days: 30 },
]
const COMPARE_PERIODS = [
  { value: '0_30', label: 'Last 30 days (incl. today)', from: 0, to: 30 },
  { value: '7_15', label: 'From 7-15 days ago', from: 7, to: 15 },
  { value: '7_30', label: 'From 7-30 days ago', from: 7, to: 30 },
  { value: '14_28', label: 'From 14-28 days ago', from: 14, to: 28 },
]

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
]
const AD_ACTIONS = [
  { value: 'send_alert', label: 'Send Alert (log only)' },
  { value: 'pause_ad', label: 'Pause Ad' },
  { value: 'enable_ad', label: 'Enable Ad' },
]

function getActionsForLevel(level: string) {
  if (level === 'ad') return AD_ACTIONS
  if (level === 'ad_set') return ADSET_ACTIONS
  return CAMPAIGN_ACTIONS
}

function getMetricsForLevel(level: string) {
  if (level === 'ad' || level === 'ad_set') return [...BASE_METRICS, ...ADSET_AD_METRICS]
  return BASE_METRICS
}

function entityLevelLabel(level: string) {
  const found = ENTITY_LEVELS.find(e => e.value === level)
  return found ? found.label : level
}

function conditionSummary(conditions: Condition[]): string {
  return conditions.map(c => {
    if (c.metric === 'hours_since_creation') return `age ${c.operator} ${c.threshold}h`
    if (c.metric === 'active_ads_in_adset') return `active_ads_in_adset ${c.operator} ${c.threshold}`
    if (c.compare_metric) return `${c.metric}(${c.days}d) ${c.operator} ${c.compare_metric}(${c.compare_period_from}-${c.compare_period_to}d ago)`
    return `${c.metric} ${c.operator} ${c.threshold} (${c.days}d)`
  }).join(' AND ')
}

export default function RulesPage() {
  const router = useRouter()
  const [rules, setRules] = useState<Rule[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingRuleId, setEditingRuleId] = useState<string | null>(null)
  const [evalResult, setEvalResult] = useState<string | null>(null)

  const [formName, setFormName] = useState('')
  const [formPlatform, setFormPlatform] = useState('meta')
  const [formAccountId, setFormAccountId] = useState('')
  const [formEntityLevel, setFormEntityLevel] = useState('campaign')
  const [formConditions, setFormConditions] = useState<Condition[]>([
    { metric: 'roas', operator: '<', threshold: 1, days: 7 },
  ])
  const [formAction, setFormAction] = useState('send_alert')
  const [formBudgetMultiplier, setFormBudgetMultiplier] = useState(0.5)

  const isEditing = editingRuleId !== null

  const fetchRules = () => {
    setLoading(true)
    fetch(`${API_BASE}/api/rules`)
      .then(r => r.json())
      .then(data => { if (data.success) setRules(data.data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchRules()
    fetch(`${API_BASE}/api/accounts`)
      .then(r => r.json())
      .then(data => { if (data.success) setAccounts(data.data) })
      .catch(() => {})
  }, [])

  // Reset action when entity level changes
  useEffect(() => {
    const actions = getActionsForLevel(formEntityLevel)
    if (!actions.find(a => a.value === formAction)) {
      setFormAction(actions[0].value)
    }
  }, [formEntityLevel])

  const resetForm = () => {
    setFormName('')
    setFormPlatform('meta')
    setFormAccountId('')
    setFormEntityLevel('campaign')
    setFormConditions([{ metric: 'roas', operator: '<', threshold: 1, days: 7 }])
    setFormAction('send_alert')
    setFormBudgetMultiplier(0.5)
    setEditingRuleId(null)
    setShowForm(false)
  }

  const startCreate = () => {
    resetForm()
    setShowForm(true)
  }

  const startEdit = (rule: Rule) => {
    setEditingRuleId(rule.id)
    setFormName(rule.name)
    setFormPlatform(rule.platform)
    setFormAccountId(rule.account_id || '')
    setFormEntityLevel(rule.entity_level || 'campaign')
    setFormConditions(rule.conditions)
    setFormAction(rule.action)
    setFormBudgetMultiplier(rule.action_params?.budget_multiplier ?? 0.5)
    setShowForm(true)
  }

  const handleSubmit = () => {
    const body: any = {
      name: formName,
      platform: formPlatform,
      account_id: formAccountId || null,
      entity_level: formEntityLevel,
      conditions: formConditions,
      action: formAction,
    }
    if (formAction === 'adjust_budget') {
      body.action_params = { budget_multiplier: formBudgetMultiplier }
    }

    const url = isEditing ? `${API_BASE}/api/rules/${editingRuleId}` : `${API_BASE}/api/rules`
    const method = isEditing ? 'PUT' : 'POST'

    fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          resetForm()
          fetchRules()
        }
      })
  }

  const toggleActive = (rule: Rule) => {
    fetch(`${API_BASE}/api/rules/${rule.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_active: !rule.is_active }),
    }).then(() => fetchRules())
  }

  const deleteRule = (id: string) => {
    fetch(`${API_BASE}/api/rules/${id}`, { method: 'DELETE' }).then(() => fetchRules())
  }

  const evaluateRule = (id: string) => {
    setEvalResult(null)
    fetch(`${API_BASE}/api/rules/${id}/evaluate`, { method: 'POST' })
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          setEvalResult(`Rule "${data.data.rule_name}": ${data.data.actions_taken} action(s) taken`)
        } else {
          setEvalResult(`Error: ${data.error}`)
        }
      })
  }

  const metrics = getMetricsForLevel(formEntityLevel)
  const actions = getActionsForLevel(formEntityLevel)

  const addCondition = () => setFormConditions([...formConditions, { metric: 'spend', operator: '>', threshold: 0, days: 7 }])
  const removeCondition = (i: number) => setFormConditions(formConditions.filter((_, idx) => idx !== i))
  const updateCondition = (i: number, field: string, value: any) => {
    const updated = [...formConditions]
    updated[i] = { ...updated[i], [field]: value }
    setFormConditions(updated)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Automation Rules</h1>
        <button onClick={startCreate} className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
          <Plus className="w-4 h-4" /> Create Rule
        </button>
      </div>

      {evalResult && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 mb-4 text-sm text-blue-700 flex items-center justify-between">
          {evalResult}
          <button onClick={() => setEvalResult(null)}><X className="w-4 h-4" /></button>
        </div>
      )}

      {showForm && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-900">{isEditing ? 'Edit Rule' : 'New Rule'}</h2>
            <button onClick={resetForm}><X className="w-5 h-5 text-gray-400" /></button>
          </div>
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Rule Name</label>
                <input type="text" value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="e.g., Pause low ROAS campaigns" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Platform</label>
                <select value={formPlatform} onChange={(e) => setFormPlatform(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                  <option value="meta">Meta</option>
                  <option value="all">All Platforms</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Entity Level</label>
                <select value={formEntityLevel} onChange={(e) => setFormEntityLevel(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                  {ENTITY_LEVELS.map(l => <option key={l.value} value={l.value}>{l.label}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Branch (optional)</label>
                <select value={formAccountId} onChange={(e) => setFormAccountId(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                  <option value="">All branches</option>
                  {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
                </select>
              </div>
            </div>

            <div>
              <label className="block text-xs text-gray-500 mb-2">Conditions (all must be true)</label>
              {formConditions.map((cond, i) => {
                const isAge = cond.metric === 'hours_since_creation'
                const isCountMetric = cond.metric === 'active_ads_in_adset'
                const isCrossPeriod = !!cond.compare_metric
                return (
                  <div key={i} className="flex flex-wrap items-center gap-2 mb-3 p-3 bg-gray-50 rounded-lg">
                    <span className="text-xs font-medium text-blue-600 w-8">{i > 0 ? 'AND' : 'IF'}</span>
                    {/* Metric */}
                    <select value={cond.metric} onChange={(e) => {
                      const m = e.target.value
                      if (m === 'hours_since_creation') {
                        const updated = [...formConditions]; updated[i] = { metric: m, operator: '>', threshold: 72 }; setFormConditions(updated)
                      } else if (m === 'active_ads_in_adset') {
                        const updated = [...formConditions]; updated[i] = { metric: m, operator: '>=', threshold: 2 }; setFormConditions(updated)
                      } else {
                        updateCondition(i, 'metric', m)
                      }
                    }} className="px-2 py-1.5 border border-gray-200 rounded text-sm bg-white">
                      {metrics.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>

                    {!isAge && !isCountMetric && (
                      <select value={cond.days ?? 7} onChange={(e) => updateCondition(i, 'days', parseInt(e.target.value))} className="px-2 py-1.5 border border-gray-200 rounded text-sm bg-white">
                        {PERIODS.map(p => <option key={p.value} value={p.days}>{p.label}</option>)}
                      </select>
                    )}

                    {/* Operator */}
                    <select value={cond.operator} onChange={(e) => updateCondition(i, 'operator', e.target.value)} className="px-2 py-1.5 border border-gray-200 rounded text-sm w-20 bg-white">
                      {OPERATORS.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>

                    {/* Right side */}
                    {(isAge || isCountMetric) ? (
                      <>
                        <input type="number" value={cond.threshold ?? (isAge ? 72 : 2)} onChange={(e) => updateCondition(i, 'threshold', parseFloat(e.target.value) || 0)} className="w-20 px-2 py-1.5 border border-gray-200 rounded text-sm bg-white" />
                        <span className="text-xs text-gray-400">{isAge ? 'hours' : 'ads'}</span>
                      </>
                    ) : isCrossPeriod ? (
                      <>
                        <span className="text-xs text-gray-400">x</span>
                        <select value={cond.compare_metric} onChange={(e) => updateCondition(i, 'compare_metric', e.target.value)} className="px-2 py-1.5 border border-gray-200 rounded text-sm bg-white">
                          {BASE_METRICS.filter(m => m !== 'hours_since_creation').map(m => <option key={m} value={m}>{m}</option>)}
                        </select>
                        <select value={`${cond.compare_period_from}_${cond.compare_period_to}`} onChange={(e) => {
                          const p = COMPARE_PERIODS.find(cp => `${cp.from}_${cp.to}` === e.target.value)
                          if (p) { updateCondition(i, 'compare_period_from', p.from); setTimeout(() => updateCondition(i, 'compare_period_to', p.to), 0) }
                        }} className="px-2 py-1.5 border border-gray-200 rounded text-sm bg-white">
                          {COMPARE_PERIODS.map(p => <option key={p.value} value={`${p.from}_${p.to}`}>{p.label}</option>)}
                        </select>
                        <button onClick={() => { const u = [...formConditions]; u[i] = { metric: cond.metric, operator: cond.operator, threshold: 0, days: cond.days }; setFormConditions(u) }} className="text-xs text-gray-400 hover:text-red-500">switch to value</button>
                      </>
                    ) : (
                      <>
                        <input type="number" value={cond.threshold ?? 0} onChange={(e) => updateCondition(i, 'threshold', parseFloat(e.target.value) || 0)} className="w-24 px-2 py-1.5 border border-gray-200 rounded text-sm bg-white" step="any" />
                        <button onClick={() => { const u = [...formConditions]; u[i] = { ...cond, threshold: undefined, compare_metric: cond.metric, compare_period_from: 0, compare_period_to: 30 }; setFormConditions(u) }} className="text-xs text-blue-500 hover:underline">compare to period</button>
                      </>
                    )}

                    {formConditions.length > 1 && <button onClick={() => removeCondition(i)} className="text-red-400 hover:text-red-600 ml-auto"><X className="w-4 h-4" /></button>}
                  </div>
                )
              })}
              <button onClick={addCondition} className="text-xs text-blue-600 hover:underline mt-1">+ Add condition</button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Then...</label>
                <select value={formAction} onChange={(e) => setFormAction(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                  {actions.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                </select>
              </div>
              {formAction === 'adjust_budget' && (
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Budget Multiplier</label>
                  <input type="number" value={formBudgetMultiplier} onChange={(e) => setFormBudgetMultiplier(parseFloat(e.target.value) || 0.5)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" step="0.1" min="0.1" max="5" />
                  <p className="text-xs text-gray-400 mt-1">0.5 = reduce 50%, 1.5 = increase 50%</p>
                </div>
              )}
            </div>

            <button onClick={handleSubmit} disabled={!formName || formConditions.length === 0} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {isEditing ? 'Save Changes' : 'Create Rule'}
            </button>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-500">Loading rules...</div>
        ) : rules.length === 0 ? (
          <div className="p-8 text-center text-gray-400">No automation rules yet. Create one to get started.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left py-3 px-4 text-gray-500 font-medium">Rule</th>
                  <th className="text-left py-3 px-4 text-gray-500 font-medium">Level</th>
                  <th className="text-left py-3 px-4 text-gray-500 font-medium">Conditions</th>
                  <th className="text-left py-3 px-4 text-gray-500 font-medium">Action</th>
                  <th className="text-center py-3 px-4 text-gray-500 font-medium">Status</th>
                  <th className="text-left py-3 px-4 text-gray-500 font-medium">Last Run</th>
                  <th className="text-center py-3 px-4 text-gray-500 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-3 px-4">
                      <p className="font-medium text-gray-900">{rule.name}</p>
                      <p className="text-xs text-gray-400">{rule.platform}</p>
                    </td>
                    <td className="py-3 px-4">
                      <span className={`text-xs px-2 py-1 rounded font-medium ${
                        rule.entity_level === 'ad' ? 'bg-purple-100 text-purple-700' :
                        rule.entity_level === 'ad_set' ? 'bg-indigo-100 text-indigo-700' :
                        'bg-gray-100 text-gray-700'
                      }`}>
                        {entityLevelLabel(rule.entity_level)}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-xs text-gray-600 max-w-xs">{conditionSummary(rule.conditions)}</td>
                    <td className="py-3 px-4">
                      <span className="text-xs px-2 py-1 rounded bg-gray-100 text-gray-700">{rule.action}</span>
                    </td>
                    <td className="py-3 px-4 text-center">
                      <button onClick={() => toggleActive(rule)} className={`text-xs px-3 py-1 rounded-full font-medium ${rule.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                        {rule.is_active ? 'Active' : 'Inactive'}
                      </button>
                    </td>
                    <td className="py-3 px-4 text-xs text-gray-500">
                      {rule.last_evaluated_at ? new Date(rule.last_evaluated_at).toLocaleString() : 'Never'}
                    </td>
                    <td className="py-3 px-4 text-center">
                      <div className="flex items-center justify-center gap-2">
                        <button onClick={() => evaluateRule(rule.id)} title="Run now" className="p-1.5 rounded hover:bg-blue-50 text-blue-600"><Play className="w-4 h-4" /></button>
                        <button onClick={() => startEdit(rule)} title="Edit" className="p-1.5 rounded hover:bg-amber-50 text-amber-600"><Pencil className="w-4 h-4" /></button>
                        <button onClick={() => router.push(`/logs?rule_id=${rule.id}&rule_name=${encodeURIComponent(rule.name)}`)} title="View Logs" className="p-1.5 rounded hover:bg-purple-50 text-purple-600"><FileText className="w-4 h-4" /></button>
                        <button onClick={() => deleteRule(rule.id)} title="Delete" className="p-1.5 rounded hover:bg-red-50 text-red-500"><Trash2 className="w-4 h-4" /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
