'use client'

import { useEffect, useState } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/**
 * Per-branch Raise/Cut budget limits editor. Lives on /accounts.
 *
 * Controls 4 fields on AdAccount:
 *   - raise_pct (0..1]   — multiplier applied to current_budget for Raise
 *   - cut_pct   (0..1)   — multiplier applied to current_budget for Cut
 *   - max_raise_per_click_abs (NUMERIC | null)  — absolute cap in account currency
 *   - max_cut_per_click_abs   (NUMERIC | null)  — same, for cut direction
 *
 * UX rules:
 *   - %fields shown as 0-100 integer to user; converted to 0-1 on save.
 *   - Caps: empty input = NULL (no cap, legacy behavior). 0 also clears.
 *   - Save button disabled if no field changed.
 *   - On successful save, calls onSaved() so parent can refresh accounts list.
 */

interface BudgetLimits {
  account_id: string
  account_name?: string
  currency: string
  raise_pct: number | null
  cut_pct: number | null
  max_raise_per_click_abs: number | null
  max_cut_per_click_abs: number | null
}

interface Props {
  accountId: string
  currency: string
  onSaved?: () => void
}

export default function BudgetLimitsEditor({ accountId, currency, onSaved }: Props) {
  const [loading, setLoading] = useState(true)
  const [limits, setLimits] = useState<BudgetLimits | null>(null)

  // Form state — strings so empty input maps to null cleanly.
  const [raisePctStr, setRaisePctStr] = useState('')
  const [cutPctStr, setCutPctStr] = useState('')
  const [maxRaiseStr, setMaxRaiseStr] = useState('')
  const [maxCutStr, setMaxCutStr] = useState('')

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [savedFlash, setSavedFlash] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts/${accountId}/budget-limits`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          const x: BudgetLimits = d.data
          setLimits(x)
          setRaisePctStr(x.raise_pct != null ? Math.round(x.raise_pct * 100).toString() : '')
          setCutPctStr(x.cut_pct != null ? Math.round(x.cut_pct * 100).toString() : '')
          setMaxRaiseStr(x.max_raise_per_click_abs != null ? x.max_raise_per_click_abs.toString() : '')
          setMaxCutStr(x.max_cut_per_click_abs != null ? x.max_cut_per_click_abs.toString() : '')
        } else {
          setError(d.error || 'Failed to load limits')
        }
      })
      .catch(() => setError('Network error'))
      .finally(() => setLoading(false))
  }, [accountId])

  const parsePct = (s: string): number | null => {
    if (!s.trim()) return null
    const n = Number(s)
    if (!Number.isFinite(n)) return null
    return n / 100  // user types 25 → 0.25
  }
  const parseAbs = (s: string): number | null => {
    if (!s.trim()) return null
    const n = Number(s)
    if (!Number.isFinite(n) || n <= 0) return null
    return n
  }

  const hasChanges = (): boolean => {
    if (!limits) return false
    return (
      parsePct(raisePctStr) !== limits.raise_pct ||
      parsePct(cutPctStr) !== limits.cut_pct ||
      parseAbs(maxRaiseStr) !== limits.max_raise_per_click_abs ||
      parseAbs(maxCutStr) !== limits.max_cut_per_click_abs
    )
  }

  const handleSave = async () => {
    setError('')
    setSaving(true)
    try {
      // Send ALL 4 fields explicitly so clearing (empty → null) works via
      // backend's `if "field" in fields` exclude_unset check.
      const body: Record<string, number | null> = {}
      const rp = parsePct(raisePctStr)
      const cp = parsePct(cutPctStr)
      const mr = parseAbs(maxRaiseStr)
      const mc = parseAbs(maxCutStr)
      // Only send fields that have a value to set; empty pct keeps existing value
      // (server-side fallback to LEGACY_*_PCT applies if column was NULL, but
      // we don't allow NULLing pct via UI — that would be ambiguous).
      if (rp !== null) body.raise_pct = rp
      if (cp !== null) body.cut_pct = cp
      // Absolute caps: send explicit 0 to clear, send number to set.
      body.max_raise_per_click_abs = mr === null ? 0 : mr
      body.max_cut_per_click_abs = mc === null ? 0 : mc

      const r = await fetch(`${API_BASE}/api/accounts/${accountId}/budget-limits`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await r.json()
      if (!d.success) {
        setError(d.error || 'Save failed')
      } else {
        setLimits(d.data)
        setSavedFlash(true)
        setTimeout(() => setSavedFlash(false), 2000)
        onSaved?.()
      }
    } catch {
      setError('Network error')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return <div className="text-xs text-gray-400 px-4 py-3">Loading limits…</div>
  }

  // Render the example so the user understands what the cap does.
  const previewRaise = (() => {
    const pct = parsePct(raisePctStr) ?? 0.25
    const cap = parseAbs(maxRaiseStr)
    const example = 1000  // arbitrary preview budget
    const delta = example * pct
    const clamped = cap != null ? Math.min(delta, cap) : delta
    return { delta, clamped, capped: cap != null && delta > cap }
  })()

  const previewCut = (() => {
    const pct = parsePct(cutPctStr) ?? 0.50
    const cap = parseAbs(maxCutStr)
    const example = 1000
    const delta = example * pct
    const clamped = cap != null ? Math.min(delta, cap) : delta
    return { delta, clamped, capped: cap != null && delta > cap }
  })()

  return (
    <div className="border-t border-gray-200 bg-gray-50 px-5 py-4 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-gray-800">
          Budget mutation limits
          <span className="ml-2 text-xs font-normal text-gray-500">
            controls the Raise/Cut buttons on Action Needed
          </span>
        </h4>
        {savedFlash && (
          <span className="text-xs text-green-700 bg-green-50 px-2 py-0.5 rounded">Saved</span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Raise % */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">
            Raise step (% of current budget)
          </label>
          <div className="relative">
            <input
              type="number"
              min={1} max={100} step={1}
              value={raisePctStr}
              onChange={e => setRaisePctStr(e.target.value)}
              placeholder="25"
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm pr-7"
            />
            <span className="absolute right-2 top-1.5 text-xs text-gray-400">%</span>
          </div>
        </div>

        {/* Cut % */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">
            Cut step (% of current budget)
          </label>
          <div className="relative">
            <input
              type="number"
              min={1} max={99} step={1}
              value={cutPctStr}
              onChange={e => setCutPctStr(e.target.value)}
              placeholder="50"
              className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm pr-7"
            />
            <span className="absolute right-2 top-1.5 text-xs text-gray-400">%</span>
          </div>
        </div>

        {/* Max raise abs */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">
            Max raise per click ({currency}) <span className="text-gray-400">— empty = no cap</span>
          </label>
          <input
            type="number"
            min={0} step={1}
            value={maxRaiseStr}
            onChange={e => setMaxRaiseStr(e.target.value)}
            placeholder="50"
            className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
          />
        </div>

        {/* Max cut abs */}
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">
            Max cut per click ({currency}) <span className="text-gray-400">— empty = no cap</span>
          </label>
          <input
            type="number"
            min={0} step={1}
            value={maxCutStr}
            onChange={e => setMaxCutStr(e.target.value)}
            placeholder="100"
            className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
          />
        </div>
      </div>

      {/* Live preview: how the caps would behave on a 1000-unit campaign */}
      <div className="bg-white border border-gray-200 rounded p-3 text-xs space-y-1">
        <div className="font-medium text-gray-700">Preview on a hypothetical {currency} 1,000 budget:</div>
        <div className="text-gray-600">
          • Raise: +{currency} {previewRaise.clamped.toFixed(0)}{' '}
          {previewRaise.capped && (
            <span className="text-amber-700">(capped from +{currency} {previewRaise.delta.toFixed(0)})</span>
          )}
        </div>
        <div className="text-gray-600">
          • Cut: −{currency} {previewCut.clamped.toFixed(0)}{' '}
          {previewCut.capped && (
            <span className="text-amber-700">(capped from −{currency} {previewCut.delta.toFixed(0)})</span>
          )}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-700">{error}</div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">
          Defaults: <span className="font-mono">+25% raise</span> · <span className="font-mono">−50% cut</span> · no absolute cap.
          Changes audit to Activity Log.
        </p>
        <button
          onClick={handleSave}
          disabled={saving || !hasChanges()}
          className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? 'Saving…' : 'Save limits'}
        </button>
      </div>
    </div>
  )
}
