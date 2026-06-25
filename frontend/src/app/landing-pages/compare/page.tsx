'use client'

import { Suspense, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { ArrowLeftRight, Trophy, AlertTriangle } from 'lucide-react'
import { API_BASE } from '@/lib/api'
import type { LandingPage, MetricsResponse } from '@/lib/landingPage'

const DAYS = [7, 14, 28, 90]

// Below these volumes the rate metrics are too noisy to trust a verdict.
const MIN_GA4_SESSIONS = 100
const MIN_CONVERSIONS = 10

// ─────────────────────────── formatters ────────────────────────────────────

function fmtNum(n: number | null | undefined, d = 0): string {
  if (n === null || n === undefined) return '—'
  return Number(n).toLocaleString('en-US', { maximumFractionDigits: d })
}
function fmtPct(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined) return '—'
  return `${(Number(n) * 100).toFixed(d)}%`
}
function fmtRoas(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return `${Number(n).toFixed(2)}×`
}
function fmtScroll(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return `${Number(n).toFixed(0)}%`
}

// ─────────────────────────── dimensions ────────────────────────────────────
// `weight` 0 = informational only (not scored — e.g. absolute volume or
// currency-dependent figures that aren't comparable across pages).

type Dim = {
  key: string
  label: string
  hint: string
  get: (m: MetricsResponse) => number | null
  fmt: (v: number | null) => string
  higherBetter: boolean
  weight: number
  primary?: boolean
}

const DIMENSIONS: Dim[] = [
  {
    key: 'dbcr',
    label: 'DBCR (GA4)',
    hint: 'Direct-booking conversion rate — conversions ÷ GA4 sessions. The metric that matters most.',
    get: (m) => m.derived.dbcr_ga4,
    fmt: (v) => fmtPct(v, 2),
    higherBetter: true,
    weight: 3,
    primary: true,
  },
  {
    key: 'roas',
    label: 'ROAS',
    hint: 'Revenue ÷ spend. Ratio, so comparable even across currencies.',
    get: (m) => m.ads.totals.roas,
    fmt: fmtRoas,
    higherBetter: true,
    weight: 2,
    primary: true,
  },
  {
    key: 'engagement',
    label: 'Engagement rate',
    hint: 'GA4 engaged sessions ÷ sessions. Info only — a fast click-through to the booking engine reads as not-engaged, so it is not scored.',
    get: (m) => m.ga4.engagement_rate,
    fmt: (v) => fmtPct(v, 1),
    higherBetter: true,
    weight: 0,
  },
  {
    key: 'bounce',
    label: 'Bounce rate',
    hint: 'GA4 bounce rate. Info only — a fast hop to the booking engine looks like a bounce, which is the goal here, so it is not scored.',
    get: (m) => m.ga4.bounce_rate,
    fmt: (v) => fmtPct(v, 1),
    higherBetter: false,
    weight: 0,
  },
  {
    key: 'lpv_session',
    label: 'LPV → GA4 session',
    hint: 'GA4 sessions ÷ Meta landing-page-views — page-load honesty.',
    get: (m) => m.derived.reconciliation.ga4_vs_meta_lpv ?? null,
    fmt: (v) => fmtPct(v, 1),
    higherBetter: true,
    weight: 1,
  },
  {
    key: 'scroll',
    label: 'Avg scroll depth',
    hint: 'Clarity — how far visitors scroll. Info only — a visitor convinced quickly scrolls little, so it is not scored.',
    get: (m) => m.clarity.avg_scroll_depth,
    fmt: fmtScroll,
    higherBetter: true,
    weight: 0,
  },
  {
    key: 'rage',
    label: 'Rage-click rate',
    hint: 'Clarity UX-bug smoke detector — lower is better.',
    get: (m) => m.clarity.rage_rate,
    fmt: (v) => fmtPct(v, 2),
    higherBetter: false,
    weight: 1,
  },
  // Informational (not scored): absolute / currency-dependent figures.
  {
    key: 'conversions',
    label: 'Conversions',
    hint: 'Absolute volume — depends on budget, not scored.',
    get: (m) => m.ads.totals.conversions,
    fmt: (v) => fmtNum(v, 0),
    higherBetter: true,
    weight: 0,
  },
  {
    key: 'sessions',
    label: 'GA4 sessions',
    hint: 'Traffic volume — sample size for the rates above.',
    get: (m) => m.ga4.sessions,
    fmt: (v) => fmtNum(v, 0),
    higherBetter: true,
    weight: 0,
  },
]

const EPS = 1e-9

/** Winner of a single dimension: 'a' | 'b' | 'tie' | null (missing data). */
function dimWinner(d: Dim, ma: MetricsResponse, mb: MetricsResponse): 'a' | 'b' | 'tie' | null {
  const va = d.get(ma)
  const vb = d.get(mb)
  if (va === null || va === undefined || vb === null || vb === undefined) return null
  if (Math.abs(va - vb) < EPS) return 'tie'
  const aBetter = d.higherBetter ? va > vb : va < vb
  return aBetter ? 'a' : 'b'
}

type Verdict = {
  winner: 'a' | 'b' | 'tie'
  scoreA: number
  scoreB: number
  lowConfidence: boolean
  reasons: string[] // dims the winner won, label only
  counters: string[] // notable dims the loser won
}

function computeVerdict(ma: MetricsResponse, mb: MetricsResponse): Verdict {
  let scoreA = 0
  let scoreB = 0
  const winsA: Dim[] = []
  const winsB: Dim[] = []
  for (const d of DIMENSIONS) {
    if (d.weight === 0) continue
    const w = dimWinner(d, ma, mb)
    if (w === 'a') { scoreA += d.weight; winsA.push(d) }
    else if (w === 'b') { scoreB += d.weight; winsB.push(d) }
  }
  const winner: 'a' | 'b' | 'tie' = Math.abs(scoreA - scoreB) < EPS ? 'tie' : scoreA > scoreB ? 'a' : 'b'
  const winnerWins = winner === 'a' ? winsA : winner === 'b' ? winsB : []
  const loserWins = winner === 'a' ? winsB : winner === 'b' ? winsA : []
  const lowConfidence =
    Math.min(ma.ga4.sessions, mb.ga4.sessions) < MIN_GA4_SESSIONS ||
    Math.min(ma.ads.totals.conversions, mb.ads.totals.conversions) < MIN_CONVERSIONS

  const byWeight = (a: Dim, b: Dim) => (b.primary ? 1 : 0) - (a.primary ? 1 : 0) || b.weight - a.weight
  return {
    winner,
    scoreA,
    scoreB,
    lowConfidence,
    reasons: [...winnerWins].sort(byWeight).slice(0, 3).map((d) => d.label),
    counters: [...loserWins].sort(byWeight).slice(0, 2).map((d) => d.label),
  }
}

// ─────────────────────────── component ─────────────────────────────────────

function ComparePageInner() {
  const search = useSearchParams()
  const [pages, setPages] = useState<LandingPage[]>([])
  const [idA, setIdA] = useState<string>(search?.get('a') || '')
  const [idB, setIdB] = useState<string>(search?.get('b') || '')
  const [days, setDays] = useState(28)
  const [mA, setMA] = useState<MetricsResponse | null>(null)
  const [mB, setMB] = useState<MetricsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load the page list once for the pickers.
  useEffect(() => {
    fetch(`${API_BASE}/api/landing-pages?limit=200`, { credentials: 'include' })
      .then((r) => r.json())
      .then((j) => { if (j.success) setPages(j.data.items) })
      .catch(() => {})
  }, [])

  // Fetch metrics for both pages whenever the selection or window changes.
  useEffect(() => {
    if (!idA || !idB) { setMA(null); setMB(null); return }
    const dateTo = new Date().toISOString().slice(0, 10)
    const dateFrom = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10)
    const fetchMetrics = (id: string) =>
      fetch(`${API_BASE}/api/landing-pages/${id}/metrics?date_from=${dateFrom}&date_to=${dateTo}`, { credentials: 'include' })
        .then((r) => r.json())

    setLoading(true)
    setError(null)
    Promise.all([fetchMetrics(idA), fetchMetrics(idB)])
      .then(([ra, rb]) => {
        if (ra.success) setMA(ra.data); else setError(ra.error || 'Failed to load page A')
        if (rb.success) setMB(rb.data); else setError(rb.error || 'Failed to load page B')
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [idA, idB, days])

  const pageA = useMemo(() => pages.find((p) => p.id === idA) || null, [pages, idA])
  const pageB = useMemo(() => pages.find((p) => p.id === idB) || null, [pages, idB])
  const verdict = useMemo(() => (mA && mB ? computeVerdict(mA, mB) : null), [mA, mB])

  const bothReady = mA && mB && pageA && pageB
  const currencyMismatch = mA && mB && mA.ads.currency !== mB.ads.currency

  const labelFor = (p: LandingPage) => p.title || `${p.domain}/${p.slug}`

  return (
    <div className="max-w-6xl mx-auto">
      <div className="flex items-start justify-between mb-4">
        <div>
          <Link href="/landing-pages" className="text-xs text-gray-500 hover:underline">&larr; Back to landing pages</Link>
          <h1 className="text-2xl font-bold text-gray-900 mt-1 flex items-center gap-2">
            <ArrowLeftRight className="w-6 h-6 text-blue-600" /> Compare Landing Pages
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Pick two pages — decided by DBCR and ROAS, with LPV→session and rage-clicks as tie-breakers.
            On-page engagement (bounce, engagement, scroll) is shown for context but not scored: a fast
            click-through to the booking engine can look like disengagement.
          </p>
        </div>
        <div className="flex gap-1">
          {DAYS.map((n) => (
            <button
              key={n}
              onClick={() => setDays(n)}
              className={`px-3 py-1.5 text-xs rounded border ${days === n ? 'bg-blue-600 text-white border-blue-600' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
            >
              {n}d
            </button>
          ))}
        </div>
      </div>

      {/* Page pickers */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <PagePicker label="Page A" pages={pages} value={idA} exclude={idB} onChange={setIdA} />
        <PagePicker label="Page B" pages={pages} value={idB} exclude={idA} onChange={setIdB} />
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded mb-4 text-sm">{error}</div>}

      {!idA || !idB ? (
        <div className="bg-white border border-dashed border-gray-300 rounded-lg p-8 text-center text-gray-500">
          Select two landing pages above to compare them.
        </div>
      ) : loading && !bothReady ? (
        <div className="text-gray-500 text-sm">Loading metrics…</div>
      ) : bothReady && verdict ? (
        <>
          {/* Verdict banner */}
          <VerdictBanner
            verdict={verdict}
            nameA={labelFor(pageA!)}
            nameB={labelFor(pageB!)}
          />

          {currencyMismatch && (
            <div className="bg-amber-50 border border-amber-200 text-amber-900 px-4 py-2 rounded mb-4 text-sm flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>
                The two pages report in different currencies ({mA!.ads.currency} vs {mB!.ads.currency}).
                ROAS and the rate metrics are still comparable; absolute spend/revenue/CPA are not — they're shown for reference only.
              </span>
            </div>
          )}

          {/* Side-by-side metric table */}
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-gray-700">Metric</th>
                  <th className="px-4 py-2 text-right font-medium text-gray-700">
                    <span className="inline-flex items-center gap-1">
                      {verdict.winner === 'a' && <Trophy className="w-3.5 h-3.5 text-amber-500" />}
                      A · {labelFor(pageA!)}
                    </span>
                  </th>
                  <th className="px-4 py-2 text-right font-medium text-gray-700">
                    <span className="inline-flex items-center gap-1">
                      {verdict.winner === 'b' && <Trophy className="w-3.5 h-3.5 text-amber-500" />}
                      B · {labelFor(pageB!)}
                    </span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {DIMENSIONS.map((d) => {
                  const w = dimWinner(d, mA!, mB!)
                  const scored = d.weight > 0
                  return (
                    <tr key={d.key} className={d.primary ? 'bg-blue-50/40' : ''}>
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-2">
                          <span className={`font-medium ${d.primary ? 'text-gray-900' : 'text-gray-700'}`}>{d.label}</span>
                          {d.primary && <span className="text-[10px] uppercase tracking-wide text-blue-600 font-semibold">primary</span>}
                          {!scored && <span className="text-[10px] uppercase tracking-wide text-gray-400">info</span>}
                        </div>
                        <p className="text-[11px] text-gray-400 mt-0.5">{d.hint}</p>
                      </td>
                      <Cell value={d.fmt(d.get(mA!))} win={scored && w === 'a'} />
                      <Cell value={d.fmt(d.get(mB!))} win={scored && w === 'b'} />
                    </tr>
                  )
                })}
                <tr className="bg-gray-50 font-semibold">
                  <td className="px-4 py-2 text-gray-700">Weighted score</td>
                  <td className={`px-4 py-2 text-right tabular-nums ${verdict.winner === 'a' ? 'text-emerald-700' : 'text-gray-700'}`}>{verdict.scoreA}</td>
                  <td className={`px-4 py-2 text-right tabular-nums ${verdict.winner === 'b' ? 'text-emerald-700' : 'text-gray-700'}`}>{verdict.scoreB}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="mt-3 flex gap-4 text-xs text-gray-500">
            <Link href={`/landing-pages/${idA}/performance`} className="hover:underline">Full analytics for A →</Link>
            <Link href={`/landing-pages/${idB}/performance`} className="hover:underline">Full analytics for B →</Link>
          </div>
        </>
      ) : null}
    </div>
  )
}

function pickerLabel(p: LandingPage): string {
  const base = p.title || `${p.domain}/${p.slug}`
  return p.ta ? `${base} · ${p.ta}` : base
}

/** Searchable page picker — type to filter by title / domain / slug / TA. */
function PagePicker({
  label, pages, value, exclude, onChange,
}: {
  label: string
  pages: LandingPage[]
  value: string
  exclude: string
  onChange: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [hi, setHi] = useState(0)
  const boxRef = useRef<HTMLDivElement>(null)

  const selected = pages.find((p) => p.id === value) || null
  const list = pages.filter((p) => p.id !== exclude)
  const q = query.trim().toLowerCase()
  const filtered = q
    ? list.filter((p) => pickerLabel(p).toLowerCase().includes(q))
    : list

  // Close on outside click.
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  // Reset the highlight whenever the visible list changes.
  useEffect(() => { setHi(0) }, [query, open])

  const choose = (id: string) => { onChange(id); setOpen(false); setQuery('') }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault(); setOpen(true); setHi((i) => Math.min(i + 1, filtered.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault(); setHi((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault(); const p = filtered[hi]; if (p) choose(p.id)
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div ref={boxRef} className="relative">
      <label className="text-xs text-gray-600 block mb-1 font-medium">{label}</label>
      <div className="relative">
        <input
          type="text"
          role="combobox"
          aria-expanded={open}
          value={open ? query : (selected ? pickerLabel(selected) : '')}
          placeholder={selected ? pickerLabel(selected) : '— search a page —'}
          onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
          onFocus={() => { setOpen(true); setQuery('') }}
          onKeyDown={onKeyDown}
          className="w-full px-3 py-2 pr-8 border border-gray-300 rounded text-sm bg-white"
        />
        {selected && (
          <button
            type="button"
            onClick={() => choose('')}
            aria-label="Clear selection"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 leading-none text-lg"
          >×</button>
        )}
      </div>
      {open && (
        <ul className="absolute z-50 mt-1 w-full max-h-72 overflow-auto bg-white border border-gray-200 rounded-lg shadow-lg py-1">
          {filtered.length === 0 ? (
            <li className="px-3 py-2 text-sm text-gray-400">No pages match “{query}”.</li>
          ) : (
            filtered.map((p, i) => (
              <li key={p.id}>
                <button
                  type="button"
                  onMouseEnter={() => setHi(i)}
                  onClick={() => choose(p.id)}
                  className={`w-full text-left px-3 py-2 text-sm ${i === hi ? 'bg-blue-50' : ''} ${p.id === value ? 'font-semibold text-blue-700' : 'text-gray-700'}`}
                >
                  {pickerLabel(p)}
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}

function Cell({ value, win }: { value: string; win: boolean }) {
  return (
    <td className={`px-4 py-2 text-right tabular-nums ${win ? 'text-emerald-700 font-semibold bg-emerald-50/60' : 'text-gray-700'}`}>
      {value}
    </td>
  )
}

function VerdictBanner({ verdict, nameA, nameB }: { verdict: Verdict; nameA: string; nameB: string }) {
  if (verdict.winner === 'tie') {
    return (
      <div className="bg-gray-50 border border-gray-300 rounded-lg p-4 mb-4">
        <p className="font-semibold text-gray-800">It's a tie ({verdict.scoreA} — {verdict.scoreB}).</p>
        <p className="text-sm text-gray-600 mt-1">
          Neither page is clearly more effective on the weighted metrics. Try a longer window or look at the
          per-metric rows below.
        </p>
      </div>
    )
  }
  const winnerName = verdict.winner === 'a' ? nameA : nameB
  const loserName = verdict.winner === 'a' ? nameB : nameA
  const reason = verdict.reasons.length
    ? `it leads on ${verdict.reasons.join(', ')}`
    : 'it wins more of the weighted metrics'
  const counter = verdict.counters.length
    ? ` ${loserName} still leads on ${verdict.counters.join(', ')}.`
    : ''
  return (
    <div className="bg-emerald-50 border border-emerald-300 rounded-lg p-4 mb-4">
      <p className="font-semibold text-emerald-900 flex items-center gap-2">
        <Trophy className="w-5 h-5 text-amber-500" />
        {winnerName} is the more effective landing page.
      </p>
      <p className="text-sm text-emerald-800 mt-1">
        Weighted score {Math.max(verdict.scoreA, verdict.scoreB)} — {Math.min(verdict.scoreA, verdict.scoreB)}: {reason}.
        {counter}
      </p>
      {verdict.lowConfidence && (
        <p className="text-xs text-amber-800 mt-2 flex items-start gap-1.5">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          Low confidence — one of the pages has thin traffic ({'<'}{MIN_GA4_SESSIONS} GA4 sessions or {'<'}{MIN_CONVERSIONS} conversions)
          in this window. Widen the timeframe before acting on this verdict.
        </p>
      )}
    </div>
  )
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="p-6 text-gray-400">Loading…</div>}>
      <ComparePageInner />
    </Suspense>
  )
}
