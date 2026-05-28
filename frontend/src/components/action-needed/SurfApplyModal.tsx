'use client'

import { useEffect, useState } from 'react'
import BudgetLimitsEditor from '@/app/accounts/BudgetLimitsEditor'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/**
 * SURF Apply confirmation modal — opened from /action-needed Working-well
 * and underperformer cards when the user clicks "Apply SURF" / "Apply SURF (cut)".
 *
 * Flow:
 *  1. Modal opens with current per-branch budget limits pre-loaded (via
 *     BudgetLimitsEditor, which fetches /api/accounts/{id}/budget-limits).
 *  2. User can adjust the 4 limit fields — Save persists them via PATCH and
 *     audits to change_log. Optional; user can also just click Apply with
 *     existing limits as-is.
 *  3. Live preview shows the actual delta the apply will produce, computed
 *     from the campaign's current daily_budget × pct, clamped by the
 *     absolute cap. This is the SAME math as backend _resolve_budget_change.
 *  4. "Apply SURF" button POSTs /api/action-needed/apply. On success,
 *     onApplied(message) fires and parent closes the modal.
 *
 * Cancel = pure UI close, no mutation either way.
 */

interface BudgetLimits {
  raise_pct: number | null
  cut_pct: number | null
  max_raise_per_click_abs: number | null
  max_cut_per_click_abs: number | null
}

interface Props {
  open: boolean
  onClose: () => void
  onApplied: (message: string) => void
  campaign: {
    id: string
    name: string
    account_id: string | null
    account_name: string
    daily_budget: number | null
    currency: string
  }
  action: 'raise_budget' | 'cut_budget'
}

export default function SurfApplyModal({ open, onClose, onApplied, campaign, action }: Props) {
  // Re-fetch limits whenever the modal opens — BudgetLimitsEditor manages its
  // own internal state but we also want a separate fetch for the preview math.
  const [limits, setLimits] = useState<BudgetLimits | null>(null)
  const [limitsTick, setLimitsTick] = useState(0)  // bump to force re-render after Save
  const [applying, setApplying] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !campaign.account_id) return
    fetch(`${API_BASE}/api/accounts/${campaign.account_id}/budget-limits`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setLimits(d.data) })
      .catch(() => {})
  }, [open, campaign.account_id, limitsTick])

  if (!open) return null

  const isRaise = action === 'raise_budget'
  const verb = isRaise ? 'raise' : 'cut'
  const verbCaps = isRaise ? 'Raise' : 'Cut'

  // Preview math — mirrors backend _resolve_budget_change exactly.
  // Legacy fallbacks match LEGACY_RAISE_PCT=0.25 / LEGACY_CUT_PCT=0.50.
  const current = campaign.daily_budget
  const previewBlocked = current == null || current <= 0
  let previewLine: React.ReactNode = null
  if (!previewBlocked && limits) {
    const pct = isRaise
      ? (limits.raise_pct ?? 0.25)
      : (limits.cut_pct ?? 0.50)
    const cap = isRaise
      ? limits.max_raise_per_click_abs
      : limits.max_cut_per_click_abs
    const desired = current * pct
    const clamped = cap != null && desired > cap ? cap : desired
    const wasCapped = cap != null && desired > cap
    const newBudget = isRaise ? current + clamped : Math.max(current - clamped, 1)
    previewLine = (
      <div className="bg-blue-50 border border-blue-200 rounded p-3 text-sm">
        <div className="font-medium text-blue-900 mb-1">After Apply SURF:</div>
        <div className="text-blue-800">
          {campaign.currency} {current.toLocaleString()}
          {' → '}
          <span className="font-semibold">{campaign.currency} {newBudget.toLocaleString()}</span>
          {' '}
          ({isRaise ? '+' : '−'}{campaign.currency} {clamped.toLocaleString()})
        </div>
        {wasCapped && (
          <div className="text-amber-700 text-xs mt-1">
            ⚠ Absolute cap clamped the {verb} from {campaign.currency} {desired.toLocaleString()} → {campaign.currency} {clamped.toLocaleString()}.
            Change &quot;Max {verb} per click&quot; below to allow more.
          </div>
        )}
      </div>
    )
  } else if (previewBlocked) {
    previewLine = (
      <div className="bg-amber-50 border border-amber-200 rounded p-3 text-sm text-amber-800">
        ⚠ This campaign has no daily budget at the campaign level (likely ABO — budget at ad-set).
        Apply will fail with a clearer error from Meta.
      </div>
    )
  }

  const handleApply = async () => {
    setError('')
    setApplying(true)
    try {
      const r = await fetch(`${API_BASE}/api/action-needed/apply`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ campaign_id: campaign.id, action, confirm: true }),
      })
      const d = await r.json()
      if (!d.success) {
        setError(d.error || 'Apply failed')
        return
      }
      // Success — surface the actual delta the backend computed (it carries
      // the canonical applied_cap reason).
      const params = d.data?.params || {}
      const delta = params.delta
      const appliedCap = params.applied_cap
      const msg = delta != null
        ? `SURF applied: ${verb} by ${campaign.currency} ${Math.abs(delta).toLocaleString()}${
            appliedCap ? ` (cap: ${appliedCap})` : ''
          }`
        : `SURF applied`
      onApplied(msg)
      onClose()
    } catch {
      setError('Network error')
    } finally {
      setApplying(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">
              Apply SURF {isRaise ? '' : '(cut)'} — {verbCaps} budget
            </h2>
            <p className="text-xs text-gray-500 mt-1">
              <span className="font-medium">{campaign.name}</span>
              {' · '}
              <span>{campaign.account_name}</span>
              {' · '}
              {current != null
                ? `Current: ${campaign.currency} ${current.toLocaleString()}/day`
                : 'No campaign-level daily budget'}
            </p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
            aria-label="Close"
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          {previewLine}

          {campaign.account_id ? (
            <BudgetLimitsEditor
              accountId={campaign.account_id}
              currency={campaign.currency}
              onSaved={() => setLimitsTick(t => t + 1)}
            />
          ) : (
            <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
              Campaign has no resolved account_id — cannot load branch limits.
              Re-sync the account on /accounts then retry.
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between gap-3 bg-gray-50">
          <p className="text-xs text-gray-500">
            Apply is irreversible on Meta. Result audits to Activity Log.
          </p>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              disabled={applying}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleApply}
              disabled={applying || !campaign.account_id}
              className={`px-4 py-2 text-sm font-medium text-white rounded-md disabled:opacity-50 ${
                isRaise ? 'bg-blue-600 hover:bg-blue-700' : 'bg-amber-600 hover:bg-amber-700'
              }`}
            >
              {applying ? 'Applying…' : `Apply SURF ${isRaise ? '' : '(cut)'}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
