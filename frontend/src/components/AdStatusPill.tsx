'use client'

/**
 * Live delivery state of a Meta ad, as served by meta_ad_states.
 *
 * A row can stand for several ads (the same creative shipped into more than
 * one campaign), so the backend folds them: `active_count` of `state_count`
 * are still delivering, and `preview_url` points at a live one when there is
 * one. `state_count === 0` means nothing is known — the ad was deleted from
 * the account, renamed, or the branch has not been synced yet.
 */
export interface AdState {
  effective_status: string | null
  active_count: number
  state_count: number
  preview_url: string | null
}

// Meta's effective_status already folds in the parent ad set / campaign switch
// and the review state, so an ad can be ON while its ad set is off — worth
// naming, since that's usually why a live-looking ad stopped spending.
const STATUS_UI: Record<string, { label: string; dot: string; text: string }> = {
  ACTIVE: { label: 'Active', dot: 'bg-emerald-500', text: 'text-emerald-700' },
  PAUSED: { label: 'Paused', dot: 'bg-gray-400', text: 'text-gray-500' },
  ADSET_PAUSED: { label: 'Ad set off', dot: 'bg-gray-400', text: 'text-gray-500' },
  CAMPAIGN_PAUSED: { label: 'Campaign off', dot: 'bg-gray-400', text: 'text-gray-500' },
  ARCHIVED: { label: 'Archived', dot: 'bg-gray-300', text: 'text-gray-400' },
  DELETED: { label: 'Deleted', dot: 'bg-gray-300', text: 'text-gray-400' },
  DISAPPROVED: { label: 'Rejected', dot: 'bg-red-500', text: 'text-red-600' },
  WITH_ISSUES: { label: 'Issues', dot: 'bg-amber-500', text: 'text-amber-600' },
  PENDING_REVIEW: { label: 'In review', dot: 'bg-amber-400', text: 'text-amber-600' },
  PREAPPROVED: { label: 'Pre-approved', dot: 'bg-amber-400', text: 'text-amber-600' },
  PENDING_BILLING_INFO: { label: 'Billing', dot: 'bg-amber-500', text: 'text-amber-600' },
  IN_PROCESS: { label: 'Processing', dot: 'bg-blue-400', text: 'text-blue-600' },
}

/** One status pill. Shows "Active 2/3" when the row covers several ads. */
export default function AdStatusPill({
  state, unknownLabel = '—',
}: { state?: AdState | null; unknownLabel?: string }) {
  if (!state?.effective_status) {
    return (
      <span
        className="text-xs text-gray-300"
        title="No live ad found — deleted from the account, renamed on Meta, or not synced yet"
      >{unknownLabel}</span>
    )
  }
  const ui = STATUS_UI[state.effective_status] ||
    { label: state.effective_status, dot: 'bg-gray-400', text: 'text-gray-500' }
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs whitespace-nowrap ${ui.text}`}
      title={state.effective_status}
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${ui.dot}`} />
      {ui.label}{state.state_count > 1 && ` ${state.active_count}/${state.state_count}`}
    </span>
  )
}
