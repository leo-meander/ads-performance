'use client'

import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface CurrencyRate {
  currency: string
  rate_to_vnd: number
  updated_by: string | null
  updated_at: string | null
}

interface DraftRow {
  currency: string
  rate_to_vnd: string
  isNew?: boolean
}

const COMMON_CURRENCIES = ['USD', 'TWD', 'JPY', 'THB', 'SGD', 'EUR', 'KRW', 'CNY', 'HKD']

export default function SettingsPage() {
  const { user } = useAuth()
  const [rates, setRates] = useState<CurrencyRate[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [newRows, setNewRows] = useState<DraftRow[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [flash, setFlash] = useState('')

  const isAdmin = !!user && (user.is_admin || user.roles?.includes('admin'))

  const load = () => {
    setLoading(true)
    fetch(`${API_BASE}/api/settings/currency-rates`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          setRates(data.data.items || [])
          setDrafts({})
          setNewRows([])
        } else {
          setError(data.error || 'Failed to load currency rates')
        }
      })
      .catch(() => setError('Network error'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  const dirty = useMemo(() => {
    const edited = Object.entries(drafts).some(([code, val]) => {
      const row = rates.find(r => r.currency === code)
      return row && String(row.rate_to_vnd) !== val
    })
    const hasNew = newRows.some(r => r.currency.trim() && r.rate_to_vnd.trim())
    return edited || hasNew
  }, [drafts, rates, newRows])

  const handleEdit = (code: string, val: string) => {
    setDrafts(d => ({ ...d, [code]: val }))
    setFlash('')
  }

  const handleNewRowChange = (idx: number, field: 'currency' | 'rate_to_vnd', val: string) => {
    setNewRows(rows => rows.map((r, i) => (i === idx ? { ...r, [field]: val } : r)))
    setFlash('')
  }

  const addNewRow = () => {
    setNewRows(rows => [...rows, { currency: '', rate_to_vnd: '', isNew: true }])
  }

  const removeNewRow = (idx: number) => {
    setNewRows(rows => rows.filter((_, i) => i !== idx))
  }

  const handleSave = async () => {
    setError('')
    setFlash('')
    setSaving(true)
    try {
      const payload: { currency: string; rate_to_vnd: number }[] = []

      for (const [code, val] of Object.entries(drafts)) {
        const row = rates.find(r => r.currency === code)
        if (!row) continue
        if (String(row.rate_to_vnd) === val) continue
        const num = Number(val)
        if (!Number.isFinite(num) || num <= 0) {
          setError(`Invalid rate for ${code}`)
          setSaving(false)
          return
        }
        payload.push({ currency: code, rate_to_vnd: num })
      }

      for (const r of newRows) {
        const code = r.currency.trim().toUpperCase()
        if (!code && !r.rate_to_vnd.trim()) continue
        if (code.length !== 3 || !/^[A-Z]{3}$/.test(code)) {
          setError(`Invalid currency code: ${r.currency}`)
          setSaving(false)
          return
        }
        const num = Number(r.rate_to_vnd)
        if (!Number.isFinite(num) || num <= 0) {
          setError(`Invalid rate for ${code}`)
          setSaving(false)
          return
        }
        payload.push({ currency: code, rate_to_vnd: num })
      }

      if (payload.length === 0) {
        setSaving(false)
        return
      }

      const res = await fetch(`${API_BASE}/api/settings/currency-rates`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ rates: payload }),
      })
      const data = await res.json()
      if (data.success) {
        setFlash(`Saved ${payload.length} rate${payload.length === 1 ? '' : 's'}`)
        load()
      } else {
        setError(data.error || 'Save failed')
      }
    } catch {
      setError('Network error')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (code: string) => {
    if (!confirm(`Remove ${code} from currency rates? Any branch using this currency will fall back to 1:1.`)) return
    try {
      const res = await fetch(`${API_BASE}/api/settings/currency-rates/${code}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      const data = await res.json()
      if (data.success) load()
      else alert(`Error: ${data.error}`)
    } catch {
      alert('Network error')
    }
  }

  const existingCodes = new Set(rates.map(r => r.currency))
  const quickAddCodes = COMMON_CURRENCIES.filter(c => !existingCodes.has(c))

  const displayRate = (code: string, rate: number) => drafts[code] ?? String(rate)

  return (
    <div className="p-8 space-y-6 max-w-5xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-500 mt-1">System-wide configuration for the Ads Platform.</p>
      </div>

      {/* Currency Conversion Rates */}
      <section className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <header className="px-6 py-4 border-b border-gray-200 flex items-start justify-between gap-4">
          <div>
            <h2 className="font-semibold text-gray-900">Currency Conversion Rates</h2>
            <p className="text-xs text-gray-500 mt-1">
              Exchange rate from each currency to <span className="font-mono font-semibold">VND</span> (base currency).
              Used to normalise spend and revenue across branches. e.g. <span className="font-mono">USD → 25,400</span> means 1 USD = 25,400 VND.
            </p>
          </div>
          {isAdmin && (
            <button
              onClick={addNewRow}
              className="px-3 py-1.5 bg-gray-900 text-white rounded-lg hover:bg-gray-700 text-xs font-medium whitespace-nowrap"
            >
              + Add Currency
            </button>
          )}
        </header>

        {error && (
          <div className="mx-6 mt-4 bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
            {error}
          </div>
        )}
        {flash && (
          <div className="mx-6 mt-4 bg-green-50 border border-green-200 rounded-lg p-3 text-sm text-green-700">
            {flash}
          </div>
        )}

        {loading ? (
          <div className="p-10 text-center text-gray-400">Loading…</div>
        ) : rates.length === 0 && newRows.length === 0 ? (
          <div className="p-10 text-center">
            <p className="text-gray-500">No currency rates yet</p>
            {isAdmin && (
              <p className="text-sm text-gray-400 mt-2">Click "+ Add Currency" to create one.</p>
            )}
          </div>
        ) : (
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3 w-32">Currency</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">Rate → VND</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">Preview</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-6 py-3">Last Updated</th>
                <th className="px-6 py-3 w-20"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {rates.map(r => {
                const val = displayRate(r.currency, r.rate_to_vnd)
                const numVal = Number(val)
                const isBase = r.currency === 'VND'
                const preview = isBase
                  ? 'base currency'
                  : Number.isFinite(numVal) && numVal > 0
                    ? `1 ${r.currency} ≈ ${numVal.toLocaleString(undefined, { maximumFractionDigits: 2 })} VND`
                    : '—'
                return (
                  <tr key={r.currency}>
                    <td className="px-6 py-3 text-sm font-mono font-semibold text-gray-900">{r.currency}</td>
                    <td className="px-6 py-3">
                      <input
                        type="number"
                        step="any"
                        min="0"
                        value={val}
                        onChange={e => handleEdit(r.currency, e.target.value)}
                        disabled={!isAdmin || isBase}
                        className="w-48 border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-gray-50 disabled:text-gray-500"
                      />
                    </td>
                    <td className="px-6 py-3 text-xs text-gray-500">
                      {isBase ? <span className="italic text-gray-400">{preview}</span> : preview}
                    </td>
                    <td className="px-6 py-3 text-xs text-gray-500">
                      {r.updated_at ? new Date(r.updated_at).toLocaleString() : '—'}
                      {r.updated_by && <div className="text-[10px] text-gray-400">by {r.updated_by}</div>}
                    </td>
                    <td className="px-6 py-3 text-right">
                      {isAdmin && !isBase && (
                        <button
                          onClick={() => handleDelete(r.currency)}
                          className="text-xs text-red-600 hover:text-red-800 font-medium"
                        >
                          Remove
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
              {newRows.map((row, idx) => (
                <tr key={`new-${idx}`} className="bg-blue-50/40">
                  <td className="px-6 py-3">
                    <input
                      type="text"
                      value={row.currency}
                      onChange={e => handleNewRowChange(idx, 'currency', e.target.value.toUpperCase())}
                      placeholder="EUR"
                      maxLength={3}
                      className="w-20 border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono uppercase focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    />
                  </td>
                  <td className="px-6 py-3">
                    <input
                      type="number"
                      step="any"
                      min="0"
                      value={row.rate_to_vnd}
                      onChange={e => handleNewRowChange(idx, 'rate_to_vnd', e.target.value)}
                      placeholder="1.0"
                      className="w-48 border border-gray-300 rounded-lg px-3 py-1.5 text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                    />
                  </td>
                  <td className="px-6 py-3 text-xs text-gray-400 italic">new</td>
                  <td className="px-6 py-3 text-xs text-gray-400 italic">not saved</td>
                  <td className="px-6 py-3 text-right">
                    <button
                      onClick={() => removeNewRow(idx)}
                      className="text-xs text-gray-500 hover:text-gray-800"
                    >
                      Cancel
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {isAdmin && quickAddCodes.length > 0 && (
          <div className="px-6 py-3 bg-gray-50 border-t border-gray-200 flex items-center gap-2 flex-wrap">
            <span className="text-xs text-gray-500 mr-1">Quick add:</span>
            {quickAddCodes.map(code => (
              <button
                key={code}
                onClick={() =>
                  setNewRows(rows => {
                    if (rows.some(r => r.currency.toUpperCase() === code)) return rows
                    return [...rows, { currency: code, rate_to_vnd: '', isNew: true }]
                  })
                }
                className="text-xs font-mono px-2 py-0.5 bg-white border border-gray-200 rounded hover:bg-gray-100"
              >
                {code}
              </button>
            ))}
          </div>
        )}

        {isAdmin && (
          <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-end gap-3">
            <button
              onClick={load}
              disabled={saving}
              className="px-4 py-2 text-sm font-medium text-gray-700 hover:text-gray-900 disabled:opacity-50"
            >
              Reset
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !dirty}
              className="px-5 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        )}

        {!isAdmin && (
          <div className="px-6 py-3 bg-amber-50 border-t border-amber-200 text-xs text-amber-700">
            Read-only. Only admins can edit currency rates.
          </div>
        )}
      </section>
    </div>
  )
}
