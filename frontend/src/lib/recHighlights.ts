// Picks 1-2 "hero" metrics to spotlight on each recommendation card.
//
// The detector_finding JSON already isolates the values that triggered the
// rec (e.g. roas_7d for BAD_ROAS_7D), so we surface those first and fall back
// to the general 7-day snapshot. Each entry returns a colour hint so the
// card can match Madgicx's orange-for-problem / green-for-opportunity vibe.

export type HighlightTone = 'red' | 'amber' | 'green' | 'blue' | 'gray'

export interface MetricHighlight {
  label: string
  value: string
  caption?: string
  tone: HighlightTone
}

const TONE_BG: Record<HighlightTone, string> = {
  red: 'bg-red-50 border-red-200',
  amber: 'bg-amber-50 border-amber-200',
  green: 'bg-green-50 border-green-200',
  blue: 'bg-blue-50 border-blue-200',
  gray: 'bg-gray-50 border-gray-200',
}
const TONE_VALUE: Record<HighlightTone, string> = {
  red: 'text-red-700',
  amber: 'text-amber-700',
  green: 'text-green-700',
  blue: 'text-blue-700',
  gray: 'text-gray-800',
}
const TONE_LABEL: Record<HighlightTone, string> = {
  red: 'text-red-600',
  amber: 'text-amber-700',
  green: 'text-green-700',
  blue: 'text-blue-700',
  gray: 'text-gray-500',
}

export function highlightStyles(tone: HighlightTone) {
  return {
    box: TONE_BG[tone],
    value: TONE_VALUE[tone],
    label: TONE_LABEL[tone],
  }
}

const COMPACT = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 1,
})
const PCT = new Intl.NumberFormat('en-US', {
  style: 'percent',
  maximumFractionDigits: 2,
})

export function fmtMoney(value: number, currency: string | undefined): string {
  const cur = (currency || 'VND').toUpperCase()
  if (cur === 'VND' || cur === 'JPY' || cur === 'KRW') {
    return `${COMPACT.format(value)} ${cur}`
  }
  if (Math.abs(value) >= 10_000) return `${COMPACT.format(value)} ${cur}`
  return `${value.toFixed(2)} ${cur}`
}
export function fmtNum(value: number): string {
  if (Math.abs(value) >= 1000) return COMPACT.format(value)
  return value.toLocaleString()
}
export function fmtPct(value: number): string {
  // Inputs are fractions (0.012 = 1.2%) — matches snapshot_campaign / snapshot_ad output.
  return PCT.format(value)
}
export function fmtRoas(value: number): string {
  return `${value.toFixed(2)}×`
}

interface PickContext {
  rec_type: string
  detector_finding: Record<string, any>
  metrics_snapshot: Record<string, any>
  currency?: string
}

function num(obj: Record<string, any>, key: string): number | null {
  const v = obj?.[key]
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}

// Map a rec_type to the most informative 1-2 highlight metrics.
// Anything not in this map falls back to the generic 7-day spend + ROAS pair.
export function pickHighlights(ctx: PickContext): MetricHighlight[] {
  const { rec_type, detector_finding: f, metrics_snapshot: m, currency } = ctx
  const t = rec_type.toUpperCase()

  // ── Meta detectors ─────────────────────────────────────────────────────
  if (t === 'BAD_ROAS_7D') {
    const roas = num(f, 'roas_7d') ?? num(m, 'roas_7d') ?? 0
    const spend = num(f, 'spend_7d') ?? num(m, 'spend_7d') ?? 0
    return [
      { label: '7-day ROAS', value: fmtRoas(roas), tone: 'red', caption: 'Below SOP target' },
      { label: '7-day spend', value: fmtMoney(spend, currency), tone: 'gray' },
    ]
  }
  if (t === 'LOW_CTR_7D') {
    const ctr = num(f, 'ctr_7d') ?? num(m, 'ctr_7d') ?? 0
    const impr = num(m, 'impressions_7d') ?? 0
    return [
      { label: '7-day CTR', value: fmtPct(ctr), tone: 'amber', caption: 'Below benchmark' },
      { label: '7-day impressions', value: fmtNum(impr), tone: 'gray' },
    ]
  }
  if (t === 'HIGH_CTR_LOW_CVR') {
    const ctr = num(f, 'ctr_7d') ?? num(m, 'ctr_7d') ?? 0
    const cvr = num(f, 'cvr_7d') ?? num(m, 'cvr_7d') ?? 0
    const baseline = num(f, 'cvr_30d_baseline') ?? num(m, 'cvr_30d')
    const caption = baseline !== null && baseline > 0
      ? `vs ${fmtPct(baseline)} 30-day baseline`
      : 'LP / offer leak'
    return [
      { label: '7-day CTR', value: fmtPct(ctr), tone: 'green', caption: 'Hook works' },
      { label: '7-day CVR', value: fmtPct(cvr), tone: 'red', caption },
    ]
  }
  if (t === 'FREQ_ABOVE_CEILING' || t === 'FREQUENCY_HIGH') {
    const freq = num(f, 'frequency_7d') ?? num(m, 'frequency_7d_avg') ?? 0
    const spend = num(m, 'spend_7d') ?? 0
    return [
      { label: '7-day frequency', value: freq.toFixed(2), tone: 'amber', caption: 'Audience burning' },
      { label: '7-day spend', value: fmtMoney(spend, currency), tone: 'gray' },
    ]
  }
  if (t === 'CTR_DROP_BASELINE' || t === 'STALE_CREATIVE_2D') {
    const drop = num(f, 'ctr_drop_pct') ?? 0
    const ctr = num(m, 'ctr_7d') ?? 0
    return [
      { label: 'CTR drop', value: `${(drop * 100).toFixed(0)}%`, tone: 'red', caption: 'vs baseline' },
      { label: '7-day CTR', value: fmtPct(ctr), tone: 'gray' },
    ]
  }
  if (t === 'BUDGET_SHIFT_APPROACHING' || t === 'SEASONALITY_LEAD_TIME_APPROACHING') {
    const days = num(f, 'days_to_event') ?? num(f, 'lead_days') ?? 0
    const event = String(f?.event_name || f?.event || 'Seasonal peak')
    return [
      { label: 'Lead time left', value: `${days} days`, tone: 'amber', caption: event },
      {
        label: 'Recommended +',
        value: f?.suggested_budget_uplift ? `+${Math.round(Number(f.suggested_budget_uplift) * 100)}%` : '—',
        tone: 'blue',
      },
    ]
  }

  // ── Google: PMax / Search / DG ────────────────────────────────────────
  if (t === 'BUDGET_DAILY_EXHAUSTED_EARLY' || t === 'BUDGET_EXHAUSTED_EARLY') {
    const days = num(f, 'days_exhausted_early') ?? num(f, 'days_exhausted') ?? 0
    const spend = num(m, 'spend_7d') ?? 0
    return [
      { label: 'Days exhausted', value: `${days}/7`, tone: 'amber', caption: 'Before 2pm local' },
      { label: '7-day spend', value: fmtMoney(spend, currency), tone: 'gray' },
    ]
  }
  if (t === 'PMAX_LEARNING_STUCK') {
    const weeks = num(f, 'weeks_in_learning') ?? 0
    return [
      { label: 'Weeks stuck', value: `${weeks}w`, tone: 'red', caption: 'Past 4-week SOP cap' },
      { label: 'Suggested action', value: 'tCPA +25%', tone: 'blue' },
    ]
  }
  if (t === 'PMAX_BRANDED_LEAK') {
    const roasMult = num(f, 'roas_multiplier') ?? 0
    return [
      { label: 'PMax ROAS', value: `${roasMult.toFixed(1)}× avg`, tone: 'amber', caption: 'Brand leak signal' },
      {
        label: 'Branded IS drop',
        value: f?.branded_is_wow_drop ? `${Math.round(Number(f.branded_is_wow_drop) * 100)}%` : '—',
        tone: 'red',
      },
    ]
  }
  if (t === 'PMAX_ASSET_GROUP_INCOMPLETE') {
    const missing = Array.isArray(f?.missing_assets) ? f.missing_assets : []
    return [
      { label: 'Missing assets', value: `${missing.length} types`, tone: 'amber', caption: missing.slice(0, 3).join(', ') },
    ]
  }
  if (t === 'DG_CTR_BELOW_BENCHMARK' || t === 'CTR_BELOW_BENCHMARK') {
    const ctr = num(f, 'ctr_14d') ?? num(m, 'ctr_7d') ?? 0
    return [
      { label: '14-day CTR', value: fmtPct(ctr), tone: 'amber', caption: 'Below 0.5% benchmark' },
    ]
  }
  if (t === 'DG_MISSING_VIDEO') {
    return [{ label: 'Video assets', value: '0', tone: 'red', caption: 'Auto-generated stand-in' }]
  }
  if (t === 'SPEND_VS_BUDGET_ANOMALY' || t === 'SPEND_ANOMALY') {
    const yest = num(f, 'spend_yesterday') ?? 0
    const dayBefore = num(f, 'spend_day_before') ?? 0
    return [
      { label: 'Spend yesterday', value: fmtMoney(yest, currency), tone: 'amber' },
      { label: 'Day before', value: fmtMoney(dayBefore, currency), tone: 'gray' },
    ]
  }
  if (t === 'ZERO_CONVERSIONS_7D') {
    const spend = num(m, 'spend_7d') ?? 0
    return [
      { label: 'Conversions (7d)', value: '0', tone: 'red', caption: 'Seven days dry' },
      { label: '7-day spend', value: fmtMoney(spend, currency), tone: 'gray' },
    ]
  }
  if (t === 'IMPRESSIONS_DROP_50' || t === 'IMPR_DROP_50') {
    const drop = num(f, 'impr_drop_pct') ?? 0.5
    return [
      { label: 'Impressions drop', value: `${(drop * 100).toFixed(0)}%`, tone: 'red', caption: 'WoW' },
    ]
  }
  if (t === 'CTR_SPIKE') {
    const ctr = num(m, 'ctr_7d') ?? 0
    return [{ label: '7-day CTR', value: fmtPct(ctr), tone: 'green', caption: 'Above baseline — investigate' }]
  }
  if (t === 'BUDGET_MIX_OFF_TARGET') {
    const off = num(f, 'mix_off_pct') ?? 0
    return [
      { label: 'Mix drift', value: `${Math.round(off * 100)}%`, tone: 'amber', caption: 'Off SOP bands' },
    ]
  }
  if (t === 'PMAX_TCPA_CHANGE_TOO_LARGE' || t === 'PMAX_TCPA_CHANGE') {
    const pct = num(f, 'tcpa_change_pct') ?? 0
    return [
      { label: 'tCPA change', value: `${Math.round(pct * 100)}%`, tone: 'red', caption: 'Within 24h — learning reset' },
    ]
  }
  if (t === 'PMAX_BID_STRATEGY_LIFECYCLE_MISMATCH' || t === 'PMAX_BID_STRATEGY_MISMATCH') {
    const expected = String(f?.expected_strategy || '—')
    const actual = String(f?.actual_strategy || '—')
    return [
      { label: 'SOP expects', value: expected, tone: 'blue' },
      { label: 'Currently', value: actual, tone: 'amber' },
    ]
  }
  if (t === 'RSA_INSUFFICIENT_ASSETS' || t === 'RSA_AD_STRENGTH_POOR') {
    const headlines = num(f, 'headlines_count') ?? 0
    const desc = num(f, 'descriptions_count') ?? 0
    return [
      { label: 'Headlines', value: `${headlines}/15`, tone: headlines < 8 ? 'amber' : 'green' },
      { label: 'Descriptions', value: `${desc}/4`, tone: desc < 3 ? 'amber' : 'green' },
    ]
  }

  // ── Generic fallback: 7-day spend + ROAS ──────────────────────────────
  const spend = num(m, 'spend_7d') ?? 0
  const roas = num(m, 'roas_7d')
  const out: MetricHighlight[] = [
    { label: '7-day spend', value: fmtMoney(spend, currency), tone: 'gray' },
  ]
  if (roas !== null) {
    out.push({
      label: '7-day ROAS',
      value: fmtRoas(roas),
      tone: roas >= 1 ? 'green' : 'amber',
    })
  }
  return out
}

// Convert ai_reasoning prose into 2-4 short bullets the Madgicx-style left
// column can render. The model already writes paragraph chunks separated by
// blank lines, so we split on those first; if there's only a single chunk
// we fall back to sentence boundaries.
export function splitReasoningBullets(text: string | null): string[] {
  if (!text) return []
  const trimmed = text.trim()
  if (!trimmed) return []
  const blocks = trimmed
    .split(/\n\s*\n/)
    .map(s => s.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
  if (blocks.length >= 2) return blocks.slice(0, 4)
  // Single block — split on sentence boundaries, cap at 4.
  const sentences = trimmed
    .replace(/\n+/g, ' ')
    .split(/(?<=[.!?])\s+(?=[A-Z一-鿿])/)
    .map(s => s.trim())
    .filter(Boolean)
  return sentences.slice(0, 4)
}
