/**
 * Plain-language rendering for the Tactics page.
 *
 * The rule engine speaks in metric keys, operators and fail codes
 * ("roas", "<", "2.1000 < 1.0 is false"). Nobody reading the page should have
 * to decode that, so every sentence a human sees on /tactics comes from here.
 */

export type RuleSummary = {
  id: string
  name: string
  entity_level: string
  action: string
  conditions: any[] | null
  action_params: Record<string, any> | null
  is_active: boolean
}

export type LastEvaluation = {
  executed_at: string | null
  entities_checked: number | null
  actions_taken: number | null
  top_fail_reason: string | null
  fail_breakdown: Record<string, number> | null
  fail_examples: Array<{
    entity_id: string | null
    entity_name: string | null
    failed_at: string | null
    reason: string | null
  }>
  error_message: string | null
}

export type LastError = {
  executed_at: string | null
  action: string
  message: string | null
}

const METRIC_LABELS: Record<string, string> = {
  roas: 'ROAS',
  spend: 'spend',
  revenue: 'revenue',
  ctr: 'CTR',
  cpc: 'CPC',
  cpa: 'CPA',
  impressions: 'impressions',
  clicks: 'clicks',
  conversions: 'conversions',
  frequency: 'frequency',
  add_to_cart: 'add-to-carts',
  checkouts: 'checkouts',
  searches: 'searches',
  leads: 'leads',
  hours_since_creation: 'age',
  active_ads_in_adset: 'active ads in the ad set',
}

const OPERATOR_WORDS: Record<string, string> = {
  '<': 'below',
  '>': 'above',
  '<=': 'at or below',
  '>=': 'at or above',
  '==': 'exactly',
}

const ENTITY_WORDS: Record<string, string> = {
  ad: 'ad',
  ad_set: 'ad set',
  campaign: 'campaign',
}

export function metricLabel(metric?: string | null): string {
  if (!metric) return 'the metric'
  return METRIC_LABELS[metric] || metric.replace(/_/g, ' ')
}

export function entityWord(level: string, plural = false): string {
  const w = ENTITY_WORDS[level] || level
  return plural ? w + 's' : w
}

function num(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v ?? '')
  // Small ratios (ROAS, CTR) read better with decimals; money-ish stays whole.
  return Math.abs(n) < 100 && !Number.isInteger(n) ? n.toFixed(2) : n.toLocaleString()
}

/** "ROAS below 1.00 over the last 7 days" */
export function describeCondition(c: any): string {
  const metric = metricLabel(c?.metric)
  const op = OPERATOR_WORDS[c?.operator] || c?.operator || 'vs'
  const days = Number(c?.days)
  const window = Number.isFinite(days) && days > 0
    ? ' over the last ' + days + (days === 1 ? ' day' : ' days')
    : ''

  if (c?.compare_metric) {
    const from = c.compare_period_from
    const to = c.compare_period_to
    const period = from != null && to != null ? ' (vs day ' + from + '-' + to + ' before)' : ''
    return metric + ' ' + op + ' ' + metricLabel(c.compare_metric) + period + window
  }
  if (c?.metric === 'hours_since_creation') {
    return metric + ' ' + op + ' ' + num(c?.threshold) + ' hours'
  }
  return metric + ' ' + op + ' ' + num(c?.threshold) + window
}

function pct(v: unknown): string {
  const n = Number(v)
  return Number.isFinite(n) ? Math.round(Math.abs(n) * 100) + '%' : '?'
}

/** "Pause the ad", "Raise budget by 20%", "Send an alert" */
export function describeAction(action: string, params?: Record<string, any> | null): string {
  const mult = Number(params?.budget_multiplier)
  if (action === 'adjust_budget' && params) {
    // The budget presets each carry their own knobs rather than a flat
    // multiplier, so say what the preset actually does to the money.
    if (params.scale_winning) {
      const cap = Number(params.max_budget_cap_multiplier)
      return 'Raise budget by ' + pct(params.daily_step_pct) + ' a day'
        + (Number.isFinite(cap) ? ', up to ' + cap + 'x the starting budget' : '')
    }
    if (params.sunsetting) {
      return 'Wind the budget down in steps (-' + pct(params.step1_reduction_pct)
        + ', then -' + pct(params.step2_reduction_pct) + ', then pause)'
    }
    if (Number.isFinite(mult) && mult > 1) {
      const cap = Number(params.max_budget_cap_multiplier)
      return 'Raise budget by ' + Math.round((mult - 1) * 100) + '% for the day'
        + (Number.isFinite(cap) ? ', never past ' + cap + 'x the starting budget' : '')
    }
  }
  switch (action) {
    case 'pause_ad': return 'Pause the ad'
    case 'pause_adset':
    case 'pause_ad_set': return 'Pause the ad set'
    case 'pause_campaign': return 'Pause the campaign'
    case 'enable_ad':
    case 'reenable_ad': return 'Turn the ad back on'
    case 'enable_adset':
    case 'enable_ad_set': return 'Turn the ad set back on'
    case 'enable_campaign': return 'Turn the campaign back on'
    case 'send_alert': return 'Send an alert (nothing on Meta changes)'
    case 'adjust_budget':
      if (Number.isFinite(mult) && mult !== 1) {
        const step = Math.round(Math.abs(mult - 1) * 100)
        return mult > 1 ? 'Raise budget by ' + step + '%' : 'Cut budget by ' + step + '%'
      }
      return 'Adjust budget'
    default:
      return action.replace(/_/g, ' ')
  }
}

/** One sentence per rule. */
export function describeRule(r: RuleSummary): string {
  const conds = Array.isArray(r.conditions) ? r.conditions : []
  if (!conds.length) return describeAction(r.action, r.action_params)

  // When every condition shares one measurement window, say it once at the end
  // instead of repeating "over the last 7 days" after each clause.
  const windows = new Set(conds.map(c => Number(c?.days)).filter(d => Number.isFinite(d) && d > 0))
  const shared = windows.size === 1 && conds.every(c => Number(c?.days) > 0)
    ? Array.from(windows)[0]
    : null

  const clauses = conds.map(c => describeCondition(shared ? { ...c, days: undefined } : c))
  const tail = shared ? ', measured over the last ' + shared + (shared === 1 ? ' day' : ' days') : ''
  return describeAction(r.action, r.action_params) + ' when ' + clauses.join(' and ') + tail
}

export function describeTactic(rules: RuleSummary[]): string[] {
  if (!rules || !rules.length) return ['No rules attached — this tactic cannot do anything.']
  return rules.map(describeRule)
}

/**
 * Turn an engine fail reason into something readable.
 * "2.1000 < 1.0 is false" -> "ROAS was 2.10 - rule needs below 1.00"
 */
export function humanizeFailExample(
  reason: string | null | undefined,
  failedAt: string | null | undefined,
): string {
  const metric = metricLabel(failedAt)
  if (!reason) return metric + ' did not match'

  const m = reason.match(/^([-\d.]+)h?\s*(<=|>=|==|<|>)\s*([-\d.]+)h?\s+is false$/)
  if (m) {
    const left = m[1]
    const op = m[2]
    const right = m[3]
    return metric + ' was ' + num(left) + ' — rule needs ' + (OPERATOR_WORDS[op] || op) + ' ' + num(right)
  }
  if (reason.startsWith('no metrics data')) {
    return 'no ' + metric + ' data in that window yet (not synced, or no delivery)'
  }
  if (reason.startsWith('no comparison data')) {
    return 'no data for the comparison period yet'
  }
  if (reason === 'no creation date') {
    return 'missing creation date, so age could not be checked'
  }
  if (reason === 'not applicable at campaign level') {
    return 'that check only works at ad-set level'
  }
  if (reason.startsWith('unknown operator')) {
    return 'rule is misconfigured: ' + reason
  }
  return reason
}

export type StatusTone = 'off' | 'error' | 'waiting' | 'acted' | 'idle' | 'nothing_to_check'

export type TacticStatus = {
  tone: StatusTone
  label: string
  detail: string
  /** True when the last evaluation is old enough to distrust. */
  stale: boolean
}

const HOUR = 3600 * 1000

export function ago(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return 'never'
  const h = (Date.now() - t) / HOUR
  if (h < 1) return 'less than an hour ago'
  if (h < 24) return Math.round(h) + 'h ago'
  const d = Math.round(h / 24)
  return d + (d === 1 ? ' day ago' : ' days ago')
}

export function tacticStatus(t: {
  is_active: boolean
  rule_count: number
  rules_summary?: RuleSummary[]
  last_evaluation?: LastEvaluation | null
  last_error?: LastError | null
}): TacticStatus {
  const ev = t.last_evaluation
  // "checked 7 ads" beats "checked 7" — take the noun from the rules it runs.
  const levels = new Set((t.rules_summary || []).map(r => r.entity_level))
  const noun = (n: number) => levels.size === 1
    ? ' ' + entityWord(Array.from(levels)[0], n !== 1)
    : n === 1 ? ' item' : ' items'
  const stale = !!ev?.executed_at && (Date.now() - new Date(ev.executed_at).getTime()) > 36 * HOUR

  if (!t.is_active) {
    return {
      tone: 'off',
      label: 'Off',
      detail: 'Switched off — it checks nothing and changes nothing.',
      stale: false,
    }
  }

  if (t.rule_count === 0) {
    return {
      tone: 'error',
      label: 'Broken',
      detail: 'No rules attached, so the daily run has nothing to evaluate.',
      stale: false,
    }
  }

  // A failed mutation newer than the last evaluation is the headline.
  const errTime = t.last_error?.executed_at ? new Date(t.last_error.executed_at).getTime() : 0
  const evalTime = ev?.executed_at ? new Date(ev.executed_at).getTime() : 0
  if (t.last_error && errTime >= evalTime - HOUR) {
    return {
      tone: 'error',
      label: 'Failed',
      detail: 'Meta rejected the last change (' + ago(t.last_error.executed_at) + '): '
        + (t.last_error.message || 'no error message returned'),
      stale,
    }
  }

  if (!ev) {
    return {
      tone: 'waiting',
      label: 'Never run',
      detail: 'The daily run has not evaluated this tactic yet. It runs once a day at 17:00 UTC (midnight Vietnam time).',
      stale: false,
    }
  }

  const checked = ev.entities_checked ?? 0
  const acted = ev.actions_taken ?? 0

  if (acted > 0) {
    return {
      tone: 'acted',
      label: 'Acted',
      detail: 'Last run (' + ago(ev.executed_at) + ') checked ' + checked + noun(checked) + ' and changed ' + acted + '.',
      stale,
    }
  }

  if (checked === 0) {
    return {
      tone: 'nothing_to_check',
      label: 'Nothing to check',
      detail: 'Last run (' + ago(ev.executed_at) + ') found 0' + noun(0) + ' to look at — the account or funnel filter matches nothing, or the sync has not produced metrics for them.',
      stale,
    }
  }

  const top = ev.top_fail_reason ? metricLabel(ev.top_fail_reason) : null
  return {
    tone: 'idle',
    label: 'No change needed',
    detail: 'Last run (' + ago(ev.executed_at) + ') checked ' + checked + noun(checked) + ' and changed nothing'
      + (top ? ' — most were held back by ' + top : '') + '.',
    stale,
  }
}

export const STATUS_STYLES: Record<StatusTone, string> = {
  off: 'bg-gray-100 text-gray-600 border-gray-200',
  error: 'bg-red-50 text-red-700 border-red-200',
  waiting: 'bg-amber-50 text-amber-700 border-amber-200',
  acted: 'bg-green-50 text-green-700 border-green-200',
  idle: 'bg-blue-50 text-blue-700 border-blue-200',
  nothing_to_check: 'bg-amber-50 text-amber-700 border-amber-200',
}
