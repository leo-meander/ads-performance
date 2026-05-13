'use client'

import { useEffect, useMemo, useState } from 'react'
import { Plus, Trash2, X, ChevronDown, ChevronRight } from 'lucide-react'
import { useAuth } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type Preset = {
  preset_type: string
  name: string
  description: string
  default_config: Record<string, number | string | boolean>
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

type Account = { id: string; account_name: string; platform: string }

const REVERT_LABELS: Record<string, string> = {
  none: 'Permanent',
  next_day: 'Auto-revert next day',
  on_recovery: 'Reverses when REVIVE fires',
}

// Keys we never want to surface in the threshold editor — these are internal
// engine markers, not user-tunable values.
const HIDDEN_CONFIG_KEYS = new Set(['_preset_type', '_revert_policy'])

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
  const [expanded, setExpanded] = useState<Record<string, TacticDetail | 'loading' | undefined>>({})

  // Create-tactic form state.
  const [showForm, setShowForm] = useState(false)
  const [formPreset, setFormPreset] = useState('')
  const [formName, setFormName] = useState('')
  const [formAccountId, setFormAccountId] = useState('')
  const [formOverrides, setFormOverrides] = useState<Record<string, string>>({})

  const currentPreset = useMemo(
    () => presets.find(p => p.preset_type === formPreset) || null,
    [presets, formPreset],
  )

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
    setShowForm(false)
  }

  // When the user picks a preset, seed overrides with defaults so the threshold
  // editor renders with real values instead of empty inputs.
  useEffect(() => {
    if (!currentPreset) return
    const seed: Record<string, string> = {}
    Object.entries(currentPreset.default_config).forEach(([k, v]) => {
      if (HIDDEN_CONFIG_KEYS.has(k)) return
      seed[k] = String(v)
    })
    setFormOverrides(seed)
  }, [currentPreset?.preset_type])

  const submitCreate = () => {
    if (!formPreset) return
    const overrides: Record<string, number | string | boolean> = {}
    Object.entries(formOverrides).forEach(([k, raw]) => {
      // Coerce numbers — most preset config values are numeric thresholds.
      const num = Number(raw)
      overrides[k] = !Number.isNaN(num) && raw.trim() !== '' ? num : raw
    })
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
      setExpanded(prev => ({ ...prev, [t.id]: undefined }))
      return
    }
    setExpanded(prev => ({ ...prev, [t.id]: 'loading' }))
    const res = await fetch(`${API_BASE}/api/tactics/${t.id}`, { credentials: 'include' })
    const data = await res.json()
    if (data.success) setExpanded(prev => ({ ...prev, [t.id]: data.data }))
  }

  const accountName = (id: string | null) => {
    if (!id) return 'All accounts'
    return accounts.find(a => a.id === id)?.account_name || id
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold">Tactics</h1>
          <p className="text-sm text-gray-500">
            Bundled automation strategies (SURF, Stop Loss, REVIVE, Sunsetting, Scale Winning).
            Runs daily at 17:00 UTC.
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
          No tactics yet. Create one from a preset above.
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
                const detail = expanded[t.id]
                return (
                  <>
                    <tr key={t.id} className="border-t hover:bg-gray-50">
                      <td className="px-3 py-2">
                        <button onClick={() => toggleExpand(t)} className="text-gray-500 hover:text-gray-900">
                          {detail ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
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
                    {detail === 'loading' && (
                      <tr key={`${t.id}-loading`} className="bg-gray-50 border-t">
                        <td colSpan={9} className="px-6 py-3 text-xs text-gray-500">Loading details…</td>
                      </tr>
                    )}
                    {detail && detail !== 'loading' && (
                      <tr key={`${t.id}-detail`} className="bg-gray-50 border-t">
                        <td colSpan={9} className="px-6 py-3 text-xs">
                          <div className="grid grid-cols-2 gap-6">
                            <div>
                              <div className="font-medium text-gray-600 mb-1">Config</div>
                              <pre className="bg-white border rounded p-2 overflow-x-auto">
{JSON.stringify(
  Object.fromEntries(
    Object.entries(detail.config || {}).filter(([k]) => !HIDDEN_CONFIG_KEYS.has(k)),
  ),
  null, 2,
)}
                              </pre>
                            </div>
                            <div>
                              <div className="font-medium text-gray-600 mb-1">Linked Rules ({detail.rules?.length || 0})</div>
                              <ul className="space-y-1">
                                {(detail.rules || []).map(r => (
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
          <div className="bg-white rounded-lg shadow-xl w-full max-w-2xl p-6">
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

              {currentPreset && (
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
