'use client'

import { ChangeTag, fmtMoney, fmtNum } from './dashboardUtils'

export type BreakdownItem = {
  key: string
  label: string
  badgeClass?: string
  spend: number
  revenue: number
  conversions: number
  leads: number
  roas: number
  spend_change: number | null
  roas_change: number | null
  conversions_change: number | null
}

type Metric = 'spend' | 'roas' | 'conversions'

export default function HorizontalBarBreakdown({
  title,
  items,
  currency,
  selectedKey,
  onSelect,
  metric = 'spend',
  onMetricChange,
  campaignType,
}: {
  title: string
  items: BreakdownItem[]
  currency: string
  selectedKey: string
  onSelect: (key: string) => void
  metric?: Metric
  onMetricChange?: (m: Metric) => void
  campaignType?: string
}) {
  const isLead = campaignType === 'lead'

  const METRIC_LABEL: Record<Metric, string> = {
    spend: 'Spend',
    roas: 'ROAS',
    conversions: isLead ? 'Leads' : 'Conversions',
  }

  const valueOf = (it: BreakdownItem) => {
    if (metric === 'spend') return it.spend
    if (metric === 'roas') return it.roas
    return isLead ? it.leads : it.conversions
  }
  const max = Math.max(...items.map(valueOf), 1)
  const hasFilter = !!selectedKey
  const fmt = (it: BreakdownItem) => {
    if (metric === 'spend') return fmtMoney(it.spend, currency)
    if (metric === 'roas') return `${it.roas.toFixed(2)}x`
    return fmtNum(isLead ? it.leads : it.conversions)
  }
  const change = (it: BreakdownItem) => {
    if (metric === 'spend') return { c: it.spend_change, inv: true }
    if (metric === 'roas') return { c: it.roas_change, inv: false }
    return { c: it.conversions_change, inv: false }
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-700">{title}</h2>
        {onMetricChange && (
          <div className="inline-flex rounded-md border border-gray-200 overflow-hidden text-[11px]">
            {(Object.keys(METRIC_LABEL) as Metric[]).map((m) => (
              <button
                key={m}
                onClick={() => onMetricChange(m)}
                className={`px-2 py-1 ${
                  metric === m ? 'bg-blue-50 text-blue-700' : 'text-gray-500 hover:bg-gray-50'
                }`}
              >
                {METRIC_LABEL[m]}
              </button>
            ))}
          </div>
        )}
      </div>
      {items.length === 0 ? (
        <p className="text-gray-400 text-xs text-center py-8">No data</p>
      ) : (
        <div className="space-y-2">
          {items.map((it) => {
            const widthPct = Math.max((valueOf(it) / max) * 100, 4)
            const isActive = selectedKey === it.key
            const dim = hasFilter && !isActive
            const ch = change(it)
            return (
              <button
                key={it.key}
                onClick={() => onSelect(it.key)}
                className={`w-full text-left group ${dim ? 'opacity-40' : ''}`}
                title={isActive ? 'Click to clear filter' : `Click to filter by ${it.label}`}
              >
                <div className="flex items-center justify-between mb-0.5">
                  <span className="flex items-center gap-2">
                    {it.badgeClass ? (
                      <span className={`text-[10px] px-2 py-0.5 rounded-full ${it.badgeClass}`}>
                        {it.label}
                      </span>
                    ) : (
                      <span className={`text-xs font-medium ${isActive ? 'text-blue-700' : 'text-gray-700'}`}>
                        {it.label}
                      </span>
                    )}
                    <ChangeTag change={ch.c} inverseColor={ch.inv} />
                  </span>
                  <span className="text-xs text-gray-600">{fmt(it)}</span>
                </div>
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      isActive ? 'bg-blue-600' : 'bg-blue-300 group-hover:bg-blue-400'
                    }`}
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
              </button>
            )
          })}
        </div>
      )}
      {hasFilter && (
        <button
          onClick={() => onSelect('')}
          className="mt-3 text-[11px] text-blue-600 hover:underline"
        >
          Clear {title.toLowerCase()} filter
        </button>
      )}
    </div>
  )
}
