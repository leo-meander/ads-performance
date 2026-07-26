'use client'

import { TrendingUp, TrendingDown } from 'lucide-react'
import { formatLocalDate } from '@/lib/dates'

export const CURRENCY_SYMBOLS: Record<string, string> = {
  VND: '₫', TWD: 'NT$', JPY: '¥', USD: '$',
}

export function fmtMoney(n: number, currency: string): string {
  const symbol = CURRENCY_SYMBOLS[currency] || currency
  return `${new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(n)} ${symbol}`
}

export function fmtNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 0 }).format(n)
}

// inverseColor: true = "increase is bad" (cost, cpc, cpa, drop-off)
export function ChangeTag({ change, inverseColor = false }: { change: number | null | undefined; inverseColor?: boolean }) {
  if (change === null || change === undefined) return <span className="text-xs text-gray-400">--</span>
  const pct = change * 100
  if (Math.abs(pct) < 0.01) return <span className="text-xs text-gray-400">0%</span>
  const pos = pct > 0
  const isGood = inverseColor ? !pos : pos
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-medium ${isGood ? 'text-green-600' : 'text-red-500'}`}>
      {pos ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
      {pos ? '+' : ''}{pct.toFixed(1)}%
    </span>
  )
}

// Period-over-period move of a drop-off RATE, in percentage points — not the
// change of the underlying count. Higher drop-off is always worse, so an
// increase renders red regardless of what happened to the raw volume.
export function DropOffDeltaTag({ current, prev }: { current: number | null | undefined; prev: number | null | undefined }) {
  if (current === null || current === undefined || prev === null || prev === undefined) {
    return <span className="text-xs text-gray-400" title="No previous-period drop-off to compare">--</span>
  }
  const pp = (current - prev) * 100
  const tip = `Drop-off ${(prev * 100).toFixed(1)}% → ${(current * 100).toFixed(1)}% vs previous period (${pp >= 0 ? '+' : ''}${pp.toFixed(1)} percentage points). Up = worse.`
  if (Math.abs(pp) < 0.05) return <span className="text-xs text-gray-400" title={tip}>0pp</span>
  const worse = pp > 0
  return (
    <span title={tip} className={`inline-flex items-center gap-0.5 text-xs font-medium ${worse ? 'text-red-500' : 'text-green-600'}`}>
      {worse ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
      {worse ? '+' : ''}{pp.toFixed(1)}pp
    </span>
  )
}

export function getDateRange(preset: string): { from: string; to: string } {
  const today = new Date()
  const to = formatLocalDate(today)
  const daysBack = (d: number) => {
    const dt = new Date(today)
    dt.setDate(dt.getDate() - d)
    return formatLocalDate(dt)
  }
  switch (preset) {
    case 'today': return { from: to, to }
    case 'yesterday': {
      const y = daysBack(1)
      return { from: y, to: y }
    }
    case '7d': return { from: daysBack(6), to }
    case '14d': return { from: daysBack(13), to }
    case '30d': return { from: daysBack(29), to }
    case 'this_month': {
      const from = formatLocalDate(new Date(today.getFullYear(), today.getMonth(), 1))
      return { from, to }
    }
    case 'last_month': {
      const from = formatLocalDate(new Date(today.getFullYear(), today.getMonth() - 1, 1))
      const last = formatLocalDate(new Date(today.getFullYear(), today.getMonth(), 0))
      return { from, to: last }
    }
    default: return { from: daysBack(6), to }
  }
}

export const DATE_PRESETS: Array<{ value: string; label: string }> = [
  { value: 'today', label: 'Today' },
  { value: 'yesterday', label: 'Yesterday' },
  { value: '7d', label: 'Last 7 days' },
  { value: '14d', label: 'Last 14 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: 'this_month', label: 'This month' },
  { value: 'last_month', label: 'Last month' },
  { value: 'custom', label: 'Custom range' },
]

export const FUNNEL_STAGE_PILL: Record<string, string> = {
  TOF: 'bg-blue-100 text-blue-700',
  MOF: 'bg-amber-100 text-amber-700',
  BOF: 'bg-green-100 text-green-700',
  Unknown: 'bg-gray-100 text-gray-700',
}

export const PLATFORM_PILL: Record<string, string> = {
  meta: 'bg-blue-50 text-blue-700',
  google: 'bg-green-50 text-green-700',
  tiktok: 'bg-pink-50 text-pink-700',
}
