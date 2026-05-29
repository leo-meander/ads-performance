'use client'

import { useEffect, useState } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/**
 * SurfRunsPanel — surfaces today's SURF intraday activity for a single tactic.
 *
 * Renders inside the tactic detail modal when preset_type === 'surf_intraday_campaign'.
 * Fetches /api/tactics/{id}/surf-runs (most recent runs with embedded checkpoints).
 *
 * Each run row shows: campaign name, origin → current budget, total raise
 * today, status pill. Expand to see the checkpoint timeline (chronological
 * sparkline of spend × ROAS with tier labels).
 */

interface SurfCheckpoint {
  id: string
  checked_at: string | null
  spend_at_check: number | null
  roas_at_check: number | null
  threshold_crossed: number | null
  tier_label: string
  multiplier_applied: number | null
  budget_before: number | null
  budget_after: number | null
  capped_by: string | null
  meta_api_called: boolean
  meta_api_success: boolean | null
  meta_api_error: string | null
}

interface SurfRun {
  id: string
  tactic_id: string
  campaign_id: string
  campaign_name: string
  run_date: string | null
  timezone: string
  origin_budget: number | null
  current_budget: number | null
  total_increase_today: number
  last_threshold_hit: number | null
  last_roas_at_check: number | null
  status: 'active' | 'reverted' | 'capped' | 'errored'
  reverted_at: string | null
  currency: string
  checkpoints: SurfCheckpoint[]
}

const STATUS_STYLE: Record<string, string> = {
  active: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  reverted: 'bg-gray-100 text-gray-600 border-gray-200',
  capped: 'bg-amber-100 text-amber-700 border-amber-200',
  errored: 'bg-red-100 text-red-700 border-red-200',
}

const TIER_STYLE: Record<string, string> = {
  tier_1: 'bg-blue-50 text-blue-700',
  tier_2: 'bg-indigo-50 text-indigo-700',
  tier_3: 'bg-violet-50 text-violet-700',
  double_check_cut: 'bg-amber-50 text-amber-700',
  no_action: 'bg-gray-50 text-gray-500',
  error: 'bg-red-50 text-red-700',
}


export default function SurfRunsPanel({ tacticId }: { tacticId: string }) {
  const [runs, setRuns] = useState<SurfRun[] | null>(null)
  const [error, setError] = useState('')
  const [expandedRun, setExpandedRun] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/tactics/${tacticId}/surf-runs?limit=10`, {
      credentials: 'include',
    })
      .then(r => r.json())
      .then(d => {
        if (d.success) setRuns(d.data.runs || [])
        else setError(d.error || 'Failed to load runs')
      })
      .catch(() => setError('Network error'))
  }, [tacticId])

  if (error) {
    return <div className="text-xs text-red-700 p-3 bg-red-50 rounded">{error}</div>
  }
  if (runs === null) {
    return <div className="text-xs text-gray-400 p-3">Loading runs…</div>
  }
  if (runs.length === 0) {
    return (
      <div className="text-xs text-gray-500 p-3 bg-gray-50 rounded border border-gray-200">
        No SURF runs yet for this tactic. The first run is created when the
        15-min cron fires on a campaign in scope.
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-semibold text-gray-800">
        SURF Runs
        <span className="ml-2 text-xs font-normal text-gray-500">
          last {runs.length} runs · most recent first
        </span>
      </h4>
      {runs.map(run => {
        const isExpanded = expandedRun === run.id
        const checkpoints = run.checkpoints || []
        const meta_writes = checkpoints.filter(cp => cp.meta_api_called && cp.meta_api_success).length
        const dry_runs = checkpoints.filter(cp => !cp.meta_api_called && cp.tier_label !== 'no_action').length
        return (
          <div key={run.id} className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              onClick={() => setExpandedRun(isExpanded ? null : run.id)}
              className="w-full px-4 py-3 flex items-center justify-between text-left hover:bg-gray-50"
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${STATUS_STYLE[run.status] || ''}`}>
                  {run.status}
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-gray-900 truncate">{run.campaign_name}</div>
                  <div className="text-xs text-gray-500">
                    {run.run_date} · {run.timezone}
                    {' · '}
                    {run.currency} {run.origin_budget?.toLocaleString()} → {run.current_budget?.toLocaleString()}
                    {run.total_increase_today > 0 && (
                      <span className="ml-1 text-emerald-700">
                        (+{run.currency} {run.total_increase_today.toLocaleString()})
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3 text-xs text-gray-500">
                <span>{checkpoints.length} ticks</span>
                {meta_writes > 0 && (
                  <span className="text-emerald-700 font-medium">{meta_writes} writes</span>
                )}
                {dry_runs > 0 && (
                  <span className="text-amber-700">{dry_runs} dry-run</span>
                )}
                <span>{isExpanded ? '▾' : '▸'}</span>
              </div>
            </button>
            {isExpanded && checkpoints.length > 0 && (
              <div className="border-t border-gray-200 bg-gray-50 px-4 py-3 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-500 border-b border-gray-200">
                      <th className="text-left py-1 font-normal">Time</th>
                      <th className="text-right py-1 font-normal">Spend</th>
                      <th className="text-right py-1 font-normal">ROAS</th>
                      <th className="text-right py-1 font-normal">Threshold</th>
                      <th className="text-left py-1 font-normal pl-2">Tier</th>
                      <th className="text-right py-1 font-normal">×Mult</th>
                      <th className="text-right py-1 font-normal">Budget</th>
                      <th className="text-left py-1 font-normal pl-2">Cap</th>
                      <th className="text-left py-1 font-normal pl-2">Meta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {checkpoints.map(cp => (
                      <tr key={cp.id} className="border-b border-gray-100 last:border-0">
                        <td className="py-1 text-gray-600">
                          {cp.checked_at?.slice(11, 16)}
                        </td>
                        <td className="py-1 text-right tabular-nums">
                          {cp.spend_at_check?.toFixed(0) ?? '—'}
                        </td>
                        <td className="py-1 text-right tabular-nums">
                          {cp.roas_at_check?.toFixed(2) ?? '—'}
                        </td>
                        <td className="py-1 text-right tabular-nums text-gray-500">
                          {cp.threshold_crossed?.toFixed(0) ?? '—'}
                        </td>
                        <td className="pl-2 py-1">
                          <span className={`px-1.5 py-0.5 rounded ${TIER_STYLE[cp.tier_label] || 'bg-gray-50'}`}>
                            {cp.tier_label}
                          </span>
                        </td>
                        <td className="py-1 text-right tabular-nums">
                          {cp.multiplier_applied?.toFixed(2) ?? '—'}
                        </td>
                        <td className="py-1 text-right tabular-nums">
                          {cp.budget_before?.toFixed(0) ?? '—'}
                          {cp.budget_after !== cp.budget_before && (
                            <>
                              {' → '}
                              <span className="font-medium">{cp.budget_after?.toFixed(0)}</span>
                            </>
                          )}
                        </td>
                        <td className="pl-2 py-1 text-amber-700">
                          {cp.capped_by ?? '—'}
                        </td>
                        <td className="pl-2 py-1">
                          {cp.meta_api_called ? (
                            cp.meta_api_success ? (
                              <span className="text-emerald-700">✓</span>
                            ) : (
                              <span className="text-red-700" title={cp.meta_api_error || ''}>✕</span>
                            )
                          ) : (
                            <span className="text-gray-400">·</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
