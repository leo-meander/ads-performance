'use client'

import { useEffect, useRef } from 'react'
import { ArrowUp, ArrowDown, ArrowUpDown, Sparkles } from 'lucide-react'
import { useSortableRows } from '@/lib/useSortableRows'
import { ChangeTag, fmtMoney, FUNNEL_STAGE_PILL } from './dashboardUtils'

export type CampaignRow = {
  campaign_id: string
  campaign_name: string
  campaign_status: string
  funnel_stage: string | null
  ta: string | null
  platform: string
  // account_id + daily_budget added for the SURF Apply modal on /action-needed.
  // account_id may be null on historical rows whose Campaign.account_id is
  // unresolved; daily_budget is null when the budget lives at ad-set level.
  account_id: string | null
  daily_budget: number | null
  account_name: string
  spend: number
  revenue: number
  impressions: number
  clicks: number
  conversions: number
  roas: number
  ctr: number
  cpc: number
  cpa: number
  cr: number
  aov: number
  spend_change: number | null
  roas_change: number | null
  cr_change: number | null
  aov_change: number | null
  cpc_change: number | null
  conversions_change: number | null
}

export default function CampaignBreakdownTable({
  rows, currency, highlightId, title,
}: {
  rows: CampaignRow[]
  currency: string
  highlightId: string
  title: string
}) {
  const { sorted, sortBy, sortDir, toggleSort } = useSortableRows<CampaignRow>(rows, 'spend', 'desc')
  const ordered = highlightId
    ? [
      ...sorted.filter(r => r.campaign_id === highlightId),
      ...sorted.filter(r => r.campaign_id !== highlightId),
    ]
    : sorted
  const highlightRef = useRef<HTMLTableRowElement>(null)
  useEffect(() => {
    if (highlightId && highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [highlightId, rows.length])

  const Th = ({ col, label, align = 'right' }: { col: keyof CampaignRow; label: string; align?: 'left' | 'right' }) => {
    const active = sortBy === col
    return (
      <th
        className={`${align === 'right' ? 'text-right' : 'text-left'} py-3 px-4 text-gray-500 font-medium cursor-pointer select-none hover:text-gray-700`}
        onClick={() => toggleSort(col)}
      >
        <span className={`inline-flex items-center gap-1 ${align === 'right' ? 'justify-end w-full' : ''}`}>
          {label}
          {active
            ? (sortDir === 'asc' ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)
            : <ArrowUpDown className="w-3 h-3 opacity-40" />}
        </span>
      </th>
    )
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="px-6 py-4 border-b flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700">{title}</h2>
        <span className="text-[11px] text-gray-400">ROAS = CR × AOV / CPC</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              <Th col="campaign_name" label="Campaign" align="left" />
              <Th col="funnel_stage" label="Funnel" align="left" />
              <Th col="spend" label={`Spend (${currency})`} />
              <Th col="revenue" label={`Revenue (${currency})`} />
              <Th col="roas" label="ROAS" />
              <Th col="cr" label="CR" />
              <Th col="aov" label={`AOV (${currency})`} />
              <Th col="cpc" label={`CPC (${currency})`} />
              <Th col="conversions" label="Conv" />
            </tr>
          </thead>
          <tbody>
            {ordered.map(row => {
              const isHighlight = row.campaign_id === highlightId
              return (
                <tr
                  key={row.campaign_id}
                  ref={isHighlight ? highlightRef : null}
                  className={`border-b border-gray-50 ${
                    isHighlight ? 'bg-blue-50 ring-2 ring-inset ring-blue-300' : 'hover:bg-gray-50'
                  }`}
                >
                  <td className="py-3 px-4">
                    <div className="flex items-center gap-2">
                      {isHighlight && (
                        <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-blue-700 bg-blue-100 px-1.5 py-0.5 rounded">
                          <Sparkles className="w-3 h-3" /> from rec
                        </span>
                      )}
                      <span className="font-medium text-gray-900 break-words" title={row.campaign_name}>
                        {row.campaign_name}
                      </span>
                    </div>
                    <div className="text-[11px] text-gray-400 mt-0.5">
                      {[row.account_name, row.platform, row.ta].filter(Boolean).join(' · ')}
                    </div>
                  </td>
                  <td className="py-3 px-4">
                    {row.funnel_stage && (
                      <span className={`text-xs px-2 py-0.5 rounded-full ${FUNNEL_STAGE_PILL[row.funnel_stage] || FUNNEL_STAGE_PILL.Unknown}`}>
                        {row.funnel_stage}
                      </span>
                    )}
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div>{fmtMoney(row.spend, currency)}</div>
                    <ChangeTag change={row.spend_change} inverseColor />
                  </td>
                  <td className="py-3 px-4 text-right">{fmtMoney(row.revenue, currency)}</td>
                  <td className="py-3 px-4 text-right">
                    <div className={`font-medium ${row.roas >= 1 ? 'text-green-600' : 'text-red-600'}`}>
                      {row.roas.toFixed(2)}x
                    </div>
                    <ChangeTag change={row.roas_change} />
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div>{row.cr.toFixed(2)}%</div>
                    <ChangeTag change={row.cr_change} />
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div>{row.aov ? fmtMoney(Math.round(row.aov), currency) : '--'}</div>
                    <ChangeTag change={row.aov_change} />
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div>{row.cpc ? fmtMoney(Math.round(row.cpc), currency) : '--'}</div>
                    <ChangeTag change={row.cpc_change} inverseColor />
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div>{row.conversions}</div>
                    <ChangeTag change={row.conversions_change} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
