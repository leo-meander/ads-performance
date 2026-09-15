// Per-campaign optimisation diagnosis for the Campaign Breakdown drawer.
//
// Pure + deterministic: given one campaign row and the rows it shares the
// current view with, decide WHICH metric to fix and WHAT to do about it.
//
// The whole thing hangs off one identity — the same one printed in the table
// header — which holds exactly, no approximation:
//
//   ROAS = CTR x CR x AOV / (10 x CPM)          [CTR, CR in percent]
//
// Each of the four is a lever. Moving one to what comparable campaigns already
// achieve, holding the rest still, multiplies ROAS by a known factor, so the
// levers can be RANKED by how much ROAS each is currently costing. That
// ranking is the point of the drawer: fix this one first.
//
// Why peer-relative rather than fixed thresholds: 1.4% CTR is poor for Google
// Search and unremarkable for Meta cold traffic; a small MOF remarketing pool
// runs an expensive CPM by design. Absolute cut-offs mislabel both.
//
// What a peer is, and why the rule is strict: a campaign is only compared
// against the same DELIVERY FAMILY (Meta / Google Search / PMax — their CPMs
// differ by more than an order of magnitude) AND the same funnel stage (MOF is
// remarketing, so its CTR and CPM are structurally unlike TOF). When there are
// not enough of those in view, the lever reports `blind` instead of borrowing a
// benchmark from a group it does not belong to. A wrong benchmark produces a
// confident wrong instruction, which is worse than no instruction.

import type { CampaignRow } from './CampaignBreakdownTable'

export type LeverKey = 'cpm' | 'ctr' | 'cr' | 'aov'

/**
 * - `drag`     → materially worse than peers; this is where ROAS is leaking
 * - `par`      → in line with peers, no action implied
 * - `strength` → materially better than peers; protect it, don't "fix" it
 * - `thin`     → this campaign lacks the volume to judge the rate at all
 * - `blind`    → too few comparable campaigns to form a benchmark
 */
export type LeverStatus = 'drag' | 'par' | 'strength' | 'thin' | 'blind'

export type Lever = {
  key: LeverKey
  label: string
  /** This campaign's value (percent for ctr/cr, money for cpm/aov). */
  value: number
  /** Period-over-period change as a FRACTION (0.155 = +15.5%), or null. */
  change: number | null
  /** Median across comparable campaigns, or null when there is no benchmark. */
  peer: number | null
  status: LeverStatus
  /**
   * ROAS multiplier if this lever alone moved to the peer median. Always >1
   * (it only exists for `drag`), null otherwise. Used for ranking.
   */
  upside: number | null
  /**
   * ROAS at the peer median for this lever. Deliberately null once the implied
   * uplift passes MAX_PROJECTION — see the constant.
   */
  projectedRoas: number | null
  /** Why this lever got its status, in plain language with real numbers. */
  why: string
  /** Concrete, platform-aware things to do. Empty unless the lever is a drag. */
  fixes: string[]
}

export type PeerScope = {
  /** Name of the comparison group, e.g. "MOF Meta" — never suffixed with
   *  "campaigns"; each sentence adds that itself so it can be pluralised. */
  label: string
  /** How many campaigns are in it, excluding this one. */
  count: number
}

export type CampaignDiagnosis = {
  /** Levers ranked worst-first: the top entry is what to fix. */
  levers: Lever[]
  /** The lever to act on, or null when nothing is dragging. */
  primary: Lever | null
  peers: PeerScope
  /** One-line summary shown under the campaign name. */
  headline: string
  /**
   * Set when the row cannot be read as a performance problem at all — spend
   * with zero bookings is a tracking or landing failure and no bid change
   * fixes it. Takes over the drawer when present.
   */
  blocker: { title: string; why: string; fixes: string[] } | null
}

// --- thresholds --------------------------------------------------------------

// Below these a rate is noise: one more click swings CR by whole points, so a
// "diagnosis" would just be reading randomness back to the user.
const MIN_IMPRESSIONS = 1000
const MIN_CLICKS = 30

// Fewest comparable campaigns that can form a median. Two is genuinely thin —
// it is a midpoint, not a distribution — which is why DRAG_THRESHOLD widens
// below five peers and why the drawer always prints the peer count.
const MIN_PEERS = 2
const WIDE_SAMPLE = 5

// How far off the median a lever must be before it is worth naming. A median
// taken over a handful of campaigns is noisy, so a small sample has to clear a
// bigger gap to be called a problem.
const DRAG_NARROW_SAMPLE = 1.3
const DRAG_WIDE_SAMPLE = 1.15

/**
 * Uplift past which the arithmetic projection stops being shown as a number.
 *
 * The identity is exact, but it holds the other three levers still, and in
 * practice they trade off — looser targeting lifts CTR and usually costs CR.
 * A "fix CTR and this becomes 68x" line is arithmetically true and practically
 * a lie, so past this multiple the lever is still ranked and still explained,
 * just without a fake-precise destination attached.
 */
const MAX_PROJECTION = 3

const LEVER_LABEL: Record<LeverKey, string> = {
  cpm: 'CPM', ctr: 'CTR', cr: 'CR', aov: 'AOV',
}

/** Is this row's own volume enough to judge the given lever? */
function hasVolume(row: CampaignRow, key: LeverKey): boolean {
  switch (key) {
    case 'cpm':
    case 'ctr': return (row.impressions || 0) >= MIN_IMPRESSIONS
    case 'cr': return (row.clicks || 0) >= MIN_CLICKS
    case 'aov': return (row.conversions || 0) > 0
  }
}

function valueOf(row: CampaignRow, key: LeverKey): number {
  return key === 'cpm' ? row.cpm : key === 'ctr' ? row.ctr : key === 'cr' ? row.cr : row.aov
}

function changeOf(row: CampaignRow, key: LeverKey): number | null {
  return key === 'cpm' ? row.cpm_change
    : key === 'ctr' ? row.ctr_change
      : key === 'cr' ? row.cr_change
        : row.aov_change
}

function median(xs: number[]): number | null {
  if (xs.length === 0) return null
  const s = [...xs].sort((a, b) => a - b)
  const mid = Math.floor(s.length / 2)
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

// --- delivery family ---------------------------------------------------------
// Search buys keywords, PMax buys everything, Meta buys a feed. Their CPMs are
// not on the same scale (Search runs 20x a Meta CPM on this account), so they
// are never each other's benchmark, and their fixes have nothing in common.

type Family = 'meta' | 'search' | 'pmax' | 'other'

function familyOf(row: CampaignRow): Family {
  const plat = (row.platform || '').toLowerCase()
  if (plat === 'meta') return 'meta'
  if (plat === 'google') return /pmax|performance max/i.test(row.campaign_name) ? 'pmax' : 'search'
  return 'other'
}

const FAMILY_LABEL: Record<Family, string> = {
  meta: 'Meta', search: 'Google Search', pmax: 'PMax', other: 'other-platform',
}

function scopeLabel(row: CampaignRow): string {
  const fam = FAMILY_LABEL[familyOf(row)]
  return row.funnel_stage ? `${row.funnel_stage} ${fam}` : fam
}

/**
 * Comparable campaigns: same delivery family AND same funnel stage, with no
 * fallback to a looser group. Too few of them is reported as `blind` rather
 * than papered over with a benchmark from a different kind of campaign.
 */
function pickPeers(row: CampaignRow, rows: CampaignRow[]): { peers: CampaignRow[]; scope: PeerScope } {
  const fam = familyOf(row)
  const peers = rows.filter(
    r => r.campaign_id !== row.campaign_id
      && familyOf(r) === fam
      && r.funnel_stage === row.funnel_stage,
  )
  return { peers, scope: { label: scopeLabel(row), count: peers.length } }
}

// --- what to actually do about each lever ------------------------------------
// Split by family because the same symptom has different causes: a Meta CPM
// spike is usually audience size or frequency, a Search CPM spike is auction
// competition and Quality Score, and PMax barely exposes either.

const CPM_FIXES: Record<Family, string[]> = {
  meta: [
    'Widen the audience or add a lookalike — a small pool forces delivery into its most expensive slice.',
    'Check frequency in this window. Above ~2.5 you are re-buying the same people at a rising price; refresh the creative or expand reach.',
    'Let Advantage+ placements run. Feed-only delivery is the most contested inventory Meta sells.',
  ],
  search: [
    'Lift Quality Score before touching bids — ad relevance and landing-page experience both discount the auction price directly.',
    'Trim the expensive head terms and push budget into long-tail variants of the same intent.',
    'Open Auction Insights for this window: a new bidder on your terms shows up here before it shows up in ROAS.',
  ],
  pmax: [
    'PMax buys on asset strength — replace anything the asset report rates "Low" and add more video, which fills the cheaper inventory.',
    'Tighten the audience signals so the campaign stops exploring the priciest placements.',
  ],
  other: [
    'The auction got more expensive for this targeting — pull the bid back to the placements that actually convert.',
  ],
}

const CTR_FIXES: Record<Family, string[]> = {
  meta: [
    'Rewrite the first 1–2 seconds. The hook decides the click; the rest of the ad decides nothing if nobody stops.',
    'Swap the thumbnail / opening frame — at this CTR it is doing more work than the copy.',
    'Put the offer in the ad itself. Vague brand lines read as noise in a feed.',
  ],
  search: [
    'Feed the RSA more assets — 10+ headlines, 4 descriptions, nothing pinned — and let Google find the pairing.',
    'Close the gap between keyword and headline: the searched phrase should appear in the ad almost verbatim.',
    'Add sitelinks, callouts and structured snippets. A taller ad takes more of the result page and earns more clicks.',
  ],
  pmax: [
    'Weak CTR in PMax is an asset problem — add headlines and images, and cut the ones the asset report rates "Low".',
  ],
  other: [
    'Refresh the creative and tighten targeting — the ad is reaching people it does not speak to.',
  ],
}

const CR_FIXES: string[] = [
  'Open the landing page from the live ad. Wrong city, wrong room, wrong language or a slow load kills the booking before the engine even loads.',
  'Confirm the dates the ad implies are actually available and priced — clicks into a sold-out or blacked-out window convert at zero.',
  'Walk the booking engine end to end on mobile. The drop is usually a form field or a forced account step, not the bid.',
]

const AOV_FIXES: string[] = [
  'Lead with the higher room types in the ad and on the landing page; the cheapest rate plan is what people book when it is all they are shown.',
  'Sell length of stay — a 2-night minimum or a third-night discount lifts booking value without lifting cost per booking.',
  'Aim at the dates and markets that already book richer stays instead of discounting to win volume.',
]

function fixesFor(key: LeverKey, row: CampaignRow): string[] {
  const fam = familyOf(row)
  switch (key) {
    case 'cpm': {
      const fixes = [...CPM_FIXES[fam]]
      if (row.funnel_stage === 'MOF') {
        // Project convention: MOF is the remarketing stage. A small pool and a
        // hot CPM are the point, not a defect — so say that before sending
        // anyone off to widen an audience that is meant to be narrow.
        fixes.unshift('MOF is remarketing, so a small pool and a high CPM come with the stage — only widen the window (30d → 90d) if reach has actually flattened.')
      }
      return fixes
    }
    case 'ctr': return CTR_FIXES[fam]
    case 'cr': return CR_FIXES
    case 'aov': return AOV_FIXES
  }
}

// --- diagnosis ---------------------------------------------------------------

export type Money = (n: number) => string

const isRate = (key: LeverKey) => key === 'ctr' || key === 'cr'
export const fmtLever = (key: LeverKey, v: number, fmt: Money) =>
  isRate(key) ? `${v.toFixed(2)}%` : fmt(Math.round(v))
const num = (n: number) => (n || 0).toLocaleString('en-US')

// Gaps are always stated as a multiple. "342% below" is not a thing a number
// can be; "the median pulls 4.4x the clicks" is, and it stays readable whether
// the gap is 20% or 20x.
const mult = (ratio: number) => `${ratio.toFixed(1)}x`

const THIN_WHY: Record<LeverKey, (row: CampaignRow) => string> = {
  cpm: r => `Only ${num(r.impressions)} impressions — under ${num(MIN_IMPRESSIONS)} the delivery cost swings too much to read.`,
  ctr: r => `Only ${num(r.impressions)} impressions — under ${num(MIN_IMPRESSIONS)} a click rate is noise.`,
  cr: r => `Only ${num(r.clicks)} clicks — under ${MIN_CLICKS} a single booking moves the rate by whole points.`,
  aov: () => 'No bookings yet, so there is no booking value to judge.',
}

const DRAG_WHY: Record<LeverKey, (gap: string, peer: string, scope: string, own: string) => string> = {
  cpm: (gap, peer, scope, own) =>
    `CPM ${own} against a ${scope} median of ${peer} — you are paying ${gap} as much for the same 1,000 impressions.`,
  ctr: (gap, peer, scope, own) =>
    `CTR ${own} against a ${scope} median of ${peer} — comparable campaigns pull ${gap} the clicks out of the same impressions.`,
  cr: (gap, peer, scope, own) =>
    `CR ${own} against a ${scope} median of ${peer} — comparable campaigns turn ${gap} as many clicks into bookings.`,
  aov: (gap, peer, scope, own) =>
    `AOV ${own} against a ${scope} median of ${peer} — the bookings land, but they are worth ${gap} less than comparable ones.`,
}

const STRENGTH_WHY: Record<LeverKey, (gap: string, peer: string, scope: string, own: string) => string> = {
  cpm: (gap, peer, scope, own) =>
    `CPM ${own} is ${gap} cheaper than the ${scope} median of ${peer} — this is working, protect it.`,
  ctr: (gap, peer, scope, own) =>
    `CTR ${own} is ${gap} the ${scope} median of ${peer} — the creative is earning its clicks, protect it.`,
  cr: (gap, peer, scope, own) =>
    `CR ${own} is ${gap} the ${scope} median of ${peer} — the post-click path is working, protect it.`,
  aov: (gap, peer, scope, own) =>
    `AOV ${own} is ${gap} the ${scope} median of ${peer} — these bookings are the valuable ones, protect it.`,
}

function buildLever(
  key: LeverKey, row: CampaignRow, peers: CampaignRow[], scope: PeerScope, roas: number, fmt: Money,
): Lever {
  const value = valueOf(row, key)
  const change = changeOf(row, key)
  const label = LEVER_LABEL[key]
  const base = { key, label, value, change, peer: null, upside: null, projectedRoas: null }

  if (!hasVolume(row, key)) {
    return { ...base, status: 'thin', why: THIN_WHY[key](row), fixes: [] }
  }

  // A peer only counts toward the median when it could measure the lever too.
  const eligible = peers.filter(p => hasVolume(p, key) && valueOf(p, key) > 0)
  const peer = median(eligible.map(p => valueOf(p, key)))
  if (peer == null || eligible.length < MIN_PEERS) {
    return {
      ...base,
      status: 'blind',
      why: `Only ${eligible.length} comparable ${scope.label} ${eligible.length === 1 ? 'campaign' : 'campaigns'} in this view — too few to say whether ${fmtLever(key, value, fmt)} is good or bad.`,
      fixes: [],
    }
  }

  // A zero rate on real delivery is a genuine drag, but the ratio is infinite,
  // so it gets named without a projection attached.
  if (value <= 0) {
    return {
      ...base, peer,
      status: 'drag',
      why: `${label} is 0 while comparable campaigns run at ${fmtLever(key, peer, fmt)} — this lever is contributing nothing.`,
      fixes: fixesFor(key, row),
    }
  }

  // >1 always means "worse than peers", whichever direction is good for the
  // metric, so one comparison covers all four levers.
  const ratio = key === 'cpm' ? value / peer : peer / value
  const dragAt = eligible.length >= WIDE_SAMPLE ? DRAG_WIDE_SAMPLE : DRAG_NARROW_SAMPLE
  const status: LeverStatus =
    ratio >= dragAt ? 'drag' : ratio <= 1 / dragAt ? 'strength' : 'par'

  const own = fmtLever(key, value, fmt)
  const peerTxt = fmtLever(key, peer, fmt)
  let why: string
  if (status === 'drag') {
    why = DRAG_WHY[key](mult(ratio), peerTxt, scope.label, own)
  } else if (status === 'strength') {
    why = STRENGTH_WHY[key](mult(1 / ratio), peerTxt, scope.label, own)
  } else {
    why = `${label} ${own} sits in line with the ${scope.label} median of ${peerTxt}. Nothing to win here.`
  }

  // A lever can sit at par and still be falling off a cliff; the period delta
  // is the only thing that catches that, so it is appended whenever it is big.
  if (change != null && Math.abs(change) >= 0.25) {
    why += ` It also moved ${change > 0 ? 'up' : 'down'} ${Math.round(Math.abs(change) * 100)}% against the previous period.`
  }

  return {
    ...base,
    peer,
    status,
    upside: status === 'drag' ? ratio : null,
    projectedRoas: status === 'drag' && roas > 0 && ratio <= MAX_PROJECTION ? roas * ratio : null,
    why,
    fixes: status === 'drag' ? fixesFor(key, row) : [],
  }
}

const STATUS_RANK: Record<LeverStatus, number> = { drag: 0, thin: 1, blind: 2, par: 3, strength: 4 }

export function diagnoseCampaign(row: CampaignRow, rows: CampaignRow[], fmt: Money): CampaignDiagnosis {
  const { peers, scope } = pickPeers(row, rows)
  const roas = row.roas || 0

  const levers = (['cpm', 'ctr', 'cr', 'aov'] as LeverKey[])
    .map(k => buildLever(k, row, peers, scope, roas, fmt))
    .sort((a, b) => {
      const byStatus = STATUS_RANK[a.status] - STATUS_RANK[b.status]
      if (byStatus !== 0) return byStatus
      return (b.upside ?? 0) - (a.upside ?? 0)
    })

  const primary = levers.find(l => l.status === 'drag') ?? null

  // Some rows cannot be read as a performance problem at all. Say that, rather
  // than ranking levers computed from numbers that do not mean anything yet.
  let blocker: CampaignDiagnosis['blocker'] = null
  if ((row.impressions || 0) < MIN_IMPRESSIONS) {
    blocker = {
      title: 'Not enough delivery to diagnose',
      why: `${num(row.impressions)} impressions in this window. Every rate below is built on that, so none of them mean anything yet.`,
      fixes: [
        'Widen the date range — the campaign may simply be newer than the window.',
        'If it should be delivering, check budget, schedule, and whether the ads cleared review.',
      ],
    }
  } else if ((row.conversions || 0) === 0 && (row.clicks || 0) >= MIN_CLICKS) {
    blocker = {
      title: 'Spending and clicking, never booking',
      why: `${num(row.clicks)} clicks and 0 bookings on ${fmt(Math.round(row.spend))}. At that click volume this is almost always broken tracking or a wrong landing page, not a bidding problem — and no bid change fixes it.`,
      fixes: [
        "Verify the booking conversion actually fires on this campaign's landing page.",
        'Open the landing page from the live ad: right property, right city, right language, and it actually loads.',
        row.funnel_stage === 'TOF'
          ? 'If tracking checks out, judge this cold campaign on assisted conversions rather than last-click ROAS.'
          : 'If tracking checks out and it still books nothing, pause it and move the budget.',
      ],
    }
  }

  let headline: string
  if (blocker) {
    headline = blocker.why
  } else if (primary) {
    headline = primary.projectedRoas
      ? `${primary.label} is the bottleneck. At the ${scope.label} median this campaign would post ${primary.projectedRoas.toFixed(2)}x instead of ${roas.toFixed(2)}x.`
      : `${primary.label} is the bottleneck — it is the furthest from what comparable campaigns achieve.`
  } else if (levers.every(l => l.status === 'blind')) {
    headline = `Nothing to compare this against — there are too few other ${scope.label} campaigns in the current filter. Widen the date range, or clear the country and branch filters, and open this again.`
  } else if (levers.every(l => l.status === 'thin' || l.status === 'blind')) {
    headline = 'Not enough volume or comparable data in this view to say which lever to pull.'
  } else {
    headline = `No single lever is dragging — every measurable metric is at or above the ${scope.label} median. This one is a budget decision, not a rebuild.`
  }

  return { levers, primary, peers: scope, headline, blocker }
}
