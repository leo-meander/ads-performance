'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ExternalLink } from 'lucide-react'
import InfoTag from '@/components/InfoTag'
import {
  fmtMoney,
  highlightStyles,
  pickHighlights,
  splitReasoningBullets,
  type MetricHighlight,
} from '@/lib/recHighlights'

// Mirror of backend `resolve_branch_for_account_name` (core/branches.py).
// The Country Dashboard `branches` query param expects canonical keys like
// "Taipei", but rec.context.account_name is the full name ("Meander Taipei").
function accountNameToBranchKey(name: string | undefined): string | null {
  if (!name) return null
  const lower = name.toLowerCase()
  // Order matters: "Oani (Taipei)" must be matched before bare "taipei".
  if (lower.includes('oani')) return 'Oani'
  if (lower.includes('saigon')) return 'Saigon'
  if (lower.includes('osaka')) return 'Osaka'
  if (lower.includes('1948')) return '1948'
  if (lower.includes('bread')) return 'Bread'
  if (lower.includes('meander taipei') || lower === 'taipei') return 'Taipei'
  return null
}

// Madgicx-style recommendation card. Used by /meta/recommendations and
// /google/recommendations. The compact summary always renders; clicking
// "See details" expands an inline 3-column panel (Why / Highlights /
// Settings) plus the action footer — no modal.

export type Severity = 'critical' | 'warning' | 'info'
export type Status = 'pending' | 'applied' | 'dismissed' | 'expired' | 'superseded' | 'failed'

export interface RecCommonShape {
  id: string
  rec_type: string
  severity: Severity
  status: Status
  entity_level: string
  title: string
  detector_finding: Record<string, any>
  metrics_snapshot: Record<string, any>
  ai_reasoning: string | null
  ai_confidence: number | null
  auto_applicable: boolean
  warning_text: string
  sop_reference: string | null
  applied_at: string | null
  dismissed_at: string | null
  dismiss_reason: string | null
  created_at: string
  // Pluck of related-entity fields injected by build_context_map().
  context: {
    account_name?: string
    currency?: string
    campaign_name?: string
    campaign_status?: string
    campaign_objective?: string | null
    campaign_daily_budget?: number | null
    campaign_lifetime_budget?: number | null
    // Dominant adset country at the campaign level — used to deep-link
    // campaign-level recommendations into the Country Dashboard.
    campaign_country?: string
    ad_set_name?: string
    ad_set_status?: string
    ad_set_daily_budget?: number | null
    ad_set_country?: string
    ad_group_name?: string
    ad_group_status?: string
    ad_group_daily_budget?: number | null
    ad_group_country?: string
    ad_name?: string
    ad_status?: string
    asset_group_name?: string
    asset_group_status?: string
    targeting?: {
      age_range?: string
      gender?: string
      countries?: string[]
      regions?: string[]
      cities?: string[]
    }
  }
  // Platform-specific extras the card surfaces if present.
  funnel_stage?: string | null
  targeted_country?: string | null
  campaign_type?: string | null
  // Entity ids — present on both meta and google rec payloads. Typed
  // optional here so the shared card can deep-link without forcing every
  // caller to extend the shape.
  campaign_id?: string | null
  ad_set_id?: string | null
  ad_group_id?: string | null
  ad_id?: string | null
}

const SEVERITY_BG: Record<Severity, string> = {
  critical: 'bg-red-50 border-red-200',
  warning: 'bg-amber-50 border-amber-200',
  info: 'bg-blue-50 border-blue-200',
}
const SEVERITY_RING: Record<Severity, string> = {
  critical: 'bg-red-100 text-red-700 ring-red-200',
  warning: 'bg-amber-100 text-amber-700 ring-amber-200',
  info: 'bg-blue-100 text-blue-700 ring-blue-200',
}
const SEVERITY_ICON: Record<Severity, string> = {
  critical: '!',
  warning: '!',
  info: 'i',
}
const STATUS_BADGE: Record<Status, string> = {
  pending: 'bg-gray-100 text-gray-700',
  applied: 'bg-green-100 text-green-700',
  dismissed: 'bg-gray-200 text-gray-500',
  expired: 'bg-gray-200 text-gray-500',
  superseded: 'bg-gray-200 text-gray-500',
  failed: 'bg-red-100 text-red-700',
}

function timeAgo(iso: string): string {
  const then = new Date(iso).getTime()
  if (!Number.isFinite(then)) return ''
  const diff = (Date.now() - then) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export default function RecommendationItem({
  rec,
  platform,
  onApply,
  onDismiss,
  onMarkManual,
  applyBusy,
  dismissBusy,
  manualBusy,
  defaultExpanded = false,
}: {
  rec: RecCommonShape
  platform: 'meta' | 'google'
  onApply: (id: string) => Promise<void> | void
  onDismiss: (id: string, reason: string) => Promise<void> | void
  onMarkManual?: (id: string, note: string) => Promise<void> | void
  applyBusy: boolean
  dismissBusy: boolean
  manualBusy?: boolean
  defaultExpanded?: boolean
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const [confirmWarning, setConfirmWarning] = useState(false)
  const [showDismiss, setShowDismiss] = useState(false)
  const [dismissReason, setDismissReason] = useState('')
  const [showManual, setShowManual] = useState(false)
  const [manualNote, setManualNote] = useState('')

  const ctx = rec.context || {}
  const currency = ctx.currency
  const highlights: MetricHighlight[] = pickHighlights({
    rec_type: rec.rec_type,
    detector_finding: rec.detector_finding || {},
    metrics_snapshot: rec.metrics_snapshot || {},
    currency,
  })
  const bullets = splitReasoningBullets(rec.ai_reasoning)

  const isPending = rec.status === 'pending'

  return (
    <div
      className={`rounded-lg border ${expanded ? 'border-gray-300 shadow-sm' : 'border-gray-200'} bg-white transition`}
      data-testid="rec-card"
    >
      {/* Compact summary header — always visible. */}
      <div className="flex items-start gap-4 p-4">
        <div
          className={`flex-shrink-0 inline-flex items-center justify-center w-10 h-10 rounded-full ring-1 font-bold text-lg ${SEVERITY_RING[rec.severity]}`}
          aria-hidden
        >
          {SEVERITY_ICON[rec.severity]}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`px-1.5 py-0.5 text-[10px] font-bold rounded ${SEVERITY_RING[rec.severity]} ring-0`}>
              {rec.severity.toUpperCase()}
            </span>
            <InfoTag
              code={rec.rec_type}
              kind="rec_type"
              className="text-[10px] font-mono text-gray-400"
            />
            {rec.entity_level && (
              <span className="text-[10px] font-mono text-gray-400">· {rec.entity_level}</span>
            )}
            {rec.funnel_stage && (
              <span className="text-[10px] font-semibold text-purple-700 bg-purple-50 px-1.5 py-0.5 rounded">
                {rec.funnel_stage}
              </span>
            )}
            {rec.targeted_country && (
              <span className="text-[10px] font-semibold text-sky-700 bg-sky-50 px-1.5 py-0.5 rounded">
                {rec.targeted_country}
              </span>
            )}
            {rec.campaign_type && (
              <span className="text-[10px] font-semibold text-indigo-700 bg-indigo-50 px-1.5 py-0.5 rounded">
                {rec.campaign_type}
              </span>
            )}
            {rec.auto_applicable && (
              <span className="text-[10px] font-semibold text-green-700 bg-green-50 px-1.5 py-0.5 rounded">
                AUTO-APPLY
              </span>
            )}
            <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${STATUS_BADGE[rec.status]}`}>
              {rec.status}
            </span>
          </div>

          <h3 className="text-sm font-semibold text-gray-900 leading-tight">{rec.title}</h3>

          <div className="mt-1 flex items-center gap-3 text-[11px] text-gray-500 flex-wrap">
            {ctx.account_name && (
              <span className="text-gray-700 font-medium">{ctx.account_name}</span>
            )}
            {ctx.campaign_name && (
              <span className="truncate max-w-[28rem]" title={ctx.campaign_name}>
                · {ctx.campaign_name}
              </span>
            )}
            {rec.created_at && <span>· {timeAgo(rec.created_at)}</span>}
          </div>
        </div>

        <div className="flex flex-col items-end gap-2 flex-shrink-0">
          {/* Compact highlight chip — first metric only. */}
          {highlights[0] && <CompactHighlight h={highlights[0]} />}
          <button
            onClick={() => setExpanded(v => !v)}
            className="text-xs font-semibold text-blue-600 hover:text-blue-700 px-3 py-1 rounded border border-blue-200 hover:bg-blue-50"
          >
            {expanded ? 'Hide details' : 'See details'}
          </button>
        </div>
      </div>

      {/* Expanded panel — 3 columns of Why / Highlights / Settings. */}
      {expanded && (
        <div className={`border-t ${SEVERITY_BG[rec.severity]} border-opacity-50`}>
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 p-4">
            <WhyColumn
              bullets={bullets}
              fallback={rec.ai_reasoning || 'No analysis was attached to this recommendation.'}
              sopReference={rec.sop_reference}
            />
            <HighlightsColumn highlights={highlights} />
            <SettingsColumn rec={rec} platform={platform} />
          </div>

          <div className="border-t border-gray-200 bg-white p-4 space-y-3">
            {rec.warning_text && (
              <div className="text-xs text-amber-900 bg-amber-50 border border-amber-200 rounded p-3">
                <span className="font-semibold uppercase tracking-wider text-[10px] text-amber-700 mr-2">
                  Warning
                </span>
                {rec.warning_text}
              </div>
            )}

            {!isPending && (
              <div className="text-xs text-gray-500">
                {rec.applied_at && <>Applied {timeAgo(rec.applied_at)}.</>}
                {rec.dismissed_at && (
                  <>
                    Dismissed {timeAgo(rec.dismissed_at)}
                    {rec.dismiss_reason ? ` — "${rec.dismiss_reason}"` : ''}.
                  </>
                )}
              </div>
            )}

            {isPending && (
              <div className="flex items-end justify-between gap-3 flex-wrap">
                <div className="flex-1 min-w-[16rem]">
                  {rec.auto_applicable ? (
                    <label className="flex items-start gap-2 text-xs text-gray-700 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={confirmWarning}
                        onChange={e => setConfirmWarning(e.target.checked)}
                        className="mt-0.5"
                      />
                      I have read the warning and confirm this action.
                    </label>
                  ) : (
                    <p className="text-xs text-gray-500">
                      Guidance only — apply manually in {platform === 'meta' ? 'Meta Ads Manager' : 'Google Ads UI'}, then click <span className="font-semibold">Mark as manually applied</span> to log it.
                    </p>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowDismiss(v => !v)}
                    className="px-3 py-1.5 text-xs font-medium text-gray-600 hover:text-gray-900 bg-white border border-gray-300 rounded hover:bg-gray-50"
                  >
                    Dismiss
                  </button>
                  {!rec.auto_applicable && onMarkManual && (
                    <button
                      onClick={() => setShowManual(v => !v)}
                      className="px-3 py-1.5 text-xs font-semibold text-violet-700 bg-violet-50 border border-violet-200 rounded hover:bg-violet-100"
                      title="Mark this guidance-only recommendation as already applied manually"
                    >
                      Mark as manually applied
                    </button>
                  )}
                  {rec.auto_applicable && (
                    <button
                      onClick={() => onApply(rec.id)}
                      disabled={!confirmWarning || applyBusy}
                      className="px-4 py-1.5 text-xs font-bold uppercase tracking-wider text-white rounded bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed"
                    >
                      {applyBusy ? 'Launching…' : 'Launch'}
                    </button>
                  )}
                </div>
              </div>
            )}

            {showManual && isPending && onMarkManual && (
              <div className="bg-violet-50 border border-violet-200 rounded p-3">
                <label className="block text-[10px] uppercase tracking-wider text-violet-700 font-semibold mb-1">
                  Note (optional)
                </label>
                <textarea
                  value={manualNote}
                  onChange={e => setManualNote(e.target.value)}
                  placeholder="What did you change in the platform UI?"
                  className="w-full text-sm border border-violet-200 rounded p-2 resize-none bg-white"
                  rows={2}
                />
                <div className="mt-2 flex justify-end gap-2">
                  <button
                    onClick={() => { setShowManual(false); setManualNote('') }}
                    className="px-3 py-1 text-xs text-gray-600 hover:text-gray-900"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => onMarkManual(rec.id, manualNote.trim())}
                    disabled={!!manualBusy}
                    className="px-3 py-1 text-xs font-semibold text-white bg-violet-600 rounded hover:bg-violet-700 disabled:opacity-40"
                  >
                    {manualBusy ? 'Saving…' : 'Confirm manual apply'}
                  </button>
                </div>
              </div>
            )}

            {showDismiss && isPending && (
              <div className="bg-gray-50 border border-gray-200 rounded p-3">
                <label className="block text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                  Dismiss reason
                </label>
                <textarea
                  value={dismissReason}
                  onChange={e => setDismissReason(e.target.value)}
                  placeholder="e.g. handled manually, false positive, not applicable"
                  className="w-full text-sm border border-gray-300 rounded p-2 resize-none"
                  rows={2}
                />
                <div className="mt-2 flex justify-end gap-2">
                  <button
                    onClick={() => { setShowDismiss(false); setDismissReason('') }}
                    className="px-3 py-1 text-xs text-gray-600 hover:text-gray-900"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => onDismiss(rec.id, dismissReason.trim())}
                    disabled={dismissBusy || !dismissReason.trim()}
                    className="px-3 py-1 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded hover:bg-gray-100 disabled:opacity-40"
                  >
                    {dismissBusy ? 'Dismissing…' : 'Confirm dismiss'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function CompactHighlight({ h }: { h: MetricHighlight }) {
  const s = highlightStyles(h.tone)
  return (
    <div className={`text-right rounded px-2.5 py-1 border ${s.box}`}>
      <div className={`text-[9px] uppercase tracking-wider font-semibold ${s.label}`}>
        {h.label}
      </div>
      <div className={`text-sm font-bold ${s.value}`}>{h.value}</div>
    </div>
  )
}

function WhyColumn({
  bullets,
  fallback,
  sopReference,
}: {
  bullets: string[]
  fallback: string
  sopReference: string | null
}) {
  return (
    <div className="lg:col-span-4 space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
        Why this matters
      </div>
      {bullets.length > 0 ? (
        <ul className="space-y-2">
          {bullets.map((b, i) => (
            <li
              key={i}
              className="bg-white rounded-md border border-gray-200 px-3 py-2 text-xs text-gray-800 leading-relaxed"
            >
              <span className="text-gray-400 mr-1.5">{['💡', '📊', '🎯', '🔍'][i % 4]}</span>
              {b}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-gray-700 bg-white rounded-md border border-gray-200 px-3 py-2 leading-relaxed">
          {fallback}
        </p>
      )}
      {sopReference && (
        <div className="text-[10px] text-gray-500 pl-1">
          <InfoTag code={sopReference} kind="sop_reference" />
        </div>
      )}
    </div>
  )
}

function HighlightsColumn({ highlights }: { highlights: MetricHighlight[] }) {
  return (
    <div className="lg:col-span-4 space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
        Key signals
      </div>
      <div className="grid grid-cols-2 gap-2">
        {highlights.map((h, i) => {
          const s = highlightStyles(h.tone)
          return (
            <div
              key={i}
              className={`rounded-md border p-3 ${s.box} ${highlights.length === 1 ? 'col-span-2' : ''}`}
            >
              <div className={`text-2xl font-bold leading-none ${s.value}`}>{h.value}</div>
              <div className={`text-[10px] uppercase tracking-wider font-semibold mt-2 ${s.label}`}>
                {h.label}
              </div>
              {h.caption && (
                <div className="text-[11px] text-gray-600 mt-1">{h.caption}</div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function SettingsColumn({
  rec,
  platform,
}: {
  rec: RecCommonShape
  platform: 'meta' | 'google'
}) {
  const ctx = rec.context || {}
  const currency = ctx.currency
  const setName = ctx.ad_set_name || ctx.ad_group_name
  const setBudget = ctx.ad_set_daily_budget ?? ctx.ad_group_daily_budget
  const setCountry = ctx.ad_set_country || ctx.ad_group_country
  const setLabel = platform === 'meta' ? 'Ad set' : 'Ad group'

  // Deep-link to the merged ADS Performance dashboard pre-filtered to this
  // rec's branch + country + 7d window so the user can see why ROAS dropped
  // (CR vs AOV vs CPC). Highlights the originating campaign in the campaign
  // breakdown.
  const branchKey = accountNameToBranchKey(ctx.account_name)
  const dashCountry = rec.targeted_country || setCountry || ctx.campaign_country || ''
  const canDeepLink = platform === 'meta' && Boolean(branchKey) && Boolean(rec.campaign_id || rec.ad_set_id || rec.ad_id)
  const dashHref = (() => {
    if (!canDeepLink || !branchKey) return null
    const params = new URLSearchParams()
    params.set('branches', branchKey)
    if (dashCountry) params.set('country', dashCountry)
    params.set('platform', 'meta')
    params.set('range', '7d')
    if (rec.funnel_stage) params.set('funnel', rec.funnel_stage)
    if (rec.campaign_id) params.set('campaign', rec.campaign_id)
    return `/?${params.toString()}`
  })()

  const rows: Array<[string, React.ReactNode]> = []
  if (ctx.account_name) rows.push(['Branch', ctx.account_name])
  if (ctx.campaign_name) {
    rows.push([
      'Campaign',
      <div className="space-y-0.5">
        <div className="font-medium text-gray-900 break-words">{ctx.campaign_name}</div>
        <div className="text-[10px] text-gray-500">
          {[ctx.campaign_objective, ctx.campaign_status].filter(Boolean).join(' · ')}
        </div>
      </div>,
    ])
  }
  if (ctx.campaign_daily_budget != null) {
    rows.push(['Campaign daily', fmtMoney(ctx.campaign_daily_budget, currency)])
  } else if (ctx.campaign_lifetime_budget != null) {
    rows.push(['Lifetime', fmtMoney(ctx.campaign_lifetime_budget, currency)])
  }
  if (setName) {
    rows.push([
      setLabel,
      <div className="space-y-0.5">
        <div className="font-medium text-gray-900 break-words">{setName}</div>
        {setBudget != null && (
          <div className="text-[10px] text-gray-500">{fmtMoney(setBudget, currency)} / day</div>
        )}
      </div>,
    ])
  }
  if (ctx.asset_group_name) {
    rows.push([
      'Asset group',
      <div className="font-medium text-gray-900 break-words">{ctx.asset_group_name}</div>,
    ])
  }
  if (ctx.ad_name) {
    rows.push([
      'Ad',
      <div className="font-medium text-gray-900 break-words">{ctx.ad_name}</div>,
    ])
  }
  if (setCountry) rows.push(['Country', setCountry])
  if (ctx.targeting) {
    const t = ctx.targeting
    const summary = [
      t.age_range && `Age ${t.age_range}`,
      t.gender,
      t.countries?.length ? `Countries: ${t.countries.join(', ')}` : null,
      t.cities?.length ? `Cities: ${t.cities.join(', ')}` : null,
      t.regions?.length ? `Regions: ${t.regions.join(', ')}` : null,
    ].filter(Boolean) as string[]
    if (summary.length) rows.push(['Targeting', <span className="text-xs">{summary.join(' · ')}</span>])
  }
  if (rec.ai_confidence != null) {
    rows.push(['AI confidence', `${Math.round(rec.ai_confidence * 100)}%`])
  }

  return (
    <div className="lg:col-span-4 space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
        Settings
      </div>
      {rows.length === 0 ? (
        <div className="bg-white rounded-md border border-gray-200 p-3 text-xs text-gray-500">
          No related entity context available.
        </div>
      ) : (
        <dl className="bg-white rounded-md border border-gray-200 divide-y divide-gray-100">
          {rows.map(([label, value], i) => (
            <div key={i} className="flex items-start gap-3 px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold w-24 flex-shrink-0 pt-0.5">
                {label}
              </dt>
              <dd className="text-xs text-gray-800 flex-1 min-w-0">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {dashHref && (
        <Link
          href={dashHref}
          className="mt-1 inline-flex w-full items-center justify-center gap-1.5 rounded border border-blue-200 bg-white px-3 py-2 text-xs font-semibold text-blue-700 hover:bg-blue-50"
          title="Open in Dashboard — see CR / AOV / CPC for this campaign"
        >
          <ExternalLink className="w-3 h-3" />
          Open in Dashboard
        </Link>
      )}
    </div>
  )
}
