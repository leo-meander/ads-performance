'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle, ChevronDown, ChevronRight, Copy, ExternalLink, Flame,
  Layers, RefreshCw, Users,
} from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

// A competitor ad as the monitor knows it. Two clocks live side by side and
// they mean different things:
//   days_running  - Meta's own start date. Longer reach, unverifiable.
//   days_observed - how long WE have watched it. Shorter, but it is proof.
// The UI shows both rather than picking one, because a large gap between them
// is itself the story (an ad that predates our monitoring).
export interface MonitoredAd {
  id: string
  ad_archive_id: string
  page_id: string | null
  page_name: string | null
  country: string | null
  ad_creative_bodies: string[]
  ad_creative_link_titles: string[]
  cta_text: string | null
  link_url: string | null
  media_type: string | null
  preview_image_url: string | null
  ad_snapshot_url: string | null
  publisher_platforms: string[]
  ad_delivery_start_time: string | null
  days_running: number
  first_seen_at: string | null
  last_seen_at: string | null
  seen_count: number
  days_observed: number
  is_currently_active: boolean
  disappeared_at: string | null
  creative_group_key: string | null
  ai_breakdown: AiBreakdown | null
  source: string | null
}

export interface AiBreakdown {
  hook?: string | null
  primary_angle?: string | null
  secondary_angle?: string | null
  offer?: string | null
  usp?: string | null
  cta?: string | null
  target?: string | null
  language?: string | null
  notes?: string | null
}

interface CreativeGroup {
  id: string
  group_key: string
  label: string | null
  ad_count: number
  active_ad_count: number
  page_names: string[]
  preview_image_url: string | null
  media_type: string | null
  first_seen_at: string | null
  last_seen_at: string | null
  max_days_running: number
  is_still_active: boolean
}

interface MonitorPage {
  id: string
  page_id: string
  page_name: string
  category: string | null
  country: string | null
  monitor_enabled: boolean
  last_checked_at: string | null
  last_crawl_ad_count: number | null
  last_crawl_error: string | null
}

export interface MonitorStatus {
  provider: { provider: string; configured: boolean; covers_commercial_ads: boolean; note: string | null }
  long_running_days: number
  totals: {
    tracked_pages: number
    ads_tracked: number
    ads_active: number
    long_running_active: number
    awaiting_breakdown: number
    creative_groups: number
  }
  pages: MonitorPage[]
}

const ANGLE_LABELS: Record<string, string> = {
  location_convenience: 'Location / convenience',
  transit_proximity: 'Transit / MRT proximity',
  price_discount: 'Price / discount',
  room_experience: 'Room experience',
  design_aesthetic: 'Design / aesthetic',
  food_beverage: 'Food & beverage',
  social_atmosphere: 'Social atmosphere',
  family_friendly: 'Family friendly',
  couple_romance: 'Couple / romance',
  business_work: 'Business / work',
  loyalty_direct_booking: 'Direct booking perk',
  urgency_scarcity: 'Urgency / scarcity',
  seasonal_event: 'Seasonal / event',
  social_proof_reviews: 'Social proof / reviews',
  amenity_facility: 'Amenity / facility',
}

function DaysBadge({ days, active }: { days: number; active: boolean }) {
  const tone =
    days >= 60 ? 'bg-emerald-100 text-emerald-800'
      : days >= 30 ? 'bg-green-100 text-green-700'
      : days >= 7 ? 'bg-amber-100 text-amber-700'
      : 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold ${tone}`}>
      {days}d
      {active && <span className="w-1.5 h-1.5 rounded-full bg-green-500" />}
    </span>
  )
}

function BreakdownGrid({ b }: { b: AiBreakdown }) {
  const rows: [string, string | null | undefined][] = [
    ['HOOK', b.hook],
    ['ANGLE', b.primary_angle ? ANGLE_LABELS[b.primary_angle] || b.primary_angle : null],
    ['OFFER', b.offer],
    ['USP', b.usp],
    ['CTA', b.cta],
    ['TARGET', b.target],
  ]
  return (
    <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5 border-t border-gray-100 pt-3">
      {rows.filter(([, v]) => v).map(([k, v]) => (
        <div key={k} className="flex gap-2 text-xs">
          <span className="w-14 shrink-0 text-[10px] font-semibold tracking-wider text-gray-400 pt-0.5">{k}</span>
          <span className="text-gray-700">{v}</span>
        </div>
      ))}
      {b.notes && <p className="col-span-full text-[11px] text-amber-700 mt-1">Note: {b.notes}</p>}
    </div>
  )
}

function AdRow({ ad }: { ad: MonitoredAd }) {
  const [open, setOpen] = useState(false)
  const body = (ad.ad_creative_bodies || []).join(' ')
  const headline = (ad.ad_creative_link_titles || [])[0]

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="flex items-start gap-3">
        {ad.preview_image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={ad.preview_image_url}
            alt=""
            className="w-16 h-16 rounded-lg object-cover bg-gray-100 shrink-0"
            onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
          />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2 mb-1">
            <span className="font-medium text-sm text-gray-900">{ad.page_name || 'Unknown page'}</span>
            <DaysBadge days={ad.days_running} active={ad.is_currently_active} />
            {ad.country && <span className="text-[10px] text-gray-400">{ad.country}</span>}
            {ad.media_type && (
              <span className="px-1.5 py-0.5 rounded bg-gray-100 text-[10px] text-gray-600">{ad.media_type}</span>
            )}
            {ad.creative_group_key && (
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-indigo-50 text-[10px] text-indigo-700">
                <Copy className="w-2.5 h-2.5" /> grouped
              </span>
            )}
          </div>

          {headline && <p className="text-xs text-gray-500 mb-1 truncate">{headline}</p>}
          {body && <p className="text-sm text-gray-700 line-clamp-2">{body}</p>}

          <div className="flex flex-wrap items-center gap-3 mt-2 text-[10px] text-gray-400">
            <span>
              Meta start:{' '}
              {ad.ad_delivery_start_time
                ? new Date(ad.ad_delivery_start_time).toLocaleDateString()
                : 'unknown'}
            </span>
            {/* Our own evidence, kept visibly separate from Meta's claim. */}
            <span>
              Seen by us: {ad.seen_count}x over {ad.days_observed}d
            </span>
            {ad.last_seen_at && <span>Last seen {new Date(ad.last_seen_at).toLocaleDateString()}</span>}
            {/* "Gone since" would name the crawl that noticed, not the day it
                stopped. Only the last confirmed sighting is provable. */}
            {!ad.is_currently_active && (
              <span className="text-red-500">
                Stopped — last confirmed{' '}
                {ad.last_seen_at ? new Date(ad.last_seen_at).toLocaleDateString() : 'unknown'}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {ad.ai_breakdown && (
            <button
              onClick={() => setOpen(!open)}
              title="AI breakdown"
              className="p-1.5 rounded-lg text-gray-400 hover:text-purple-600 hover:bg-purple-50 transition"
            >
              {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </button>
          )}
          {ad.ad_snapshot_url && (
            <a
              href={ad.ad_snapshot_url}
              target="_blank"
              rel="noopener noreferrer"
              title="Open in Ad Library"
              className="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition"
            >
              <ExternalLink className="w-4 h-4" />
            </a>
          )}
        </div>
      </div>

      {open && ad.ai_breakdown && <BreakdownGrid b={ad.ai_breakdown} />}
    </div>
  )
}

function GroupCard({ group, onOpen }: { group: CreativeGroup; onOpen: (key: string) => void }) {
  return (
    <button
      onClick={() => onOpen(group.group_key)}
      className="w-full text-left bg-white rounded-xl border border-gray-200 p-4 hover:border-indigo-300 hover:shadow-sm transition"
    >
      <div className="flex items-center gap-2 mb-2">
        <Layers className="w-3.5 h-3.5 text-indigo-500" />
        <span className="text-sm font-semibold text-gray-900">
          {group.ad_count} ads, one concept
        </span>
        <DaysBadge days={group.max_days_running} active={group.is_still_active} />
      </div>
      {group.label && <p className="text-sm text-gray-700 line-clamp-2 mb-2">{group.label}</p>}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-gray-400">
        <span className="inline-flex items-center gap-1">
          <Users className="w-3 h-3" />
          {group.page_names.length} advertiser{group.page_names.length === 1 ? '' : 's'}
        </span>
        <span>{group.active_ad_count} still running</span>
        {group.first_seen_at && <span>Since {new Date(group.first_seen_at).toLocaleDateString()}</span>}
      </div>
    </button>
  )
}

export default function SpyRadarTab({
  status,
  onStatusChange,
}: {
  status: MonitorStatus | null
  onStatusChange: () => void
}) {
  const [view, setView] = useState<'ads' | 'groups'>('ads')
  const [ads, setAds] = useState<MonitoredAd[]>([])
  const [total, setTotal] = useState(0)
  const [groups, setGroups] = useState<CreativeGroup[]>([])
  const [openGroup, setOpenGroup] = useState<{ key: string; ads: MonitoredAd[]; label: string | null } | null>(null)
  const [minDays, setMinDays] = useState(30)
  const [adStatus, setAdStatus] = useState<'active' | 'stopped' | 'all'>('active')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [progress, setProgress] = useState<
    { done: number; total: number; current: string; lines: string[] } | null
  >(null)
  const [message, setMessage] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)

  const loadAds = useCallback(() => {
    setLoading(true)
    const params = new URLSearchParams({
      min_days: String(minDays),
      status: adStatus,
      limit: '100',
      sort_by: 'days_running',
    })
    fetch(`${API_BASE}/api/spy-ads/monitor/ads?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          setAds(d.data.items)
          setTotal(d.data.total)
        } else {
          setMessage({ tone: 'err', text: d.error || 'Could not load the ledger.' })
        }
      })
      .catch(() => setMessage({ tone: 'err', text: 'Could not reach the server.' }))
      .finally(() => setLoading(false))
  }, [minDays, adStatus])

  const loadGroups = useCallback(() => {
    fetch(`${API_BASE}/api/spy-ads/monitor/groups?min_ads=2&only_active=false&limit=100`, {
      credentials: 'include',
    })
      .then(r => r.json())
      .then(d => { if (d.success) setGroups(d.data.items) })
      .catch(() => {})
  }, [])

  useEffect(() => { loadAds() }, [loadAds])
  useEffect(() => { loadGroups() }, [loadGroups])

  const openGroupDetail = (key: string) => {
    fetch(`${API_BASE}/api/spy-ads/monitor/groups/${key}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setOpenGroup({ key, ads: d.data.ads, label: d.data.label }) })
      .catch(() => {})
  }

  // One request per competitor rather than one sweep.
  //
  // Each page costs a full provider run (tens of seconds), so a sweep over
  // half a dozen competitors would run past the ingress timeout and the user
  // would lose the roll call for runs they had already paid for. Serial, not
  // parallel: the provider charges per ad and rate-limits concurrent runs, and
  // a half-finished parallel batch is harder to reason about than a queue.
  const runCrawl = async () => {
    const pages = (status?.pages || []).filter(p => p.monitor_enabled)
    if (pages.length === 0) {
      setMessage({ tone: 'err', text: 'No competitors are enabled for monitoring yet.' })
      return
    }

    setBusy('crawl')
    setMessage(null)
    setProgress({ done: 0, total: pages.length, current: pages[0].page_name, lines: [] })

    const lines: string[] = []
    let fetched = 0
    let added = 0
    let retired = 0
    let failed = 0

    for (const [i, page] of pages.entries()) {
      setProgress({ done: i, total: pages.length, current: page.page_name, lines: [...lines] })
      try {
        const resp = await fetch(`${API_BASE}/api/spy-ads/monitor/crawl`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ page_db_id: page.id }),
        })
        const d = await resp.json()
        const row = d.data?.pages?.[0]
        if (row && !row.error) {
          fetched += row.fetched
          added += row.new
          retired += row.retired
          lines.push(`${page.page_name}: ${row.fetched} ads (${row.new} new)`)
        } else {
          failed += 1
          lines.push(`${page.page_name}: ${row?.error || d.error || 'failed'}`)
        }
      } catch {
        failed += 1
        lines.push(`${page.page_name}: could not reach the server`)
      }
      setProgress({ done: i + 1, total: pages.length, current: '', lines: [...lines] })
    }

    setMessage({
      tone: failed === pages.length ? 'err' : 'ok',
      text: `Crawled ${pages.length - failed}/${pages.length} competitors: ${fetched} ads (${added} new, ${retired} retired).`,
    })
    setProgress(null)
    loadAds()
    loadGroups()
    onStatusChange()
    setBusy(null)
  }

  const runBreakdown = () => {
    setBusy('breakdown')
    setMessage(null)
    fetch(`${API_BASE}/api/spy-ads/monitor/breakdown`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          setMessage({
            tone: 'ok',
            text: `Broke down ${d.data.analyzed} ads (${d.data.failed} failed, ${d.data.skipped} had no copy to read).`,
          })
        } else {
          setMessage({ tone: 'err', text: d.error || 'Breakdown failed.' })
        }
        loadAds()
        onStatusChange()
      })
      .catch(() => setMessage({ tone: 'err', text: 'Could not reach the server.' }))
      .finally(() => setBusy(null))
  }

  const brokenPages = (status?.pages || []).filter(p => p.last_crawl_error)
  const neverCrawled = (status?.pages || []).filter(p => !p.last_checked_at)

  // Nothing crawls on a schedule, so the ledger is exactly as fresh as the
  // last time somebody pressed the button. Say how stale it is rather than
  // letting a three-month-old snapshot read as today's market.
  //
  // Freshness counts only crawls that SUCCEEDED. `last_checked_at` records the
  // attempt, so a run that failed on every competitor would otherwise reset the
  // clock and make a stale ledger look current -- "we tried" is not "we know".
  const lastCrawl = (status?.pages || [])
    .filter(p => !p.last_crawl_error)
    .map(p => p.last_checked_at)
    .filter((d): d is string => !!d)
    .sort()
    .pop()
  const daysStale = lastCrawl
    ? Math.floor((Date.now() - new Date(lastCrawl).getTime()) / 86400000)
    : null

  return (
    <div className="space-y-4">
      {/* Totals */}
      {status && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: `Running ${status.long_running_days}+ days`, value: status.totals.long_running_active, accent: true },
            { label: 'Ads tracked', value: status.totals.ads_tracked },
            { label: 'Creative concepts', value: status.totals.creative_groups },
            { label: 'Awaiting AI breakdown', value: status.totals.awaiting_breakdown },
          ].map(card => (
            <div key={card.label} className="bg-white rounded-xl border border-gray-200 p-4">
              <p className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold">{card.label}</p>
              <p className={`text-2xl font-bold mt-1 ${card.accent ? 'text-emerald-600' : 'text-gray-900'}`}>
                {card.value}
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Anything that makes the numbers above a lie gets said out loud. */}
      {status && !status.provider.configured && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
          <p className="font-semibold flex items-center gap-1.5">
            <AlertTriangle className="w-4 h-4" /> The data source is not configured
          </p>
          <p className="mt-1 text-amber-700">{status.provider.note}</p>
        </div>
      )}
      {brokenPages.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm">
          <p className="font-semibold text-red-800 flex items-center gap-1.5">
            <AlertTriangle className="w-4 h-4" /> {brokenPages.length} competitor
            {brokenPages.length === 1 ? '' : 's'} failed the last crawl
          </p>
          <ul className="mt-1.5 space-y-1 text-xs text-red-700">
            {brokenPages.map(p => (
              <li key={p.id}><span className="font-medium">{p.page_name}</span> — {p.last_crawl_error}</li>
            ))}
          </ul>
        </div>
      )}
      {neverCrawled.length > 0 && brokenPages.length === 0 && (
        <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-sm text-blue-800">
          {neverCrawled.length} tracked competitor{neverCrawled.length === 1 ? ' has' : 's have'} never been
          crawled. Run a crawl to start their longevity clock.
        </div>
      )}

      {daysStale === null && (status?.pages || []).some(p => p.last_checked_at) && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
          <p className="font-semibold flex items-center gap-1.5">
            <AlertTriangle className="w-4 h-4" /> No competitor has been crawled successfully
          </p>
          <p className="mt-1 text-amber-700">
            Every crawl so far has failed, so anything below is either stale or empty. Fix the
            errors above before reading these numbers.
          </p>
        </div>
      )}

      {daysStale !== null && daysStale >= 7 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
          <p className="font-semibold flex items-center gap-1.5">
            <AlertTriangle className="w-4 h-4" /> This ledger is {daysStale} days old
          </p>
          <p className="mt-1 text-amber-700">
            Nothing crawls on a schedule — press &quot;Crawl now&quot; before trusting what is
            still running. Ads that stopped since the last crawl are still listed as active.
          </p>
        </div>
      )}

      {/* Controls */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-wrap items-center gap-2">
        <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
          {(['ads', 'groups'] as const).map(v => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${view === v ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}
            >
              {v === 'ads' ? 'Long-running ads' : `Creative concepts (${groups.length})`}
            </button>
          ))}
        </div>

        {view === 'ads' && (
          <>
            <select
              value={minDays}
              onChange={e => setMinDays(Number(e.target.value))}
              className="px-3 py-1.5 border border-gray-200 rounded-lg text-xs"
            >
              {[0, 7, 14, 30, 60, 90].map(d => (
                <option key={d} value={d}>{d === 0 ? 'Any duration' : `${d}+ days`}</option>
              ))}
            </select>
            <select
              value={adStatus}
              onChange={e => setAdStatus(e.target.value as 'active' | 'stopped' | 'all')}
              className="px-3 py-1.5 border border-gray-200 rounded-lg text-xs"
            >
              <option value="active">Still running</option>
              <option value="stopped">Stopped</option>
              <option value="all">All</option>
            </select>
          </>
        )}

        <div className="flex-1" />

        <button
          onClick={runCrawl}
          disabled={busy !== null}
          className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${busy === 'crawl' ? 'animate-spin' : ''}`} />
          {busy === 'crawl' ? 'Crawling...' : 'Crawl now'}
        </button>
        <button
          onClick={runBreakdown}
          disabled={busy !== null || (status?.totals.awaiting_breakdown ?? 0) === 0}
          title={
            (status?.totals.awaiting_breakdown ?? 0) === 0
              ? 'Nothing new to break down'
              : 'Run the AI breakdown on long-running ads'
          }
          className="inline-flex items-center gap-1.5 px-4 py-2 bg-purple-600 text-white rounded-lg text-sm font-medium hover:bg-purple-700 transition disabled:opacity-50"
        >
          <Flame className="w-3.5 h-3.5" />
          {busy === 'breakdown' ? 'Analyzing...' : `Break down ${status?.totals.awaiting_breakdown ?? 0}`}
        </button>
      </div>

      {progress && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 text-sm">
          <div className="flex items-center justify-between gap-3 mb-2">
            <span className="font-medium text-blue-900">
              {progress.current
                ? `Crawling ${progress.current}…`
                : 'Finishing up…'}
            </span>
            <span className="text-xs text-blue-700 tabular-nums">
              {progress.done}/{progress.total}
            </span>
          </div>
          <div className="h-1.5 bg-blue-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all"
              style={{ width: `${Math.round((progress.done / progress.total) * 100)}%` }}
            />
          </div>
          {progress.lines.length > 0 && (
            <ul className="mt-2 space-y-0.5 text-xs text-blue-800">
              {progress.lines.map((l, i) => <li key={i}>{l}</li>)}
            </ul>
          )}
        </div>
      )}

      {message && (
        <div
          className={`rounded-xl border p-3 text-sm ${message.tone === 'ok' ? 'bg-green-50 border-green-200 text-green-800' : 'bg-red-50 border-red-200 text-red-700'}`}
        >
          {message.text}
        </div>
      )}

      {/* Group detail */}
      {openGroup && (
        <div className="bg-indigo-50/50 rounded-xl border border-indigo-200 p-4">
          <div className="flex items-start justify-between gap-3 mb-3">
            <div>
              <p className="text-sm font-semibold text-gray-900">
                {openGroup.ads.length} ads in this concept
              </p>
              {openGroup.label && <p className="text-xs text-gray-600 mt-0.5">{openGroup.label}</p>}
            </div>
            <button onClick={() => setOpenGroup(null)} className="text-xs text-gray-500 hover:text-gray-700">
              Close
            </button>
          </div>
          <div className="space-y-2">
            {openGroup.ads.map(a => <AdRow key={a.id} ad={a} />)}
          </div>
        </div>
      )}

      {/* Lists */}
      {view === 'ads' ? (
        loading ? (
          <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">Loading…</div>
        ) : ads.length === 0 ? (
          <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
            <p>Nothing in the ledger yet at this filter.</p>
            <p className="text-xs mt-1">
              Add competitors, then run a crawl. Longevity only appears once an ad has been
              observed — the first crawl starts the clock.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-gray-400">{ads.length} of {total} ads</p>
            {ads.map(ad => <AdRow key={ad.id} ad={ad} />)}
          </div>
        )
      ) : groups.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
          <p>No duplicated concepts found yet.</p>
          <p className="text-xs mt-1">
            A concept appears when two or more ads share a creative asset or near-identical copy.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {groups.map(g => <GroupCard key={g.id} group={g} onOpen={openGroupDetail} />)}
        </div>
      )}
    </div>
  )
}
