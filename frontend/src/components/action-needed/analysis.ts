// Weekly Report analysis layer — pure, deterministic functions that turn the
// conversion funnel + per-campaign rows + the Activity Log into a concrete
// "what's working / where we lose people / what to do next" verdict.
//
// Two data sources, both period-over-period (change fields are FRACTIONS,
// 0.334 = +33.4%):
//  - /api/dashboard/funnel        → the 6-step conversion funnel
//    (Impression → Clicks → Search → Add to cart → Checkout → Booking) with
//    per-step drop-off + WoW drop-off change. This answers "which funnel
//    stage is leaking".
//  - /api/dashboard/country/campaigns → per-campaign spend/ROAS/CTR/CR/CPC.
//    Per campaign we only see Impression→Click (CTR) and click→booking (CR),
//    so per-campaign diagnosis stays coarse and defers funnel-step detail to
//    the funnel section.

import type { CampaignRow } from '@/components/dashboard/CampaignBreakdownTable'
import type { ChangeLogItem } from '@/components/dashboard/activity/ActivityLogPanel'

export type Verdict = 'winner' | 'watch' | 'loser'
export type Severity = 'high' | 'medium' | 'low'
export type Money = (n: number) => string

export type FunnelStep = {
  key: string
  label: string
  value: number
  change: number | null
  drop_off: number | null
  drop_off_change: number | null
}

export type FunnelDiagnosis = {
  transition: string
  stepKey: string
  dropOff: number
  dropOffChange: number | null
  worsening: boolean
  severity: Severity
  reason: string
  fixes: string[]
}

export type CampaignInsight = {
  row: CampaignRow
  verdict: Verdict
  /** Share of total spend in the window, 0..1 — used for materiality ranking. */
  spendShare: number
  /** Money lost while ROAS < 1 (spend × (1 − roas)); 0 for profitable rows. */
  bleed: number
  /** Short tag for where this campaign leaks, e.g. "Impression → Click". */
  leakLabel: string | null
  /** Plain-English reason it's under-performing (with real numbers). */
  reason: string | null
  recommendations: string[]
  /** The single concrete next step (feeds the Next Actions list). */
  action: string | null
  severity: Severity
  activity: ChangeLogItem[]
  /** Buttons offered for this item on the Action Needed page. */
  applyOptions: ApplyOption[]
}

// What the user can do with an item. 'auto' actions hit
// /api/action-needed/apply and mutate the live Meta campaign; 'manual' hits
// /mark-done and only records the decision to the Activity Log.
export type ApplyAction = 'pause_campaign' | 'cut_budget' | 'raise_budget'
export type ApplyOption =
  | { kind: 'auto'; action: ApplyAction; label: string }
  | { kind: 'manual'; label: string }

export type NextAction = { severity: Severity; text: string; campaign?: string }

// Surface a loser/winner in the report only when it moves the needle.
export const MIN_SPEND_SHARE = 0.02

const pct = (v: number | null | undefined) => (v == null ? 0 : Math.round(v * 100))
const pctAbs = (v: number | null | undefined) => (v == null ? 0 : Math.round(Math.abs(v) * 100))
const num = (n: number) => n.toLocaleString('en-US')

export function verdictOf(row: CampaignRow): Verdict {
  if (row.roas >= 1.5) return 'winner'
  if (row.roas >= 1.0) return 'watch'
  return 'loser'
}

// ---------------------------------------------------------------------------
// Conversion funnel diagnosis (Impression → … → Booking)
// ---------------------------------------------------------------------------

// Each entry is keyed by the step you LAND on; the leak is the transition into
// it from the previous step.
const STEP_FIX: Record<string, { what: string; fixes: string[] }> = {
  clicks: {
    what: "people see the ad but don't click",
    fixes: [
      'Refresh the ad creative/hook and tighten targeting — this is an ad-relevance problem, not a landing-page one.',
      'Pause the audiences/placements with the lowest CTR.',
    ],
  },
  searches: {
    what: 'they click the ad but leave before browsing rooms',
    fixes: [
      'Check landing-page load speed (mobile first) and that the ad → landing-page message matches.',
      'Send them to a relevant room/offer page, not a generic homepage.',
    ],
  },
  add_to_cart: {
    what: "they browse but don't select a room",
    fixes: [
      'Check availability and rates for the searched dates — sold-out or overpriced kills this step.',
      'Improve room photos/descriptions and make the "select room" CTA obvious.',
    ],
  },
  checkouts: {
    what: 'they pick a room but bail before starting checkout',
    fixes: [
      'Hunt for price shock — taxes/fees/deposit appearing only here. Show all-in pricing earlier.',
      'Test the cart → checkout step on mobile for bugs; add trust signals (free cancellation, secure payment).',
    ],
  },
  bookings: {
    what: "they start checkout but don't finish paying",
    fixes: [
      'Check payment methods and for errors on the final step (card declines, form validation).',
      'Cut required fields and confirm price/availability does not change at the last step.',
    ],
  },
}

/**
 * Pick the funnel transition that's leaking worst. Priority: the step whose
 * drop-off worsened most week-over-week (a NEW leak). If nothing worsened,
 * fall back to the lower-funnel step with the highest standing drop-off (top-
 * funnel drop-off is naturally huge, so we don't flag it).
 */
export function diagnoseConversionFunnel(steps: FunnelStep[]): FunnelDiagnosis | null {
  if (!steps || steps.length < 2) return null
  const cands = steps.filter((s) => s.drop_off != null)
  if (cands.length === 0) return null

  const worsened = cands
    .filter((s) => (s.drop_off_change ?? 0) > 0.05)
    .sort((a, b) => (b.drop_off_change ?? 0) - (a.drop_off_change ?? 0))

  const lowerFunnel = ['add_to_cart', 'checkouts', 'bookings']
  const pick =
    worsened[0] ||
    [...cands].filter((s) => lowerFunnel.includes(s.key)).sort((a, b) => (b.drop_off ?? 0) - (a.drop_off ?? 0))[0] ||
    [...cands].sort((a, b) => (b.drop_off ?? 0) - (a.drop_off ?? 0))[0]

  const idx = steps.findIndex((s) => s.key === pick.key)
  const from = steps[idx - 1]
  const transition = `${from ? from.label : '?'} → ${pick.label}`
  const meta = STEP_FIX[pick.key] || { what: 'users drop off here', fixes: ['Investigate this step in analytics.'] }
  const doc = pick.drop_off_change
  const dOff = pick.drop_off ?? 0
  const worsening = doc != null && doc > 0
  const severity: Severity = doc != null && doc >= 0.3 ? 'high' : doc != null && doc >= 0.1 ? 'medium' : 'low'

  const reason = worsening
    ? `Biggest leak this week: ${transition}. ${(dOff * 100).toFixed(0)}% drop off here, and it worsened ${pct(doc)}% vs last week — ${meta.what}.`
    : `Biggest standing leak: ${transition} — ${(dOff * 100).toFixed(0)}% drop off here (${meta.what}). No major week-over-week shift.`

  return { transition, stepKey: pick.key, dropOff: dOff, dropOffChange: doc ?? null, worsening, severity, reason, fixes: meta.fixes }
}

// ---------------------------------------------------------------------------
// Per-campaign diagnosis (concrete, with real numbers)
// ---------------------------------------------------------------------------

type Core = {
  leakLabel: string | null
  reason: string | null
  recommendations: string[]
  action: string | null
  severity: Severity
}

function campaignCore(row: CampaignRow, verdict: Verdict, fmt: Money): Core {
  const name = row.campaign_name
  const stage = row.funnel_stage
  const isTOF = stage === 'TOF'
  const cpcUp = pctAbs(row.cpc_change)
  const cpcSpiked = (row.cpc_change ?? 0) >= 1.0

  if (verdict === 'winner') {
    const recs = [`ROAS ${row.roas.toFixed(2)}x is profitable — scale daily budget 20–30% in steps and re-check CPA in 3 days.`]
    if ((row.roas_change ?? 0) > 0.1) recs.push('Trending up — duplicate to similar audiences/keywords to widen reach.')
    return { leakLabel: null, reason: null, recommendations: recs, action: null, severity: 'low' }
  }

  // Real traffic, zero bookings → tracking / landing, not bidding.
  if (row.conversions === 0 && row.clicks >= 30) {
    const reason = isTOF
      ? `${num(row.clicks)} clicks, 0 bookings. It's a cold/TOF campaign so last-click under-reports — but zero is still a red flag.`
      : `${num(row.clicks)} clicks, 0 bookings — warm/${stage ?? 'mid'} traffic that never converts is almost always broken tracking or a wrong landing/geo, not bidding.`
    const recommendations = [
      `Verify the conversion tag fires on this campaign's landing page — ${num(row.clicks)} clicks with 0 bookings usually means tracking is broken.`,
      'Confirm the landing page matches the ad (right city / room / language) and actually loads.',
      isTOF
        ? 'If tracking is fine, judge this TOF campaign by assisted conversions, not last-click ROAS.'
        : 'If tracking checks out and it still gets 0 bookings, pause it.',
    ]
    const action = `Fix tracking/landing for ${name} — ${num(row.clicks)} clicks → 0 bookings is a tracking or landing failure, not a budget one. Don't scale until it records a booking.`
    return { leakLabel: 'Post-click · 0 bookings', reason, recommendations, action, severity: 'high' }
  }

  // Low CTR → Impression → Click leak (creative / targeting).
  if (row.ctr > 0 && row.ctr < 1) {
    const reason = `CTR is only ${row.ctr.toFixed(2)}% — losing people at Impression → Click; the ad isn't earning the click (${fmt(row.spend)} spent).`
    const recommendations = [
      `Refresh the creative/hook — CTR ${row.ctr.toFixed(2)}% is below 1%.`,
      'Tighten or swap the audience; broad/irrelevant targeting drags CTR down.',
    ]
    const action = `Refresh creative & targeting on ${name} — CTR ${row.ctr.toFixed(2)}% (below 1%) is bleeding the Impression → Click step.`
    return { leakLabel: 'Impression → Click', reason, recommendations, action, severity: 'medium' }
  }

  const cpaTxt = row.cpa ? fmt(Math.round(row.cpa)) : '—'
  const aovTxt = row.aov ? fmt(Math.round(row.aov)) : '—'
  const cpcTxt = row.cpc ? fmt(Math.round(row.cpc)) : '—'

  // Converts, but CPC blew up.
  if (cpcSpiked || cpcUp >= 25) {
    const reason = `Converts, but CPC rose ${cpcUp}% to ${cpcTxt} — paying too much per click dragged ROAS to ${row.roas.toFixed(2)}x.`
    const recommendations = [
      `Cap bids and cut the priciest keywords/placements — CPC is up ${cpcUp}%.`,
      'Check for new competitors/seasonality on these terms; refresh creative to raise relevance and lower CPC.',
    ]
    const action = `Rein in CPC on ${name} — up ${cpcUp}% to ${cpcTxt}, ROAS now ${row.roas.toFixed(2)}x. Cap bids and drop the most expensive keywords/placements.`
    return { leakLabel: 'Click cost · CPC', reason, recommendations, action, severity: cpcSpiked ? 'high' : 'medium' }
  }

  // Converts but the math doesn't work.
  const reason = `Converts but unprofitable: ROAS ${row.roas.toFixed(2)}x — ${cpaTxt} cost per booking vs ${aovTxt} booking value.`
  const recommendations = [
    verdict === 'loser'
      ? 'Cut daily budget ~50% now; if ROAS stays under 1x for 3 more days, pause and move the spend to a top performer.'
      : `Hold steady and watch — ROAS ${row.roas.toFixed(2)}x is thin; don't scale until it clears 1.5x.`,
    'Either lower cost per booking (tighter targeting) or lift AOV (longer stays / room upsells).',
  ]
  const action =
    verdict === 'loser'
      ? `Cut ${name} budget ~50% — ROAS ${row.roas.toFixed(2)}x is below break-even (${cpaTxt}/booking vs ${aovTxt} value). Pause in 3 days if it doesn't recover.`
      : `Watch ${name} — ROAS ${row.roas.toFixed(2)}x is marginal; hold budget, don't scale yet.`
  return { leakLabel: 'Profitability', reason, recommendations, action, severity: verdict === 'loser' ? 'medium' : 'low' }
}

/**
 * Activity Log entries that plausibly explain a campaign's swing: exact
 * campaign matches first, else account-level changes (tracking, budget) on the
 * same branch + platform.
 */
export function correlateActivity(row: CampaignRow, log: ChangeLogItem[]): ChangeLogItem[] {
  const byCampaign = log.filter((it) => it.campaign_id && it.campaign_id === row.campaign_id)
  if (byCampaign.length > 0) return byCampaign
  return log.filter(
    (it) =>
      it.campaign_id == null &&
      it.platform === row.platform &&
      it.account_name != null &&
      it.account_name === row.account_name,
  )
}

/**
 * Buttons for an item. Auto-apply (pause / budget) is Meta-only — Google/TikTok
 * and human tasks fall back to "Mark as done" (log only).
 */
function applyOptionsFor(row: CampaignRow, verdict: Verdict): ApplyOption[] {
  const isMeta = (row.platform || '').toLowerCase() === 'meta'
  const opts: ApplyOption[] = []
  if (verdict === 'winner') {
    if (isMeta) opts.push({ kind: 'auto', action: 'raise_budget', label: 'Raise budget 25%' })
  } else if (isMeta) {
    opts.push({ kind: 'auto', action: 'pause_campaign', label: 'Pause campaign' })
    opts.push({ kind: 'auto', action: 'cut_budget', label: 'Cut budget 50%' })
  }
  opts.push({ kind: 'manual', label: 'Mark as done' })
  return opts
}

export function buildInsights(rows: CampaignRow[], log: ChangeLogItem[], fmt: Money): CampaignInsight[] {
  const totalSpend = rows.reduce((s, r) => s + (r.spend || 0), 0) || 1
  return rows.map((row) => {
    const verdict = verdictOf(row)
    const core = campaignCore(row, verdict, fmt)
    return {
      row,
      verdict,
      spendShare: (row.spend || 0) / totalSpend,
      bleed: row.roas < 1 ? (row.spend || 0) * (1 - row.roas) : 0,
      leakLabel: core.leakLabel,
      reason: core.reason,
      recommendations: core.recommendations,
      action: core.action,
      severity: core.severity,
      activity: correlateActivity(row, log),
      applyOptions: applyOptionsFor(row, verdict),
    }
  })
}

/** Prioritized to-do list: plug the funnel leak, stop the bleed, scale winners. */
export function buildNextActions(insights: CampaignInsight[], funnelDiag: FunnelDiagnosis | null): NextAction[] {
  const actions: NextAction[] = []

  // 1. The site-wide conversion-funnel leak comes first — it caps every campaign.
  if (funnelDiag && funnelDiag.severity !== 'low') {
    actions.push({
      severity: funnelDiag.severity,
      text: `Plug the ${funnelDiag.transition} leak (${(funnelDiag.dropOff * 100).toFixed(0)}% drop-off${
        funnelDiag.worsening ? `, +${pct(funnelDiag.dropOffChange)}% WoW` : ''
      }) — ${funnelDiag.fixes[0]}`,
    })
  }

  // 2. Biggest money-losing campaigns, each with its concrete action.
  const losers = insights
    .filter((i) => i.verdict === 'loser' && i.spendShare >= MIN_SPEND_SHARE && i.action)
    .sort((a, b) => b.bleed - a.bleed)
  for (const i of losers.slice(0, 5)) {
    actions.push({ severity: i.severity, campaign: i.row.campaign_name, text: i.action as string })
  }

  // 3. Winners worth scaling (high ROAS, small budget share).
  const scale = insights
    .filter((i) => i.verdict === 'winner' && i.row.roas >= 3 && i.spendShare < 0.05)
    .sort((a, b) => b.row.roas - a.row.roas)
  for (const i of scale.slice(0, 3)) {
    actions.push({
      severity: 'medium',
      campaign: i.row.campaign_name,
      text: `Scale ${i.row.campaign_name} — ROAS ${i.row.roas.toFixed(2)}x on only ${(i.spendShare * 100).toFixed(1)}% of budget. Raise daily budget ~50% and re-check CPA in 3 days.`,
    })
  }

  // 4. Tracking change that coincides with a 0-booking campaign → top priority.
  const trackingFlag = insights.find(
    (i) =>
      i.severity === 'high' &&
      (i.leakLabel?.startsWith('Post-click') ?? false) &&
      i.activity.some((a) => a.category === 'tracking_integrity'),
  )
  if (trackingFlag) {
    actions.unshift({
      severity: 'high',
      campaign: trackingFlag.row.campaign_name,
      text: 'Activity Log shows a tracking change right when bookings went to zero — verify the pixel/conversion before anything else.',
    })
  }

  return actions
}
