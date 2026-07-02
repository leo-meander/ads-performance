'use client'

import { Sparkles, X, TrendingUp, AlertTriangle, CheckCircle } from 'lucide-react'

type DataHighlight = {
  channel: string
  ta: string
  country: string
  roas: number
  spend_pct: number
}

type BudgetSuggestion = {
  channel_pct: Record<string, number>
  ta_focus: Record<string, string[]>
  country_focus: Record<string, string[]>
  rationale: string
  data_highlights: DataHighlight[]
  hid_signals_used: string[]
  warnings: string[]
  meta?: {
    branch: string
    target_month: string
    last_month: string
    total_vnd: number | null
    perf_rows: number
    hid_available: boolean
  }
  error?: string
}

type Props = {
  suggestion: BudgetSuggestion
  targetMonthLabel: string
  onApply: (channelPct: Record<string, number>) => void
  onDismiss: () => void
}

const CHANNEL_COLORS: Record<string, string> = {
  meta: 'bg-blue-500',
  google: 'bg-green-500',
  tiktok: 'bg-pink-500',
}

const CHANNEL_LABEL_COLORS: Record<string, string> = {
  meta: 'text-blue-700 bg-blue-50',
  google: 'text-green-700 bg-green-50',
  tiktok: 'text-pink-700 bg-pink-50',
}

export default function BudgetSuggestionPanel({ suggestion, targetMonthLabel, onApply, onDismiss }: Props) {
  if (suggestion.error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3">
        <AlertTriangle className="w-4 h-4 text-red-500 mt-0.5 flex-shrink-0" />
        <div>
          <p className="text-sm font-medium text-red-800">Suggestion failed</p>
          <p className="text-xs text-red-600 mt-0.5">{suggestion.error}</p>
        </div>
        <button onClick={onDismiss} className="ml-auto text-red-400 hover:text-red-600">
          <X className="w-4 h-4" />
        </button>
      </div>
    )
  }

  const channelPct = suggestion.channel_pct || {}
  const channels = Object.keys(channelPct).sort((a, b) => channelPct[b] - channelPct[a])
  const lastMonthLabel = suggestion.meta?.last_month
    ? new Date(suggestion.meta.last_month + 'T00:00:00').toLocaleString('en-US', { month: 'long', year: 'numeric' })
    : 'last month'

  return (
    <div className="bg-white border border-blue-200 rounded-xl overflow-hidden shadow-sm">
      {/* Header */}
      <div className="px-5 py-3 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-blue-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-blue-600" />
          <span className="text-sm font-semibold text-blue-900">AI Budget Suggestion — {targetMonthLabel}</span>
          <span className="text-xs text-blue-500">based on {lastMonthLabel}</span>
        </div>
        <button onClick={onDismiss} className="text-blue-400 hover:text-blue-600 rounded p-0.5 hover:bg-blue-100 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Body */}
      <div className="p-5 grid grid-cols-3 gap-6">
        {/* Column 1: Channel split */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Channel Split</p>
          <div className="space-y-3">
            {channels.map(ch => {
              const pct = channelPct[ch] ?? 0
              const barColor = CHANNEL_COLORS[ch] || 'bg-gray-400'
              return (
                <div key={ch}>
                  <div className="flex items-center justify-between mb-1">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium capitalize ${CHANNEL_LABEL_COLORS[ch] || 'text-gray-700 bg-gray-100'}`}>
                      {ch}
                    </span>
                    <span className="text-sm font-semibold text-gray-900">{pct}%</span>
                  </div>
                  <div className="w-full bg-gray-100 rounded-full h-2">
                    <div className={`${barColor} h-2 rounded-full transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
                  </div>
                </div>
              )
            })}
          </div>

          {/* HiD signals */}
          {suggestion.hid_signals_used?.length > 0 && (
            <div className="mt-4 pt-4 border-t border-gray-100">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Hotel signals used</p>
              <ul className="space-y-1">
                {suggestion.hid_signals_used.map((s, i) => (
                  <li key={i} className="text-xs text-gray-500 flex items-start gap-1.5">
                    <CheckCircle className="w-3 h-3 text-green-400 mt-0.5 flex-shrink-0" />
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Column 2: TA + Country focus */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Focus by Channel</p>
          <div className="space-y-4">
            {channels.map(ch => {
              const tas = suggestion.ta_focus?.[ch] || []
              const countries = suggestion.country_focus?.[ch] || []
              if (!tas.length && !countries.length) return null
              return (
                <div key={ch}>
                  <p className={`text-xs font-medium capitalize mb-1.5 ${CHANNEL_LABEL_COLORS[ch] || ''} inline-block px-2 py-0.5 rounded`}>{ch}</p>
                  {tas.length > 0 && (
                    <div className="flex flex-wrap gap-1 mb-1">
                      {tas.map(t => (
                        <span key={t} className="text-xs bg-purple-50 text-purple-700 px-1.5 py-0.5 rounded">{t}</span>
                      ))}
                    </div>
                  )}
                  {countries.length > 0 && (
                    <div className="flex flex-wrap gap-1">
                      {countries.map(c => (
                        <span key={c} className="text-xs bg-orange-50 text-orange-700 px-1.5 py-0.5 rounded font-mono">{c}</span>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Top data highlights */}
          {suggestion.data_highlights?.length > 0 && (
            <div className="mt-4 pt-4 border-t border-gray-100">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Top performers</p>
              <div className="space-y-1">
                {suggestion.data_highlights.slice(0, 4).map((h, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="text-gray-600">
                      <span className="capitalize font-medium">{h.channel}</span>
                      {h.ta !== 'Unknown' && <span className="text-gray-400"> · {h.ta}</span>}
                      {h.country !== 'Unknown' && <span className="text-gray-400"> · {h.country}</span>}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-green-700 font-medium">{h.roas}x</span>
                      <span className="text-gray-400">{h.spend_pct}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Column 3: Rationale */}
        <div>
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Rationale</p>
          <p className="text-sm text-gray-700 leading-relaxed">{suggestion.rationale}</p>

          {suggestion.warnings?.length > 0 && (
            <div className="mt-4 space-y-1.5">
              {suggestion.warnings.map((w, i) => (
                <div key={i} className="flex items-start gap-1.5 bg-yellow-50 rounded px-2.5 py-1.5">
                  <AlertTriangle className="w-3 h-3 text-yellow-500 mt-0.5 flex-shrink-0" />
                  <p className="text-xs text-yellow-800">{w}</p>
                </div>
              ))}
            </div>
          )}

          {suggestion.meta && (
            <p className="mt-4 text-xs text-gray-400">
              Based on {suggestion.meta.perf_rows} ad-group rows
              {suggestion.meta.hid_available ? ' + HiD signals' : ''}.
            </p>
          )}
        </div>
      </div>

      {/* Footer actions */}
      <div className="px-5 py-3 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
        <p className="text-xs text-gray-400">
          <TrendingUp className="w-3 h-3 inline mr-1" />
          Apply fills in the channel % inputs — review and click Save per month to confirm.
        </p>
        <div className="flex gap-2">
          <button onClick={onDismiss}
            className="px-3 py-1.5 text-xs text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-100 transition-colors">
            Dismiss
          </button>
          <button onClick={() => onApply(channelPct)}
            className="px-4 py-1.5 text-xs font-medium bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-1.5">
            <Sparkles className="w-3 h-3" />
            Apply to form
          </button>
        </div>
      </div>
    </div>
  )
}
