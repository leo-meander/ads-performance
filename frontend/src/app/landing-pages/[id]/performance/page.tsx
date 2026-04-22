'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { API_BASE } from '@/lib/api'
import type { LandingPage, MetricsResponse } from '@/lib/landingPage'

type UtmRow = {
  utm_source: string | null
  utm_campaign: string | null
  utm_content: string | null
  sessions: number
  distinct_users: number
  avg_scroll_depth: number | null
  rage_clicks: number
  dead_clicks: number
  quickback_clicks: number
  total_time_sec: number
  active_time_sec: number
}

const DAYS = [7, 14, 28, 90]

function fmtNum(n: number | null | undefined, d = 0): string {
  if (n === null || n === undefined) return '—'
  return Number(n).toLocaleString('en-US', { maximumFractionDigits: d })
}

function fmtPct(n: number | null | undefined, d = 2): string {
  if (n === null || n === undefined) return '—'
  return `${(Number(n) * 100).toFixed(d)}%`
}

function fmtDur(sec: number | null | undefined): string {
  if (!sec) return '—'
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  if (m < 60) return `${m}m ${s}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

export default function LandingPagePerformance() {
  const params = useParams()
  const pageId = params.id as string

  const [page, setPage] = useState<LandingPage | null>(null)
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null)
  const [utmBreakdown, setUtmBreakdown] = useState<UtmRow[]>([])
  const [days, setDays] = useState(7)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const dateTo = new Date().toISOString().slice(0, 10)
    const dateFrom = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10)

    const load = async () => {
      setLoading(true)
      setError(null)
      try {
        const [pRes, mRes, uRes] = await Promise.all([
          fetch(`${API_BASE}/api/landing-pages/${pageId}`, { credentials: 'include' }).then((r) => r.json()),
          fetch(`${API_BASE}/api/landing-pages/${pageId}/metrics?date_from=${dateFrom}&date_to=${dateTo}`, { credentials: 'include' }).then((r) => r.json()),
          fetch(`${API_BASE}/api/landing-pages/${pageId}/metrics/by-utm?date_from=${dateFrom}&date_to=${dateTo}`, { credentials: 'include' }).then((r) => r.json()),
        ])
        if (pRes.success) setPage(pRes.data)
        if (mRes.success) setMetrics(mRes.data)
        if (uRes.success) setUtmBreakdown(uRes.data || [])
        if (!pRes.success || !mRes.success) setError(pRes.error || mRes.error)
      } catch (e) {
        setError(String(e))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [pageId, days])

  if (loading && !metrics) return <div className="text-gray-500">Loading…</div>
  if (!page) return <div className="text-red-600">Not found</div>

  const a = metrics?.ads.totals
  const c = metrics?.clarity
  const g = metrics?.ga4
  const d = metrics?.derived

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex items-start justify-between mb-4">
        <div>
          <Link href={`/landing-pages/${pageId}`} className="text-xs text-gray-500 hover:underline">&larr; Back to page</Link>
          <h1 className="text-2xl font-bold text-gray-900 mt-1">Analytics — {page.title}</h1>
          <p className="text-sm text-gray-500 mt-1 font-mono">{page.domain}/{page.slug}</p>
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

      {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded mb-4 text-sm">{error}</div>}

      {/* Clarity data-coverage warning — appears when the selected window is
          wider than what we've synced so far. */}
      {metrics && !metrics.clarity_coverage.is_complete && (
        <div className="bg-amber-50 border border-amber-200 text-amber-900 px-4 py-2.5 rounded mb-4 text-sm flex items-start gap-2">
          <span className="text-amber-600 font-bold">⚠</span>
          <div>
            <strong>Incomplete Clarity data.</strong>{' '}
            Showing {metrics.clarity_coverage.days_with_data}/{metrics.clarity_coverage.requested_days} days in the selected range
            {metrics.clarity_coverage.latest_synced_date && (<> · last synced {new Date(metrics.clarity_coverage.latest_synced_date).toLocaleDateString()}</>)}.
            Clarity numbers will look low until the daily cron fills in the gap.
            Compare against <strong>LPV → Session</strong> below for a same-window view.
          </div>
        </div>
      )}

      {/* DBCR hero row — playbook §1.2 "the one metric that matters".
          Use GA4 as the independent denominator since it's the 3rd-party count. */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        <BigStat label="DBCR (GA4)" value={fmtPct(d?.dbcr_ga4, 2)} hint="Conversions ÷ GA4 sessions" tone={dbcrTone(d?.dbcr_ga4)} />
        <BigStat label="LPV → GA4 Session" value={fmtPct(d?.reconciliation?.ga4_vs_meta_lpv, 1)} hint="Meta LPV honesty check — low = Meta inflates" tone={lpvToSessionTone(d?.reconciliation?.ga4_vs_meta_lpv)} />
        <BigStat label="ROAS" value={a?.roas ? `${a.roas.toFixed(2)}×` : '—'} hint="Revenue ÷ Spend" tone="neutral" />
        <BigStat label="Rage click rate" value={fmtPct(c?.rage_rate, 2)} hint="UX-bug smoke detector" tone={rageTone(c?.rage_rate)} />
      </div>

      {/* Cross-source reconciliation — the 3-way truth check */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-900 mb-2">Cross-source reconciliation</h2>
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500">
                <th className="text-left font-normal pb-1.5">Source</th>
                <th className="text-right font-normal pb-1.5">Count</th>
                <th className="text-left font-normal pb-1.5 pl-4">Ratio</th>
                <th className="text-left font-normal pb-1.5">Interpretation</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              <tr><td className="py-2">Meta <strong>clicks</strong></td><td className="text-right font-mono">{fmtNum(a?.clicks)}</td><td className="pl-4 text-gray-400">—</td><td className="text-gray-500 text-xs">Counts all ad interactions (likes, video plays, profile taps…)</td></tr>
              <tr><td className="py-2">Meta <strong>landing page views</strong></td><td className="text-right font-mono">{fmtNum(a?.landing_page_views)}</td><td className="pl-4 font-mono">{fmtPct((a?.landing_page_views || 0) / (a?.clicks || 1), 1)}</td><td className="text-gray-500 text-xs">Meta's own page-load count — 25-30% of clicks is normal</td></tr>
              <tr className="bg-amber-50/50"><td className="py-2">GA4 <strong>sessions</strong></td><td className="text-right font-mono">{fmtNum(g?.sessions)}</td><td className="pl-4 font-mono">{fmtPct(d?.reconciliation?.ga4_vs_meta_lpv, 1)}</td><td className="text-gray-500 text-xs">Independent count — if &lt;60% of Meta LPV → Meta over-reports</td></tr>
              <tr><td className="py-2">Clarity <strong>sessions</strong></td><td className="text-right font-mono">{fmtNum(c?.sessions)}</td><td className="pl-4 font-mono">{fmtPct(d?.reconciliation?.clarity_vs_ga4, 1)}</td><td className="text-gray-500 text-xs">vs GA4 — 60-80% normal (ad-blockers, slow loads)</td></tr>
              <tr><td className="py-2">Ad <strong>conversions</strong></td><td className="text-right font-mono">{fmtNum(a?.conversions)}</td><td className="pl-4 text-gray-400">—</td><td className="text-gray-500 text-xs">Pixel-attributed purchases</td></tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* Ads card */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-900 mb-2">Ad Performance (all linked campaigns)</h2>
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          {metrics && metrics.ads.campaign_count === 0 ? (
            <p className="text-sm text-gray-500">No linked campaigns yet. Run <strong>Import from Ads</strong> on the list page, or link campaigns manually via the editor.</p>
          ) : (
            <div className="grid grid-cols-6 gap-4 text-sm">
              <Stat label="Spend" value={fmtNum(a?.spend, 0)} />
              <Stat label="Impressions" value={fmtNum(a?.impressions)} />
              <Stat label="Clicks" value={fmtNum(a?.clicks)} />
              <Stat label="Landing page views" value={fmtNum(a?.landing_page_views)} />
              <Stat label="Conversions" value={fmtNum(a?.conversions)} />
              <Stat label="Revenue" value={fmtNum(a?.revenue, 0)} />
              <Stat label="CTR" value={fmtPct(a?.ctr, 2)} />
              <Stat label="CPC" value={fmtNum(a?.cpc, 2)} />
              <Stat label="CPA" value={fmtNum(a?.cpa, 0)} />
              <Stat label="Campaigns linked" value={fmtNum(metrics?.ads.campaign_count)} />
            </div>
          )}
          {metrics && Object.keys(metrics.ads.by_platform).length > 1 && (
            <div className="mt-4 border-t border-gray-100 pt-4">
              <p className="text-xs font-medium text-gray-600 mb-2">By platform</p>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-gray-500">
                    <th className="text-left font-normal pb-1">Platform</th>
                    <th className="text-right font-normal pb-1">Spend</th>
                    <th className="text-right font-normal pb-1">Clicks</th>
                    <th className="text-right font-normal pb-1">Conv</th>
                    <th className="text-right font-normal pb-1">ROAS</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(metrics.ads.by_platform).map(([plat, row]) => (
                    <tr key={plat}>
                      <td className="capitalize">{plat}</td>
                      <td className="text-right">{fmtNum(row.spend, 0)}</td>
                      <td className="text-right">{fmtNum(row.clicks)}</td>
                      <td className="text-right">{fmtNum(row.conversions)}</td>
                      <td className="text-right">{row.roas ? `${row.roas.toFixed(2)}×` : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {/* GA4 card */}
      <section className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-gray-900">Google Analytics 4 — independent traffic & engagement</h2>
          {metrics && !metrics.ga4_coverage.is_complete && (
            <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-0.5">
              {metrics.ga4_coverage.days_with_data}/{metrics.ga4_coverage.requested_days} days synced
            </span>
          )}
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4 grid grid-cols-6 gap-4 text-sm">
          <Stat label="Sessions" value={fmtNum(g?.sessions)} />
          <Stat label="Engaged sessions" value={fmtNum(g?.engaged_sessions)} />
          <Stat label="Engagement rate" value={fmtPct(g?.engagement_rate, 1)} tone={engagementTone(g?.engagement_rate)} />
          <Stat label="Active users" value={fmtNum(g?.active_users)} />
          <Stat label="New users" value={fmtNum(g?.new_users)} />
          <Stat label="Page views" value={fmtNum(g?.page_views)} />
          <Stat label="Avg session duration" value={g?.avg_session_duration_sec ? fmtDur(Math.round(g.avg_session_duration_sec)) : '—'} />
          <Stat label="Bounce rate" value={fmtPct(g?.bounce_rate, 1)} tone={bounceTone(g?.bounce_rate)} />
        </div>

        {/* Web Vitals — playbook §5.3 pass/fail gauges */}
        {(g?.web_vitals?.lcp_p75_ms || g?.web_vitals?.inp_p75_ms || g?.web_vitals?.cls_p75 !== null) ? (
          <div className="mt-3 bg-white border border-gray-200 rounded-lg p-4">
            <p className="text-xs font-medium text-gray-700 mb-2">Core Web Vitals (p75) — playbook §5.3 thresholds</p>
            <div className="grid grid-cols-4 gap-3">
              <VitalStat label="LCP" value={g?.web_vitals?.lcp_p75_ms ? `${(g.web_vitals.lcp_p75_ms / 1000).toFixed(2)}s` : '—'} pass={g?.web_vitals?.lcp_pass} threshold="<1.8s ideal, <2.5s pass" />
              <VitalStat label="INP" value={g?.web_vitals?.inp_p75_ms ? `${g.web_vitals.inp_p75_ms}ms` : '—'} pass={g?.web_vitals?.inp_pass} threshold="<100ms ideal, <200ms pass" />
              <VitalStat label="CLS" value={g?.web_vitals?.cls_p75 != null ? g.web_vitals.cls_p75.toFixed(3) : '—'} pass={g?.web_vitals?.cls_pass} threshold="<0.1 pass" />
              <VitalStat label="FCP" value={g?.web_vitals?.fcp_p75_ms ? `${(g.web_vitals.fcp_p75_ms / 1000).toFixed(2)}s` : '—'} pass={undefined} threshold="First Contentful Paint" />
            </div>
          </div>
        ) : (
          <p className="mt-2 text-xs text-gray-500 italic">
            Web Vitals not available — install the <a className="underline" href="https://developers.google.com/tag-platform/gtagjs/reference/web-vitals" target="_blank" rel="noreferrer">web-vitals.js</a> library on the landing page to start collecting LCP/INP/CLS metrics.
          </p>
        )}
      </section>

      {/* Clarity card */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-900 mb-2">Microsoft Clarity — UX signals</h2>
        <div className="bg-white border border-gray-200 rounded-lg p-4 grid grid-cols-6 gap-4 text-sm">
          <Stat label="Sessions" value={fmtNum(c?.sessions)} />
          <Stat label="Distinct users" value={fmtNum(c?.distinct_users)} />
          <Stat label="Avg scroll depth" value={c?.avg_scroll_depth !== null && c?.avg_scroll_depth !== undefined ? `${c.avg_scroll_depth.toFixed(1)}%` : '—'} tone={scrollTone(c?.avg_scroll_depth)} />
          <Stat label="Total time on page" value={fmtDur(c?.total_time_sec)} />
          <Stat label="Active time" value={fmtDur(c?.active_time_sec)} />
          <Stat label="Pages / session" value="—" />
          <Stat label="Rage clicks" value={fmtNum(c?.rage_clicks)} tone={c?.rage_clicks ? 'bad' : 'good'} />
          <Stat label="Dead clicks" value={fmtNum(c?.dead_clicks)} tone={c?.dead_clicks ? 'warn' : 'good'} />
          <Stat label="Error clicks" value={fmtNum(c?.error_clicks)} tone={c?.error_clicks ? 'bad' : 'good'} />
          <Stat label="Quickback (bounce)" value={fmtNum(c?.quickback_clicks)} tone={c?.quickback_clicks ? 'warn' : 'good'} />
          <Stat label="Excessive scroll" value={fmtNum(c?.excessive_scrolls)} tone={c?.excessive_scrolls ? 'warn' : 'good'} />
          <Stat label="Script errors" value={fmtNum(c?.script_errors)} tone={c?.script_errors ? 'bad' : 'good'} />
        </div>
      </section>

      {/* UTM breakdown */}
      <section>
        <h2 className="text-sm font-semibold text-gray-900 mb-2">By UTM (per ad/campaign)</h2>
        <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
          {utmBreakdown.length === 0 ? (
            <p className="text-sm text-gray-500 p-4">No UTM-tagged traffic observed in this window.</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Source</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Campaign</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Ad (content)</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Sessions</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Scroll%</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Active time</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Rage</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Dead</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Quickback</th>
                </tr>
              </thead>
              <tbody>
                {utmBreakdown.map((r, i) => (
                  <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-3 py-1.5 text-xs">{r.utm_source || '—'}</td>
                    <td className="px-3 py-1.5 text-xs max-w-[200px] truncate" title={r.utm_campaign || ''}>{r.utm_campaign || '—'}</td>
                    <td className="px-3 py-1.5 text-xs max-w-[280px] truncate" title={r.utm_content || ''}>{r.utm_content || '—'}</td>
                    <td className="px-3 py-1.5 text-right">{fmtNum(r.sessions)}</td>
                    <td className="px-3 py-1.5 text-right">{r.avg_scroll_depth !== null ? `${r.avg_scroll_depth.toFixed(0)}%` : '—'}</td>
                    <td className="px-3 py-1.5 text-right text-xs">{fmtDur(r.active_time_sec)}</td>
                    <td className={`px-3 py-1.5 text-right ${r.rage_clicks > 0 ? 'text-red-600 font-semibold' : 'text-gray-400'}`}>{r.rage_clicks}</td>
                    <td className={`px-3 py-1.5 text-right ${r.dead_clicks > 0 ? 'text-amber-700' : 'text-gray-400'}`}>{r.dead_clicks}</td>
                    <td className={`px-3 py-1.5 text-right ${r.quickback_clicks > 0 ? 'text-amber-700' : 'text-gray-400'}`}>{r.quickback_clicks}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  )
}

function SmallStat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3">
      <p className="text-xs text-gray-600 font-medium">{label}</p>
      <p className="text-xl font-semibold mt-0.5">{value}</p>
      <p className="text-[11px] text-gray-500 mt-1">{hint}</p>
    </div>
  )
}

function VitalStat({ label, value, pass, threshold }: { label: string; value: string; pass: boolean | undefined; threshold: string }) {
  const color = pass === true ? 'text-emerald-700 bg-emerald-50 border-emerald-200' : pass === false ? 'text-red-700 bg-red-50 border-red-200' : 'text-gray-700 bg-gray-50 border-gray-200'
  return (
    <div className={`rounded border px-3 py-2 ${color}`}>
      <div className="flex items-baseline gap-2">
        <p className="text-xs font-semibold">{label}</p>
        {pass === true && <span className="text-[10px]">✓ pass</span>}
        {pass === false && <span className="text-[10px]">✗ fail</span>}
      </div>
      <p className="text-xl font-bold mt-0.5 tabular-nums">{value}</p>
      <p className="text-[10px] opacity-75 mt-0.5">{threshold}</p>
    </div>
  )
}

function BigStat({ label, value, hint, tone }: { label: string; value: string; hint: string; tone: 'good' | 'warn' | 'bad' | 'neutral' }) {
  const borders = {
    good: 'border-emerald-300 bg-emerald-50',
    warn: 'border-amber-300 bg-amber-50',
    bad: 'border-red-300 bg-red-50',
    neutral: 'border-gray-200 bg-white',
  }[tone]
  return (
    <div className={`rounded-lg border p-4 ${borders}`}>
      <p className="text-xs text-gray-600 font-medium">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
      <p className="text-[11px] text-gray-500 mt-1">{hint}</p>
    </div>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'good' | 'warn' | 'bad' }) {
  const color = tone === 'bad' ? 'text-red-600' : tone === 'warn' ? 'text-amber-700' : tone === 'good' ? 'text-emerald-700' : 'text-gray-900'
  return (
    <div>
      <p className="text-[11px] text-gray-500 font-medium uppercase tracking-wide">{label}</p>
      <p className={`text-lg font-semibold mt-0.5 ${color}`}>{value}</p>
    </div>
  )
}

// Playbook-informed thresholds for coloring the big stats
function dbcrTone(v: number | null | undefined): 'good' | 'warn' | 'bad' | 'neutral' {
  if (v === null || v === undefined) return 'neutral'
  if (v >= 0.025) return 'good'   // Meta cold ≥ 2.5% = Elite per playbook §1.2
  if (v >= 0.01) return 'warn'
  return 'bad'
}
function clickToSessionTone(v: number | null | undefined): 'good' | 'warn' | 'bad' | 'neutral' {
  if (v === null || v === undefined) return 'neutral'
  if (v >= 0.6) return 'good'
  if (v >= 0.3) return 'warn'
  return 'bad'  // >70% click leak = slow hero (§9.4)
}
function lpvToSessionTone(v: number | null | undefined): 'good' | 'warn' | 'bad' | 'neutral' {
  if (v === null || v === undefined) return 'neutral'
  // Clarity ≥60% of LPV is healthy; <40% means sessions are being lost
  // before the page renders enough to fire the tracking script.
  if (v >= 0.6) return 'good'
  if (v >= 0.4) return 'warn'
  return 'bad'
}
function engagementTone(v: number | null | undefined): 'good' | 'warn' | 'bad' | undefined {
  if (v === null || v === undefined) return undefined
  if (v >= 0.5) return 'good'
  if (v >= 0.3) return 'warn'
  return 'bad'
}
function bounceTone(v: number | null | undefined): 'good' | 'warn' | 'bad' | undefined {
  if (v === null || v === undefined) return undefined
  // Inverse of engagement — low bounce = good
  if (v <= 0.4) return 'good'
  if (v <= 0.65) return 'warn'
  return 'bad'
}
function rageTone(v: number | null | undefined): 'good' | 'warn' | 'bad' | 'neutral' {
  if (v === null || v === undefined) return 'neutral'
  if (v === 0) return 'good'
  if (v < 0.02) return 'warn'
  return 'bad'
}
function scrollTone(v: number | null | undefined): 'good' | 'warn' | 'bad' | undefined {
  if (v === null || v === undefined) return undefined
  if (v >= 40) return 'good'
  if (v >= 20) return 'warn'
  return 'bad'
}
