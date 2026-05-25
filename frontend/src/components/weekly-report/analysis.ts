// Weekly Report analysis layer — pure, deterministic functions that turn raw
// campaign rows + the Activity Log into a "what's working / what's broken /
// why / what to do" verdict.
//
// All metrics come from /api/dashboard/country/campaigns (CampaignRow) so the
// ROAS = CR × AOV / CPC decomposition is available per campaign, and change
// fields are period-over-period FRACTIONS (0.334 = +33.4%).

import type { CampaignRow } from '@/components/dashboard/CampaignBreakdownTable'
import type { ChangeLogItem } from '@/components/dashboard/activity/ActivityLogPanel'

export type FunnelStage = 'TOF' | 'MOF' | 'BOF'
export type Verdict = 'winner' | 'watch' | 'loser'

export type Diagnosis = {
  stage: FunnelStage
  driver: 'cr' | 'cpc' | 'aov' | 'ctr' | 'roas'
  reason: string
}

export type CampaignInsight = {
  row: CampaignRow
  verdict: Verdict
  /** Share of total spend in the window, 0..1 — used for materiality ranking. */
  spendShare: number
  /** Money lost while ROAS < 1 (spend × (1 − roas)); 0 for profitable rows. */
  bleed: number
  diagnosis: Diagnosis | null
  recommendations: string[]
  activity: ChangeLogItem[]
}

export type NextAction = {
  severity: 'high' | 'medium' | 'low'
  text: string
  campaign?: string
}

// Surface a loser/winner in the report only when it moves the needle.
export const MIN_SPEND_SHARE = 0.02

const pctAbs = (v: number | null | undefined): number =>
  v == null ? 0 : Math.round(Math.abs(v) * 100)

export function verdictOf(row: CampaignRow): Verdict {
  if (row.roas >= 1.5) return 'winner'
  if (row.roas >= 1.0) return 'watch'
  return 'loser'
}

/**
 * Pin the weak funnel stage. ROAS = CR × AOV / CPC, so a ROAS drop is caused by
 * CR falling, AOV falling, or CPC rising. When there's a strong week-over-week
 * move (≥10%) we attribute the drop to the dominant factor; otherwise we read
 * the absolute funnel levels (low CTR = top, low CR = bottom).
 */
export function diagnoseFunnel(row: CampaignRow): Diagnosis {
  const crHurt = Math.max(0, -(row.cr_change ?? 0))
  const aovHurt = Math.max(0, -(row.aov_change ?? 0))
  const cpcHurt = Math.max(0, row.cpc_change ?? 0)
  const maxHurt = Math.max(crHurt, aovHurt, cpcHurt)

  if (maxHurt >= 0.1) {
    if (maxHurt === cpcHurt) {
      return {
        stage: 'MOF',
        driver: 'cpc',
        reason: `ROAS dropped mainly because CPC rose ${pctAbs(row.cpc_change)}% — paying more per click (mid-funnel / MOF).`,
      }
    }
    if (maxHurt === aovHurt) {
      return {
        stage: 'BOF',
        driver: 'aov',
        reason: `ROAS dropped because AOV fell ${pctAbs(row.aov_change)}% — pulling in lower-value guests (bottom-funnel / BOF).`,
      }
    }
    return {
      stage: 'BOF',
      driver: 'cr',
      reason: `ROAS dropped mainly because CR fell ${pctAbs(row.cr_change)}% — traffic lands but doesn't book (bottom-funnel / BOF).`,
    }
  }

  // No strong WoW signal → diagnose from absolute funnel levels.
  if (row.ctr > 0 && row.ctr < 1) {
    return {
      stage: 'TOF',
      driver: 'ctr',
      reason: `CTR is only ${row.ctr.toFixed(2)}% — the ad isn't earning clicks (top-funnel / TOF).`,
    }
  }
  if (row.clicks >= 50 && row.cr < 0.5) {
    return {
      stage: 'BOF',
      driver: 'cr',
      reason: `CR is only ${row.cr.toFixed(2)}% — ${row.clicks.toLocaleString('en-US')} clicks in but almost no bookings (bottom-funnel / BOF).`,
    }
  }
  return {
    stage: 'BOF',
    driver: 'roas',
    reason: `ROAS ${row.roas.toFixed(2)}x — no clear break at top/mid funnel; the bottleneck is the final booking step (BOF): review creative → landing → price.`,
  }
}

export function recommend(row: CampaignRow, d: Diagnosis, verdict: Verdict): string[] {
  const recs: string[] = []
  if (verdict === 'loser') {
    recs.push(
      `ROAS ${row.roas.toFixed(2)}x is losing money — cut budget or pause until fixed, and shift spend to higher-ROAS campaigns.`,
    )
  }
  switch (d.driver) {
    case 'cr':
      recs.push('Check the conversion tracking/pixel is still firing — an abnormal CR drop usually means broken tracking.')
      recs.push('Review the landing page, room price & availability for this campaign.')
      recs.push('Cut keywords/audiences with the wrong intent that are driving junk clicks.')
      break
    case 'cpc':
      recs.push('Tighten targeting & bids; drop expensive placements/keywords.')
      recs.push('Refresh the creative to lift relevance → bring CPC down.')
      break
    case 'ctr':
      recs.push('Swap the hook/creative/offer at the top of funnel — CTR is low.')
      recs.push('Narrow an over-broad audience; test new audiences with clear travel intent.')
      break
    case 'aov':
      recs.push('Target higher-value audiences; push multi-night packages / premium rooms.')
      recs.push('Add upsells/add-ons to raise AOV.')
      break
    default:
      recs.push('Re-check creative → landing → price to find the drop-off at the bottom of funnel.')
  }
  return recs
}

export function winnerRecommend(row: CampaignRow): string[] {
  const recs = [
    `ROAS ${row.roas.toFixed(2)}x is profitable — scale budget 20–30% in steps and watch whether CPA holds.`,
  ]
  if ((row.roas_change ?? 0) > 0.1) {
    recs.push('Trending up — duplicate to similar audiences/keywords to expand.')
  }
  return recs
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

export function buildInsights(rows: CampaignRow[], log: ChangeLogItem[]): CampaignInsight[] {
  const totalSpend = rows.reduce((s, r) => s + (r.spend || 0), 0) || 1
  return rows.map((row) => {
    const verdict = verdictOf(row)
    const diagnosis = verdict === 'winner' ? null : diagnoseFunnel(row)
    const recommendations = diagnosis ? recommend(row, diagnosis, verdict) : winnerRecommend(row)
    return {
      row,
      verdict,
      spendShare: (row.spend || 0) / totalSpend,
      bleed: row.roas < 1 ? (row.spend || 0) * (1 - row.roas) : 0,
      diagnosis,
      recommendations,
      activity: correlateActivity(row, log),
    }
  })
}

/** Prioritized to-do list: stop the bleeding, scale the winners, fix tracking. */
export function buildNextActions(insights: CampaignInsight[]): NextAction[] {
  const actions: NextAction[] = []

  const losers = insights
    .filter((i) => i.verdict === 'loser' && i.spendShare >= MIN_SPEND_SHARE)
    .sort((a, b) => b.bleed - a.bleed)
  for (const i of losers.slice(0, 5)) {
    actions.push({
      severity: i.spendShare >= 0.1 ? 'high' : 'medium',
      campaign: i.row.campaign_name,
      text: `${i.diagnosis?.reason ?? ''} ${i.recommendations[0] ?? ''}`.trim(),
    })
  }

  const scale = insights
    .filter((i) => i.verdict === 'winner' && i.row.roas >= 3 && i.spendShare < 0.05)
    .sort((a, b) => b.row.roas - a.row.roas)
  for (const i of scale.slice(0, 3)) {
    actions.push({
      severity: 'medium',
      campaign: i.row.campaign_name,
      text: `ROAS ${i.row.roas.toFixed(2)}x but only ${(i.spendShare * 100).toFixed(1)}% of budget spent — raise budget to capture more bookings.`,
    })
  }

  // Tracking-integrity changes that coincide with a CR-driven collapse.
  const trackingFlag = insights.find(
    (i) =>
      i.verdict !== 'winner' &&
      i.diagnosis?.driver === 'cr' &&
      i.activity.some((a) => a.category === 'tracking_integrity'),
  )
  if (trackingFlag) {
    actions.unshift({
      severity: 'high',
      campaign: trackingFlag.row.campaign_name,
      text: 'Activity Log shows a tracking change at the same time CR collapsed — verify the pixel/conversion before touching budget.',
    })
  }

  return actions
}
