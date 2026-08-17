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
  drop_off_prev: number | null
  drop_off_change: number | null
}

/**
 * How strong a claim the evidence actually supports:
 *  - worsened   → this step degraded vs the active baseline beyond noise
 *  - standing   → no abnormal shift; it's just the funnel's weakest step
 *  - low_volume → too few events to judge (one event swings the rate)
 *  - healthy    → every measurable step sits at or below its baseline
 */
export type FunnelVerdict = 'worsened' | 'standing' | 'low_volume' | 'healthy'

export type FunnelDiagnosis = {
  transition: string
  stepKey: string
  dropOff: number
  dropOffChange: number | null
  worsening: boolean
  severity: Severity
  reason: string
  fixes: string[]
  kind: FunnelVerdict
  /** Delta vs the active baseline in percentage POINTS (+ = worse). */
  baselineDeltaPp: number | null
  /** What we compared against, e.g. "90-day average" / "previous 7 days". */
  baselineLabel: string
  /** Events feeding the diagnosed step, and how much 1 event moves the rate. */
  upstreamVolume: number
  swingPerEventPp: number | null
  /** Steps reporting 0 while a later step has volume → reporting gap, not a leak. */
  untrackedSteps: string[]
  /** Data-quality caveat to show next to the verdict (tracking gap / thin volume). */
  dataNote: string | null
  /** Activity Log entries in the window that can plausibly move this step. */
  activity: ChangeLogItem[]
  /** One-line "rule this out first" note built from `activity`. */
  activityNote: string | null
}

export type FunnelDiagnosisContext = {
  /** Which baseline the panel is showing. Defaults to 'prev'. */
  mode?: 'prev' | 'benchmark'
  /** 90-day average funnel (same step keys) — required for mode 'benchmark'. */
  benchmark?: FunnelStep[]
  /** Length of the selected window in days, so wording never says "week" wrongly. */
  periodDays?: number | null
  /** Activity Log entries for the same window/branch scope. */
  activity?: ChangeLogItem[]
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
// 'enroll' opts the campaign into an allowlist tactic (SURF intraday) via
// /api/tactics/enroll-campaign — continuous automation, not a one-shot Meta hit.
export type ApplyOption =
  | { kind: 'auto'; action: ApplyAction; label: string }
  | { kind: 'enroll'; preset: string; label: string }
  | { kind: 'manual'; label: string }

export type NextAction = { severity: Severity; text: string; campaign?: string }

// Surface a loser/winner in the report only when it moves the needle.
export const MIN_SPEND_SHARE = 0.02

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
//
// Root causes are grounded in hotel-booking funnel mechanics:
// - Impression→Click is a pure ad problem (creative/audience/offer/fatigue), not website.
// - Click→Search is a landing page problem (load speed, hero, message-match).
// - Search→Add to Cart is room selection (availability, pricing, presentation).
// - Add to Cart→Checkout is booking intent — users are evaluating, not "abandoning checkout".
//   This step is NOT traditional checkout abandonment. Users pick a room to see the total
//   price, then may leave to compare OTAs or check with travel companions.
// - Checkout→Booking is payment/form friction (the actual checkout experience).
const STEP_FIX: Record<string, { what: string; fixes: string[] }> = {
  clicks: {
    what: "users see the ad but don't click — this is an ad problem, not a website one",
    fixes: [
      'Refresh creative hook (first 3s of video / thumbnail) and sharpen the offer — Best Price Guarantee, Free Breakfast, Free Cancellation. This step has nothing to do with the landing page.',
      'Check audience: wrong market or no travel intent → ad fatigue or mismatched ICP. Pause lowest-CTR placements/audiences.',
    ],
  },
  // Engagement funnel (Impression → 3s View → ThruPlay → Click → Booking).
  video_3s_views: {
    what: 'the first frame does not stop the scroll — a hook problem, nothing downstream',
    fixes: [
      'Rework the opening 3 seconds: lead with motion, a face, or the payoff shot. A title card or slow establishing shot loses the viewer before the ad registers.',
      'Check placement mix — Reels/TikTok feed reward vertical, sound-on hooks. Recycled 16:9 landscape assets lose the scroll war regardless of the offer.',
    ],
  },
  video_thru_plays: {
    what: 'they started watching but left before the payoff — the middle of the video loses them',
    fixes: [
      'Move the offer/USP earlier. If the reveal sits at 0:15 in a 0:30 cut, most viewers never reach it — front-load the reason to care.',
      'Cut length and tighten pacing: fewer scenes, faster cuts, captions burned in for sound-off viewing.',
    ],
  },
  searches: {
    what: 'they clicked the ad but left before searching for rooms — landing page experience failed',
    fixes: [
      'Check load speed on mobile and that the ad message matches the landing page (e.g. an ad about "Things to do in Saigon" should not open a booking engine).',
      'Strengthen the hero: add USP, social proof, best-price guarantee, and a clear CTA — users must immediately see a reason to search for rooms.',
    ],
  },
  add_to_cart: {
    what: 'they searched dates but selected no room — offer or availability issue',
    fixes: [
      'Check availability and pricing for the searched dates — sold-out inventory or uncompetitive rates block this step most often.',
      'Improve room listing: more photos, clearer descriptions, capacity/view/breakfast callouts, and easier comparison between room types.',
    ],
  },
  checkouts: {
    what: 'they selected a room but did not tap Book Now — booking intent is low, not a checkout bug',
    fixes: [
      'This is normal hotel-booking behaviour: users pick a room to see the total price, then compare OTAs or check travel plans. Add Best Price Guarantee, Free Cancellation, and limited-availability signals to Reservation Summary to nudge them to commit.',
      'Clarify the CTA label: "Continue to Guest Details" converts better than "Book Now" (reduces the perceived commitment). Ensure no price surprises (taxes/fees) appear only at this step.',
    ],
  },
  bookings: {
    what: 'they reached the payment step but no booking was recorded — either payment/form friction or a booking that never got attributed back',
    fixes: [
      'Check the booking engine + payment gateway logs for the window (card declines, OTP timeouts, 3DS failures) and confirm the purchase event still fires — a missing conversion event looks identical to a payment failure in this chart.',
      'Then reduce friction: fewer required fields validated inline, local payment methods (QR / Apple Pay / Google Pay), and no tax/fee surprise appearing only at this step.',
    ],
  },
}

/**
 * Minimum upstream events before a drop-off deserves a verdict. Below this,
 * one event moves the rate by more than the "worsening" threshold itself, so
 * any "it worsened X%" claim is noise. Mirrors the backend gates in
 * app/services/funnel_recommendations.py.
 */
const MIN_UPSTREAM_FOR_VERDICT: Record<string, number> = {
  clicks: 1000,
  video_3s_views: 1000,
  video_thru_plays: 200,
  searches: 50,
  landing_page_views: 50,
  add_to_cart: 30,
  leads: 30,
  checkouts: 30,
  bookings: 30,
}
const DEFAULT_MIN_UPSTREAM = 30

/** Drop-off moves smaller than this (in percentage POINTS) are noise, not news. */
const WORSENED_PP = 3

const LOWER_FUNNEL = ['add_to_cart', 'checkouts', 'bookings', 'leads']

/**
 * Which Activity Log categories can plausibly move each step. Deliberately
 * narrow: a landing-page edit cannot change Impression→Click, and a pixel
 * change cannot change platform-side clicks.
 */
const UPPER_FUNNEL_CATEGORIES = [
  'ad_creation', 'ad_mutation', 'automation_rule_applied', 'recommendation_applied',
  'external_competitor', 'external_algorithm', 'external_seasonality',
]
const SITE_STEP_CATEGORIES = [
  'tracking_integrity', 'landing_page', 'ad_creation', 'ad_mutation',
  'automation_rule_applied', 'recommendation_applied', 'external_seasonality',
]
const STEP_ACTIVITY_CATEGORIES: Record<string, string[]> = {
  clicks: UPPER_FUNNEL_CATEGORIES,
  video_3s_views: UPPER_FUNNEL_CATEGORIES,
  video_thru_plays: UPPER_FUNNEL_CATEGORIES,
  searches: ['tracking_integrity', 'landing_page', 'ad_creation', 'ad_mutation', 'external_seasonality'],
  landing_page_views: ['tracking_integrity', 'landing_page', 'ad_creation', 'ad_mutation', 'external_seasonality'],
  add_to_cart: SITE_STEP_CATEGORIES,
  checkouts: SITE_STEP_CATEGORIES,
  bookings: SITE_STEP_CATEGORIES,
  leads: SITE_STEP_CATEGORIES,
}

const ACTIVITY_WHY: Record<string, string> = {
  tracking_integrity:
    'a tracking change can wipe these events out of reporting while guests keep booking — verify the pixel/conversion event before treating this as a UX leak',
  landing_page: 'a landing-page change in this window hits this step directly',
  ad_creation: 'new ads/campaigns change the traffic mix, which moves this step even when the site did not change',
  ad_mutation: 'ad/audience edits change the traffic mix feeding this step',
  automation_rule_applied: 'an automation rule moved budget, which re-mixes the traffic feeding this step',
  recommendation_applied: 'an applied recommendation moved budget/targeting, re-mixing this step',
  external_seasonality: 'a seasonality event in this window changes booking behaviour',
  external_competitor: 'competitor pressure in this window drags click-through',
  external_algorithm: 'a platform delivery/algorithm change lands in this window',
}

const shortDate = (iso: string) => {
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso.slice(0, 10) : d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
}

/**
 * Activity Log entries that could plausibly explain a move at `stepKey`,
 * tracking changes first (they fake leaks), then newest.
 */
export function correlateFunnelActivity(
  stepKey: string,
  log: ChangeLogItem[] | undefined,
  limit = 4,
): ChangeLogItem[] {
  const cats = STEP_ACTIVITY_CATEGORIES[stepKey]
  if (!cats || !log || log.length === 0) return []
  return log
    .filter((it) => cats.includes(it.category))
    .sort((a, b) => {
      const rank = (it: ChangeLogItem) => (it.category === 'tracking_integrity' ? 0 : 1)
      return rank(a) - rank(b) || (b.occurred_at || '').localeCompare(a.occurred_at || '')
    })
    .slice(0, limit)
}

function buildActivityNote(items: ChangeLogItem[], transition: string): string | null {
  if (items.length === 0) return null
  const head = items.find((i) => i.category === 'tracking_integrity') || items[0]
  const why = ACTIVITY_WHY[head.category] || 'this change lands inside the same window'
  const more = items.length > 1 ? ` (+${items.length - 1} more logged change${items.length > 2 ? 's' : ''})` : ''
  return `Activity Log — "${head.title}" on ${shortDate(head.occurred_at)}${more}: ${why}. Rule that out before calling ${transition} a site problem.`
}

function baselineClause(deltaPp: number | null, baselineLabel: string): string {
  if (deltaPp == null) return `no ${baselineLabel} to compare against`
  if (deltaPp >= WORSENED_PP) return `${deltaPp.toFixed(1)}pp worse than the ${baselineLabel}`
  if (deltaPp <= -WORSENED_PP) return `${Math.abs(deltaPp).toFixed(1)}pp better than the ${baselineLabel}`
  return `in line with the ${baselineLabel} (${deltaPp >= 0 ? '+' : ''}${deltaPp.toFixed(1)}pp)`
}

type Cand = {
  step: FunnelStep
  fromLabel: string
  upstream: number
  dropOff: number
  deltaPp: number | null
  conclusive: boolean
}

/**
 * Diagnose the conversion funnel against the baseline the panel is actually
 * showing (previous period or 90-day average), and only make a claim the
 * numbers support.
 *
 * Guard rails, in order:
 *  1. Steps reporting 0 while a later step has volume are TRACKING GAPS — their
 *     100% drop-off is excluded, never reported as a leak.
 *  2. A step needs enough upstream events to be judged; below the gate we say
 *     "not enough volume" instead of inventing a cause.
 *  3. "Worse" is measured in percentage POINTS vs the active baseline — a step
 *     that is better than the baseline is never called a worsening leak.
 *  4. Activity Log entries from the same window are attached, so a pixel edit /
 *     LP swap / new campaign mix is ruled out before blaming the funnel.
 */
export function diagnoseConversionFunnel(
  steps: FunnelStep[],
  ctx: FunnelDiagnosisContext = {},
): FunnelDiagnosis | null {
  if (!steps || steps.length < 2) return null

  const useBenchmark = ctx.mode === 'benchmark' && (ctx.benchmark?.length ?? 0) > 0
  const baselineLabel = useBenchmark
    ? '90-day average'
    : ctx.periodDays && ctx.periodDays > 0
      ? `previous ${ctx.periodDays} days`
      : 'previous period'

  // (1) Reporting gaps: 0 here but volume further down the funnel.
  const untracked = steps.filter((s, i) => s.value === 0 && steps.slice(i + 1).some((l) => l.value > 0))
  const untrackedKeys = untracked.map((s) => s.key)

  const cands: Cand[] = []
  steps.forEach((s, i) => {
    if (i === 0 || s.drop_off == null) return
    // Skip the gap step itself and the step right after it (its rate is measured
    // against a zero that isn't real).
    if (untrackedKeys.includes(s.key) || untrackedKeys.includes(steps[i - 1].key)) return
    const bm = useBenchmark ? ctx.benchmark?.find((b) => b.key === s.key) : null
    const baselineDrop = useBenchmark ? (bm?.drop_off ?? null) : s.drop_off_prev
    const upstream = steps[i - 1].value
    cands.push({
      step: s,
      fromLabel: steps[i - 1].label,
      upstream,
      dropOff: s.drop_off,
      deltaPp: baselineDrop == null ? null : (s.drop_off - baselineDrop) * 100,
      conclusive: upstream >= (MIN_UPSTREAM_FOR_VERDICT[s.key] ?? DEFAULT_MIN_UPSTREAM),
    })
  })
  if (cands.length === 0) return null

  const byDrop = (a: Cand, b: Cand) => b.dropOff - a.dropOff
  const conclusive = cands.filter((c) => c.conclusive)
  const worsened = conclusive
    .filter((c) => (c.deltaPp ?? 0) >= WORSENED_PP)
    .sort((a, b) => (b.deltaPp ?? 0) - (a.deltaPp ?? 0))
  const lowerConclusive = conclusive.filter((c) => LOWER_FUNNEL.includes(c.step.key)).sort(byDrop)
  const lowerThin = cands.filter((c) => !c.conclusive && LOWER_FUNNEL.includes(c.step.key)).sort(byDrop)

  let kind: FunnelVerdict
  let pick: Cand
  if (worsened.length > 0) {
    kind = 'worsened'
    pick = worsened[0]
  } else if (lowerThin.length > 0) {
    // Nothing degraded on solid volume, and the lower funnel is too thin to judge.
    kind = 'low_volume'
    pick = lowerThin[0]
  } else if (lowerConclusive.length > 0 && (lowerConclusive[0].deltaPp ?? 0) > -WORSENED_PP) {
    kind = 'standing'
    pick = lowerConclusive[0]
  } else if (conclusive.length > 0) {
    kind = 'healthy'
    pick = [...conclusive].sort(byDrop)[0]
  } else {
    kind = 'low_volume'
    pick = [...cands].sort(byDrop)[0]
  }

  const transition = `${pick.fromLabel} → ${pick.step.label}`
  const meta = STEP_FIX[pick.step.key] || {
    what: 'users drop off here',
    fixes: ['Investigate this step in analytics.'],
  }
  const dOff = pick.dropOff
  const dropTxt = `${(dOff * 100).toFixed(1)}%`
  const baseTxt = baselineClause(pick.deltaPp, baselineLabel)
  const swingPp = pick.upstream > 0 ? 100 / pick.upstream : null

  const activity = correlateFunnelActivity(pick.step.key, ctx.activity)
  const activityNote = buildActivityNote(activity, transition)

  const gapNote = untracked.length > 0
    ? `${untracked.map((s) => s.label).join(', ')} report${untracked.length === 1 ? 's' : ''} 0 while later steps have volume — that event isn't tracked for these campaigns, so its 100% drop-off is a reporting gap, not a leak.`
    : null
  const thinNote = kind === 'low_volume' && swingPp != null
    ? `Only ${num(pick.upstream)} at ${pick.fromLabel} → ${num(pick.step.value)} at ${pick.step.label} in this window: one event moves the rate ~${swingPp.toFixed(0)}pp.`
    : null
  const dataNote = [thinNote, gapNote].filter(Boolean).join(' ') || null

  let reason: string
  let severity: Severity
  let fixes: string[]
  if (kind === 'worsened') {
    reason = `Biggest leak in this window: ${transition}. ${dropTxt} drop off here, ${baseTxt} — ${meta.what}.`
    severity = (pick.deltaPp ?? 0) >= 10 ? 'high' : 'medium'
    fixes = meta.fixes
  } else if (kind === 'standing') {
    reason = `No step degraded vs the ${baselineLabel}. Weakest step is ${transition} at ${dropTxt} (${baseTxt}) — ${meta.what}. Treat it as a structural improvement, not an incident.`
    severity = 'low'
    fixes = meta.fixes
  } else if (kind === 'low_volume') {
    reason = `Not enough volume to diagnose. ${transition} carries the biggest lower-funnel drop-off (${dropTxt}, ${baseTxt}), but the event counts are too small to read as a leak.`
    severity = 'low'
    fixes = [
      `Widen the date range (or drop the branch/country filter) until this step clears ~30 events — right now a single event swings the rate ~${swingPp != null ? swingPp.toFixed(0) : '10'}pp.`,
      ...(gapNote
        ? [`Close the tracking gap first: ${untracked.map((s) => s.label).join(', ')} report${untracked.length === 1 ? 's' : ''} 0 events, so the funnel shape around it isn't measurable.`]
        : []),
      `If it persists at real volume: ${meta.fixes[0]}`,
    ]
  } else {
    reason = `Funnel is at its usual shape — every measurable step is at or better than the ${baselineLabel}. Worst standing drop-off is ${transition} at ${dropTxt} (${baseTxt}), which is the funnel's normal floor.`
    severity = 'low'
    fixes = [`Nothing to plug this window. If you want upside here: ${meta.fixes[0]}`]
  }

  if (activityNote) fixes = [...fixes, activityNote]

  return {
    transition,
    stepKey: pick.step.key,
    dropOff: dOff,
    dropOffChange: pick.step.drop_off_change ?? null,
    worsening: kind === 'worsened',
    severity,
    reason,
    fixes,
    kind,
    baselineDeltaPp: pick.deltaPp,
    baselineLabel,
    upstreamVolume: pick.upstream,
    swingPerEventPp: swingPp,
    untrackedSteps: untrackedKeys,
    dataNote,
    activity,
    activityNote,
  }
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
  // SURF labels — per-branch raise_pct + max_raise_per_click_abs is configured
  // inside the modal that opens on click; we no longer hardcode the percentage
  // in the label because the actual delta depends on per-branch settings.
  if (verdict === 'winner') {
    if (isMeta) {
      // One-shot manual bump (opens caps modal)...
      opts.push({ kind: 'auto', action: 'raise_budget', label: 'Apply SURF' })
      // ...or enroll into continuous intraday SURF (auto-rides budget all day).
      opts.push({ kind: 'enroll', preset: 'surf_intraday_campaign', label: 'Enroll SURF auto' })
    }
  } else if (isMeta) {
    opts.push({ kind: 'auto', action: 'pause_campaign', label: 'Pause campaign' })
    opts.push({ kind: 'auto', action: 'cut_budget', label: 'Apply SURF (cut)' })
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
  //    Only when the evidence supports it: 'low_volume' / 'healthy' verdicts are
  //    severity 'low' and never become a to-do.
  if (funnelDiag && funnelDiag.severity !== 'low') {
    const delta = funnelDiag.baselineDeltaPp
    const vs = delta != null ? `, ${delta.toFixed(1)}pp vs ${funnelDiag.baselineLabel}` : ''
    actions.push({
      severity: funnelDiag.severity,
      text: `Plug the ${funnelDiag.transition} leak (${(funnelDiag.dropOff * 100).toFixed(1)}% drop-off${vs}) — ${funnelDiag.fixes[0]}`,
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
