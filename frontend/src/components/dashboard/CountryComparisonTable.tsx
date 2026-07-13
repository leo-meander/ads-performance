'use client'

import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react'
import { useSortableRows } from '@/lib/useSortableRows'
import { ChangeTag, fmtMoney } from './dashboardUtils'

export type CountryKpi = {
  country_code: string
  country: string
  total_spend: number
  total_revenue: number
  impressions: number
  clicks: number
  conversions: number
  leads: number
  campaign_count: number
  roas: number
  ctr: number
  cpa: number
  cr: number
  aov: number
  cpc: number
  spend_change: number | null
  revenue_change: number | null
  roas_change: number | null
  ctr_change: number | null
  cpa_change: number | null
  cr_change: number | null
  aov_change: number | null
  cpc_change: number | null
  conversions_change: number | null
}

export default function CountryComparisonTable({
  rows,
  currency,
  selectedCountry,
  onSelectCountry,
}: {
  rows: CountryKpi[]
  currency: string
  selectedCountry: string
  onSelectCountry: (code: string) => void
}) {
  const { sorted, sortBy, sortDir, toggleSort } = useSortableRows<CountryKpi>(rows)

  const Th = ({ col, label, align = 'right' }: { col: keyof CountryKpi; label: string; align?: 'left' | 'right' }) => {
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
        <h2 className="text-sm font-semibold text-gray-700">By Country</h2>
        <span className="text-[11px] text-gray-400">Click row to filter</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              <Th col="country" label="Country" align="left" />
              <Th col="total_spend" label={`Spend (${currency})`} />
              <Th col="total_revenue" label={`Revenue (${currency})`} />
              <Th col="roas" label="ROAS" />
              <Th col="ctr" label="CTR" />
              <Th col="cpa" label={`CPA (${currency})`} />
              <Th col="conversions" label="Conversions" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const isActive = selectedCountry === row.country_code
              return (
                <tr
                  key={row.country_code}
                  onClick={() => onSelectCountry(isActive ? '' : row.country_code)}
                  className={`border-b border-gray-50 cursor-pointer transition-colors ${
                    isActive ? 'bg-blue-50 ring-2 ring-inset ring-blue-300' : 'hover:bg-gray-50'
                  }`}
                  title={isActive ? 'Click to clear country filter' : `Filter by ${row.country}`}
                >
                  <td className="py-3 px-4">
                    <span className={`font-medium ${isActive ? 'text-blue-700' : 'text-gray-900'}`}>{row.country}</span>
                    <span className="text-xs text-gray-400 ml-1">({row.country_code})</span>
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div>{fmtMoney(row.total_spend, currency)}</div>
                    <ChangeTag change={row.spend_change} inverseColor />
                  </td>
                  <td className="py-3 px-4 text-right">{fmtMoney(row.total_revenue, currency)}</td>
                  <td className="py-3 px-4 text-right">
                    <div className={`font-medium ${row.roas >= 1 ? 'text-green-600' : 'text-red-600'}`}>{row.roas.toFixed(2)}x</div>
                    <ChangeTag change={row.roas_change} />
                  </td>
                  <td className="py-3 px-4 text-right">{row.ctr.toFixed(1)}%</td>
                  <td className="py-3 px-4 text-right">{fmtMoney(Math.round(row.cpa), currency)}</td>
                  <td className="py-3 px-4 text-right">
                    <div>{row.conversions}</div>
                    <ChangeTag change={row.conversions_change} />
                  </td>
                </tr>
              )
            })}
            {sorted.length === 0 && (
              <tr><td colSpan={7} className="py-8 text-center text-gray-400">No country data.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
