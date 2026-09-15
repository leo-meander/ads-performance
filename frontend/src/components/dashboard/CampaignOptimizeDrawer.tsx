'use client'

import { useEffect } from 'react'
import { AlertTriangle, CheckCircle2, HelpCircle, Minus, TrendingDown, X } from 'lucide-react'
import { ChangeTag, fmtMoney, FUNNEL_STAGE_PILL } from './dashboardUtils'
import { diagnoseCampaign, fmtLever, type Lever, type LeverStatus } from './campaignOptimizer'
import type { CampaignRow } from './CampaignBreakdownTable'

const STATUS_CHIP: Record<LeverStatus, string> = {
  drag: 'bg-red-50 text-red-700 border-red-200',
  par: 'bg-gray-50 text-gray-500 border-gray-200',
  strength: 'bg-green-50 text-green-700 border-green-200',
  thin: 'bg-amber-50 text-amber-700 border-amber-200',
  blind: 'bg-gray-50 text-gray-400 border-gray-200',
}

const STATUS_LABEL: Record<LeverStatus, string> = {
  drag: 'Fix this',
  par: 'At par',
  strength: 'Working',
  thin: 'Too thin to judge',
  blind: 'No benchmark',
}

const STATUS_ICON: Record<LeverStatus, typeof Minus> = {
  drag: TrendingDown,
  par: Minus,
  strength: CheckCircle2,
  thin: HelpCircle,
  blind: HelpCircle,
}

export default function CampaignOptimizeDrawer({
  row, rows, currency, onClose,
}: {
  row: CampaignRow
  /** Every row in the current view — the benchmark this campaign is read against. */
  rows: CampaignRow[]
  currency: string
  onClose: () => void
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])

  const money = (n: number) => fmtMoney(n, currency)
  const d = diagnoseCampaign(row, rows, money)
  const num = (n: number) => (n || 0).toLocaleString('en-US')

  const stat = (label: string, value: string) => (
    <div className="bg-gray-50 rounded-lg p-2">
      <p className="text-[10px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-sm font-bold text-gray-900">{value}</p>
    </div>
  )

  const leverCard = (l: Lever) => {
    const Icon = STATUS_ICON[l.status]
    return (
      <div
        key={l.key}
        className={`rounded-lg border p-3 ${l.status === 'drag' ? 'border-red-200 bg-red-50/40' : 'border-gray-200 bg-white'}`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-bold text-gray-900">{l.label}</span>
            <span className={`inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${STATUS_CHIP[l.status]}`}>
              <Icon className="w-3 h-3" /> {STATUS_LABEL[l.status]}
            </span>
          </div>
          <div className="text-right shrink-0">
            <div className="text-sm font-semibold text-gray-900">{fmtLever(l.key, l.value, money)}</div>
            <ChangeTag change={l.change} inverseColor={l.key === 'cpm'} />
          </div>
        </div>

        {l.peer != null && (
          <p className="text-[11px] text-gray-400 mt-1">
            {d.peers.label} median: {fmtLever(l.key, l.peer, money)}
          </p>
        )}

        <p className="text-xs text-gray-700 mt-1.5 leading-relaxed">{l.why}</p>

        {l.projectedRoas != null && (
          <p className="text-[11px] text-red-700 mt-1.5 font-medium">
            Close this gap alone → ROAS {row.roas.toFixed(2)}x becomes {l.projectedRoas.toFixed(2)}x
          </p>
        )}

        {l.fixes.length > 0 && (
          <ul className="mt-2 space-y-1">
            {l.fixes.map((f, i) => (
              <li key={i} className="text-xs text-gray-700 flex gap-1.5">
                <span className="text-blue-400 shrink-0">→</span>
                <span>{f}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-40" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`How to optimise ${row.campaign_name}`}
        className="fixed top-0 right-0 h-full w-full max-w-md bg-white z-50 shadow-2xl flex flex-col"
      >
        <div className="flex items-start justify-between p-4 border-b border-gray-100">
          <div className="min-w-0">
            <p className="text-sm font-bold text-gray-900 break-words">{row.campaign_name}</p>
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              {row.funnel_stage && (
                <span className={`text-[10px] px-2 py-0.5 rounded-full ${FUNNEL_STAGE_PILL[row.funnel_stage] || FUNNEL_STAGE_PILL.Unknown}`}>
                  {row.funnel_stage}
                </span>
              )}
              <span className="text-[11px] text-gray-400">
                {[row.account_name, row.platform, row.ta].filter(Boolean).join(' · ')}
              </span>
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" className="p-1 rounded hover:bg-gray-100 text-gray-400 shrink-0">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {/* What this campaign did, so the diagnosis below can be weighed. */}
          <div className="grid grid-cols-4 gap-2">
            {stat('ROAS', `${row.roas.toFixed(2)}x`)}
            {stat('Spend', money(row.spend))}
            {stat('Clicks', num(row.clicks))}
            {stat('Bookings', num(row.conversions))}
          </div>

          <section>
            <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">What to fix first</h3>
            <p className="text-sm text-gray-800 leading-relaxed">{d.headline}</p>

            {d.blocker && (
              <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
                <p className="text-xs font-semibold text-amber-900 inline-flex items-center gap-1.5">
                  <AlertTriangle className="w-3.5 h-3.5" /> {d.blocker.title}
                </p>
                <ul className="mt-2 space-y-1">
                  {d.blocker.fixes.map((f, i) => (
                    <li key={i} className="text-xs text-amber-900 flex gap-1.5">
                      <span className="shrink-0">→</span><span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

          </section>

          {/* The identity the whole panel is reasoning from, with real numbers
              substituted, so the ranking below can be checked by hand. */}
          <section>
            <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">How this ROAS is built</h3>
            <div className="bg-gray-50 rounded-lg p-3 text-[11px] text-gray-600 leading-relaxed">
              <span className="font-semibold text-gray-900">{row.roas.toFixed(2)}x</span>
              {' = CTR '}{row.ctr.toFixed(2)}%
              {' × CR '}{row.cr.toFixed(2)}%
              {' × AOV '}{money(Math.round(row.aov))}
              {' / (10 × CPM '}{money(Math.round(row.cpm))}{')'}
              <p className="mt-1 text-gray-400">
                Move one of the four and ROAS moves with it. The cards below rank them by how far each sits from what
                comparable campaigns already do. Projections hold the other three still — in practice they trade off,
                since looser targeting lifts CTR and usually costs CR.
              </p>
            </div>
          </section>

          <section>
            <h3 className="text-xs font-semibold text-gray-700 uppercase tracking-wide mb-2">The four levers</h3>
            <div className="space-y-2">{d.levers.map(leverCard)}</div>
          </section>

          {d.peers.count > 0 && (
            <p className="text-[11px] text-gray-400 leading-relaxed">
              Benchmarked against the {d.peers.count} other {d.peers.label}{' '}
              {d.peers.count === 1 ? 'campaign' : 'campaigns'} in the current filter and date range — not an
              account-wide or all-time average. Change the filters above and these medians move with them.
            </p>
          )}
        </div>
      </div>
    </>
  )
}
