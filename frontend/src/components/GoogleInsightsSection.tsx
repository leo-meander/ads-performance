'use client'

import { useEffect, useMemo, useRef, useState } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Props {
  campaignId: string
  campaignType: string  // 'PERFORMANCE_MAX' | 'SEARCH' | etc.
  dateFrom?: string
  dateTo?: string
}

type LoadState = 'idle' | 'loading' | 'ready' | 'error'

interface PanelState<T> {
  status: LoadState
  data: T | null
  error: string | null
}

interface SearchTermRow {
  search_term: string
  match_type: string
  intent: string
  brand: string
  price_quality: string
  spend: number
  clicks: number
  conversions: number
  revenue: number
  ctr: number
  cvr: number
  roas: number
  flags: string[]
}

interface SearchTermsData {
  mode: 'search_terms' | 'pmax_categories'
  terms?: SearchTermRow[]
  by_intent?: Record<string, BucketAgg>
  by_brand?: Record<string, BucketAgg>
  by_price_quality?: Record<string, BucketAgg>
  junk_terms?: SearchTermRow[]
  winners?: SearchTermRow[]
  intent_match_no_conv?: SearchTermRow[]
  total_terms?: number
  categories?: { category: string; impressions: number; clicks: number; conversions: number; cvr: number }[]
}

interface BucketAgg {
  term_count: number
  spend: number
  clicks: number
  conversions: number
  cvr: number
  roas: number
  cpa: number | null
}

interface DeviceRow {
  device: string
  spend: number
  clicks: number
  conversions: number
  ctr: number
  cvr: number
  cpa: number | null
  roas: number
}

interface DevicesData {
  devices: DeviceRow[]
  flags: string[]
}

interface LocationRow {
  country: string
  spend: number
  clicks: number
  conversions: number
  ctr: number
  cvr: number
  roas: number
  spend_share: number
  flags: string[]
}

interface LocationsData {
  locations: LocationRow[]
  junk: LocationRow[]
  winners: LocationRow[]
  summary: { country_count: number; junk_count: number; profitable_count: number }
}

interface HourCell { hour: number; day_of_week: string; spend: number; clicks: number; conversions: number; cvr: number; roas: number }
interface HourRollup { hour: number; spend: number; clicks: number; conversions: number; cvr: number; roas: number; spend_share?: number }
interface DayRollup { day_of_week: string; spend: number; clicks: number; conversions: number; cvr: number; roas: number }

interface TimeData {
  cells: HourCell[]
  by_hour: HourRollup[]
  by_day: DayRollup[]
  waste_hours: HourRollup[]
  peak_hours: HourRollup[]
}

const INTENT_COLORS: Record<string, string> = {
  HIGH: 'bg-green-100 text-green-700',
  MID: 'bg-blue-100 text-blue-700',
  LOW: 'bg-yellow-100 text-yellow-700',
  JUNK: 'bg-red-100 text-red-700',
}
const FLAG_COLORS: Record<string, string> = {
  WASTE: 'bg-red-100 text-red-700',
  WINNER: 'bg-green-100 text-green-700',
  INTENT_MATCH_NO_CONV: 'bg-orange-100 text-orange-700',
  NEGATIVE_CANDIDATE: 'bg-red-100 text-red-700',
  CHEAP_TRAFFIC_NO_VALUE: 'bg-red-100 text-red-700',
  PROFITABLE: 'bg-green-100 text-green-700',
  HIGH_VALUE_MARKET: 'bg-purple-100 text-purple-700',
  MOBILE_UX_BROKEN: 'bg-red-100 text-red-700',
  CROSS_DEVICE_RESEARCH: 'bg-blue-100 text-blue-700',
  HEALTHY: 'bg-green-100 text-green-700',
}

const fmtNum = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 2 })
const fmtCur = (n: number, currency: string) => `${currency} ${n.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
const fmtPct = (n: number) => `${n.toFixed(2)}%`

export default function GoogleInsightsSection({ campaignId, campaignType, dateFrom, dateTo }: Props) {
  const [searchTerms, setSearchTerms] = useState<PanelState<SearchTermsData>>({ status: 'idle', data: null, error: null })
  const [devices, setDevices] = useState<PanelState<DevicesData>>({ status: 'idle', data: null, error: null })
  const [locations, setLocations] = useState<PanelState<LocationsData>>({ status: 'idle', data: null, error: null })
  const [timeOfDay, setTimeOfDay] = useState<PanelState<TimeData>>({ status: 'idle', data: null, error: null })
  const [currency, setCurrency] = useState<string>('USD')
  const [narrative, setNarrative] = useState<string>('')
  const [narrativeLoading, setNarrativeLoading] = useState(false)
  const [narrativeError, setNarrativeError] = useState<string | null>(null)
  const narrativeAbortRef = useRef<AbortController | null>(null)

  const qs = useMemo(() => {
    const p = new URLSearchParams()
    if (dateFrom) p.set('date_from', dateFrom)
    if (dateTo) p.set('date_to', dateTo)
    const s = p.toString()
    return s ? `?${s}` : ''
  }, [dateFrom, dateTo])

  const fetchPanel = async <T,>(
    path: string,
    setter: (s: PanelState<T>) => void,
  ): Promise<{ data: T; currency?: string } | null> => {
    setter({ status: 'loading', data: null, error: null })
    try {
      const res = await fetch(`${API_BASE}${path}${qs}`, { credentials: 'include' }).then(r => r.json())
      if (res.success) {
        setter({ status: 'ready', data: res.data, error: null })
        if (res.data?.currency) setCurrency(res.data.currency)
        return { data: res.data, currency: res.data?.currency }
      }
      setter({ status: 'error', data: null, error: res.error || 'Request failed' })
      return null
    } catch (e: any) {
      setter({ status: 'error', data: null, error: e?.message || 'Network error' })
      return null
    }
  }

  // Lazy-load each panel in parallel on mount / range change
  useEffect(() => {
    fetchPanel<SearchTermsData>(`/api/google/campaigns/${campaignId}/insights/search-terms`, setSearchTerms)
    fetchPanel<DevicesData>(`/api/google/campaigns/${campaignId}/insights/devices`, setDevices)
    fetchPanel<LocationsData>(`/api/google/campaigns/${campaignId}/insights/locations`, setLocations)
    fetchPanel<TimeData>(`/api/google/campaigns/${campaignId}/insights/time-of-day`, setTimeOfDay)
    setNarrative('')
    setNarrativeError(null)
    return () => {
      narrativeAbortRef.current?.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaignId, dateFrom, dateTo])

  const allReady = searchTerms.status === 'ready' && devices.status === 'ready' && locations.status === 'ready' && timeOfDay.status === 'ready'

  const generateNarrative = async () => {
    if (!allReady) return
    narrativeAbortRef.current?.abort()
    const ctl = new AbortController()
    narrativeAbortRef.current = ctl
    setNarrative('')
    setNarrativeError(null)
    setNarrativeLoading(true)
    try {
      const body = {
        date_range: { from: dateFrom, to: dateTo },
        totals: null,
        search_terms: searchTerms.data?.mode === 'search_terms' ? searchTerms.data : null,
        pmax_categories: searchTerms.data?.mode === 'pmax_categories' ? searchTerms.data.categories : null,
        devices: devices.data,
        locations: locations.data,
        time_of_day: timeOfDay.data,
      }
      const res = await fetch(`${API_BASE}/api/google/campaigns/${campaignId}/insights/narrative`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: ctl.signal,
      })
      if (!res.ok || !res.body) {
        setNarrativeError(`HTTP ${res.status}`)
        setNarrativeLoading(false)
        return
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      // Parse SSE: "data: <json>\n\n"
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''
        for (const evt of events) {
          for (const line of evt.split('\n')) {
            if (!line.startsWith('data: ')) continue
            const payload = line.slice(6)
            if (payload === '[DONE]') continue
            try {
              const text = JSON.parse(payload)
              if (typeof text === 'string') {
                setNarrative(prev => prev + text)
              }
            } catch {
              /* ignore non-JSON lines */
            }
          }
        }
      }
    } catch (e: any) {
      if (e?.name !== 'AbortError') setNarrativeError(e?.message || 'Stream failed')
    } finally {
      setNarrativeLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Insights</h2>
        <div className="text-xs text-gray-400">Pulled live from Google Ads — last 30 days by default</div>
      </div>

      {/* Search Terms Panel */}
      <SearchTermsPanel state={searchTerms} currency={currency} campaignType={campaignType} />

      {/* Device Panel */}
      <DevicesPanel state={devices} currency={currency} />

      {/* Location Panel */}
      <LocationsPanel state={locations} currency={currency} />

      {/* Time of Day Panel */}
      <TimePanel state={timeOfDay} currency={currency} />

      {/* Combined Narrative */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900">AI Combined Diagnosis</h3>
          <button
            onClick={generateNarrative}
            disabled={!allReady || narrativeLoading}
            className="text-xs px-3 py-1.5 rounded-lg font-medium bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {narrativeLoading ? 'Generating…' : narrative ? 'Regenerate' : 'Generate insight'}
          </button>
        </div>
        {!allReady && (
          <p className="text-xs text-gray-400">Waiting for all panels to load…</p>
        )}
        {narrativeError && (
          <p className="text-xs text-red-600">Error: {narrativeError}</p>
        )}
        {narrative ? (
          <div className="prose prose-sm max-w-none whitespace-pre-wrap text-sm text-gray-800">{narrative}</div>
        ) : !narrativeLoading && allReady && (
          <p className="text-xs text-gray-400">Click "Generate insight" to ask Claude to synthesize the panels above into a cross-dimension diagnosis.</p>
        )}
      </div>
    </div>
  )
}

// ── Sub-components ──────────────────────────────────────────

function PanelShell({ title, subtitle, state, children }: {
  title: string
  subtitle?: string
  state: PanelState<unknown>
  children: React.ReactNode
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200">
      <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-gray-900">{title}</h3>
          {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
        </div>
        {state.status === 'loading' && <span className="text-xs text-gray-400">Loading…</span>}
        {state.status === 'error' && <span className="text-xs text-red-600">Error</span>}
      </div>
      <div className="p-5">
        {state.status === 'loading' && <div className="text-sm text-gray-400">Fetching from Google Ads…</div>}
        {state.status === 'error' && <div className="text-sm text-red-600">{state.error}</div>}
        {state.status === 'ready' && children}
      </div>
    </div>
  )
}

function FlagBadge({ flag }: { flag: string }) {
  const cls = FLAG_COLORS[flag] || 'bg-gray-100 text-gray-600'
  return <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${cls}`}>{flag.replace(/_/g, ' ')}</span>
}

function SearchTermsPanel({ state, currency, campaignType }: { state: PanelState<SearchTermsData>; currency: string; campaignType: string }) {
  const data = state.data
  const isPMax = campaignType === 'PERFORMANCE_MAX'
  return (
    <PanelShell
      title={isPMax ? 'Search Term Categories (PMax)' : 'Search Terms'}
      subtitle={isPMax ? 'Bucketed query themes from campaign_search_term_insight' : 'Real user queries — actual intent'}
      state={state}
    >
      {data?.mode === 'pmax_categories' && (
        <div>
          {(!data.categories || data.categories.length === 0) ? (
            <p className="text-sm text-gray-400">No category data available (PMax may not surface this for low-volume campaigns).</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-xs text-gray-500">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">Category</th>
                    <th className="text-right px-3 py-2 font-medium">Impr.</th>
                    <th className="text-right px-3 py-2 font-medium">Clicks</th>
                    <th className="text-right px-3 py-2 font-medium">Conv.</th>
                    <th className="text-right px-3 py-2 font-medium">CVR</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.categories.slice(0, 30).map((c, i) => (
                    <tr key={i} className="hover:bg-gray-50">
                      <td className="px-3 py-2 text-gray-800">{c.category}</td>
                      <td className="px-3 py-2 text-right">{fmtNum(c.impressions)}</td>
                      <td className="px-3 py-2 text-right">{fmtNum(c.clicks)}</td>
                      <td className="px-3 py-2 text-right">{fmtNum(c.conversions)}</td>
                      <td className="px-3 py-2 text-right">{fmtPct(c.cvr)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {data?.mode === 'search_terms' && (
        <div className="space-y-5">
          {/* Bucket summaries */}
          <div className="grid grid-cols-3 gap-4">
            <BucketCard title="By Intent" buckets={data.by_intent} currency={currency} order={['HIGH', 'MID', 'LOW', 'JUNK']} />
            <BucketCard title="Brand vs Non-brand" buckets={data.by_brand} currency={currency} order={['BRAND', 'NON_BRAND']} />
            <BucketCard title="Price vs Quality" buckets={data.by_price_quality} currency={currency} order={['PRICE', 'QUALITY', 'MIXED', 'NEUTRAL']} />
          </div>

          {/* Action lists */}
          {(data.junk_terms && data.junk_terms.length > 0) && (
            <ActionList
              title="❌ Wasted spend / negative-keyword candidates"
              terms={data.junk_terms}
              currency={currency}
              accent="red"
            />
          )}
          {(data.intent_match_no_conv && data.intent_match_no_conv.length > 0) && (
            <ActionList
              title="⚠️ Right intent, no conversion (ad-copy or landing-page mismatch)"
              terms={data.intent_match_no_conv}
              currency={currency}
              accent="orange"
            />
          )}
          {(data.winners && data.winners.length > 0) && (
            <ActionList
              title="✅ Winners — split into Exact match, scale separately"
              terms={data.winners}
              currency={currency}
              accent="green"
            />
          )}

          <p className="text-xs text-gray-400">{data.total_terms} unique terms in selected range.</p>
        </div>
      )}
    </PanelShell>
  )
}

function BucketCard({ title, buckets, currency, order }: {
  title: string
  buckets?: Record<string, BucketAgg>
  currency: string
  order: string[]
}) {
  return (
    <div className="border border-gray-100 rounded-lg p-3">
      <p className="text-xs font-semibold text-gray-500 uppercase mb-2">{title}</p>
      <div className="space-y-1.5">
        {order.map(k => {
          const b = buckets?.[k]
          if (!b || b.term_count === 0) return null
          return (
            <div key={k} className="flex items-center justify-between text-xs">
              <span className={`px-1.5 py-0.5 rounded ${INTENT_COLORS[k] || 'bg-gray-100 text-gray-700'}`}>{k}</span>
              <span className="text-gray-500">
                {b.term_count} terms · {fmtCur(b.spend, currency)} · CVR {fmtPct(b.cvr)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ActionList({ title, terms, currency, accent }: {
  title: string
  terms: SearchTermRow[]
  currency: string
  accent: 'red' | 'orange' | 'green'
}) {
  const accentBg = accent === 'red' ? 'bg-red-50' : accent === 'orange' ? 'bg-orange-50' : 'bg-green-50'
  return (
    <div className={`rounded-lg ${accentBg} p-3`}>
      <p className="text-xs font-semibold text-gray-700 mb-2">{title}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-gray-500">
            <tr>
              <th className="text-left px-2 py-1 font-medium">Term</th>
              <th className="text-left px-2 py-1 font-medium">Intent</th>
              <th className="text-right px-2 py-1 font-medium">Spend</th>
              <th className="text-right px-2 py-1 font-medium">Clicks</th>
              <th className="text-right px-2 py-1 font-medium">Conv.</th>
              <th className="text-right px-2 py-1 font-medium">CVR</th>
              <th className="text-right px-2 py-1 font-medium">ROAS</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/50">
            {terms.slice(0, 10).map((t, i) => (
              <tr key={i}>
                <td className="px-2 py-1 text-gray-800 font-mono">{t.search_term}</td>
                <td className="px-2 py-1"><span className={`px-1.5 py-0.5 rounded ${INTENT_COLORS[t.intent]}`}>{t.intent}</span></td>
                <td className="px-2 py-1 text-right">{fmtCur(t.spend, currency)}</td>
                <td className="px-2 py-1 text-right">{fmtNum(t.clicks)}</td>
                <td className="px-2 py-1 text-right">{fmtNum(t.conversions)}</td>
                <td className="px-2 py-1 text-right">{fmtPct(t.cvr)}</td>
                <td className="px-2 py-1 text-right">{t.roas.toFixed(2)}x</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function DevicesPanel({ state, currency }: { state: PanelState<DevicesData>; currency: string }) {
  const data = state.data
  return (
    <PanelShell
      title="Device"
      subtitle="Mobile vs Desktop — user behavior, not just ad performance"
      state={state}
    >
      {data && data.devices.length === 0 && <p className="text-sm text-gray-400">No data in selected range.</p>}
      {data && data.devices.length > 0 && (
        <div className="space-y-3">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">Device</th>
                  <th className="text-right px-3 py-2 font-medium">Spend</th>
                  <th className="text-right px-3 py-2 font-medium">Clicks</th>
                  <th className="text-right px-3 py-2 font-medium">CTR</th>
                  <th className="text-right px-3 py-2 font-medium">Conv.</th>
                  <th className="text-right px-3 py-2 font-medium">CVR</th>
                  <th className="text-right px-3 py-2 font-medium">CPA</th>
                  <th className="text-right px-3 py-2 font-medium">ROAS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.devices.map((d, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-medium text-gray-800">{d.device}</td>
                    <td className="px-3 py-2 text-right">{fmtCur(d.spend, currency)}</td>
                    <td className="px-3 py-2 text-right">{fmtNum(d.clicks)}</td>
                    <td className="px-3 py-2 text-right">{fmtPct(d.ctr)}</td>
                    <td className="px-3 py-2 text-right">{fmtNum(d.conversions)}</td>
                    <td className="px-3 py-2 text-right">{fmtPct(d.cvr)}</td>
                    <td className="px-3 py-2 text-right">{d.cpa ? fmtCur(d.cpa, currency) : '–'}</td>
                    <td className="px-3 py-2 text-right">{d.roas.toFixed(2)}x</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.flags.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-gray-500">Flags:</span>
              {data.flags.map(f => <FlagBadge key={f} flag={f} />)}
            </div>
          )}
        </div>
      )}
    </PanelShell>
  )
}

function LocationsPanel({ state, currency }: { state: PanelState<LocationsData>; currency: string }) {
  const data = state.data
  return (
    <PanelShell
      title="Location (User country)"
      subtitle="Where the money actually comes from — geo quality, not just targeting"
      state={state}
    >
      {data && data.locations.length === 0 && <p className="text-sm text-gray-400">No data.</p>}
      {data && data.locations.length > 0 && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-2 text-xs">
            <span className="text-gray-500">{data.summary.country_count} countries</span>
            <span className="text-red-600">{data.summary.junk_count} junk</span>
            <span className="text-green-600">{data.summary.profitable_count} profitable</span>
          </div>
          <div className="overflow-x-auto max-h-72">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-xs text-gray-500 sticky top-0">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">Country</th>
                  <th className="text-right px-3 py-2 font-medium">Spend</th>
                  <th className="text-right px-3 py-2 font-medium">Spend %</th>
                  <th className="text-right px-3 py-2 font-medium">Clicks</th>
                  <th className="text-right px-3 py-2 font-medium">Conv.</th>
                  <th className="text-right px-3 py-2 font-medium">CVR</th>
                  <th className="text-right px-3 py-2 font-medium">ROAS</th>
                  <th className="text-left px-3 py-2 font-medium">Flags</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.locations.slice(0, 25).map((r, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-3 py-2 font-mono text-gray-800">{r.country}</td>
                    <td className="px-3 py-2 text-right">{fmtCur(r.spend, currency)}</td>
                    <td className="px-3 py-2 text-right">{(r.spend_share * 100).toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right">{fmtNum(r.clicks)}</td>
                    <td className="px-3 py-2 text-right">{fmtNum(r.conversions)}</td>
                    <td className="px-3 py-2 text-right">{fmtPct(r.cvr)}</td>
                    <td className="px-3 py-2 text-right">{r.roas.toFixed(2)}x</td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1 flex-wrap">{r.flags.map(f => <FlagBadge key={f} flag={f} />)}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </PanelShell>
  )
}

function TimePanel({ state, currency }: { state: PanelState<TimeData>; currency: string }) {
  const data = state.data
  // Compute heatmap matrix [day][hour] = spend (for color) + cvr
  const matrix = useMemo(() => {
    if (!data) return null
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    const grid: Record<string, Record<number, HourCell | undefined>> = {}
    for (const d of days) grid[d] = {}
    for (const c of data.cells) {
      if (!grid[c.day_of_week]) grid[c.day_of_week] = {}
      grid[c.day_of_week][c.hour] = c
    }
    const maxSpend = Math.max(...data.cells.map(c => c.spend), 0.0001)
    return { grid, days, maxSpend }
  }, [data])

  return (
    <PanelShell
      title="Time of Day"
      subtitle="Hour × day-of-week — when users are ready to convert"
      state={state}
    >
      {data && data.cells.length === 0 && <p className="text-sm text-gray-400">No data.</p>}
      {data && matrix && data.cells.length > 0 && (
        <div className="space-y-4">
          {/* Heatmap */}
          <div>
            <p className="text-xs text-gray-500 mb-2">Spend heatmap (darker = more spend; ✓ = had conversions)</p>
            <div className="overflow-x-auto">
              <div className="inline-block">
                <div className="grid" style={{ gridTemplateColumns: `40px repeat(24, minmax(20px, 1fr))` }}>
                  <div></div>
                  {Array.from({ length: 24 }, (_, h) => (
                    <div key={h} className="text-[9px] text-gray-400 text-center">{h}</div>
                  ))}
                  {matrix.days.map(d => (
                    <ReactFragment key={d}>
                      <div className="text-[10px] text-gray-500 pr-2 flex items-center justify-end">{d}</div>
                      {Array.from({ length: 24 }, (_, h) => {
                        const cell = matrix.grid[d]?.[h]
                        const intensity = cell ? cell.spend / matrix.maxSpend : 0
                        const bg = intensity > 0
                          ? `rgba(37, 99, 235, ${0.15 + intensity * 0.65})`
                          : 'rgb(243, 244, 246)'
                        const hasConv = cell && cell.conversions > 0
                        return (
                          <div
                            key={h}
                            className="h-5 m-0.5 rounded text-[8px] flex items-center justify-center text-white font-bold"
                            style={{ background: bg }}
                            title={cell ? `${d} ${h}:00 — ${fmtCur(cell.spend, currency)} · ${cell.conversions} conv · CVR ${fmtPct(cell.cvr)}` : `${d} ${h}:00 — no data`}
                          >
                            {hasConv ? '✓' : ''}
                          </div>
                        )
                      })}
                    </ReactFragment>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Action lists */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-red-50 rounded-lg p-3">
              <p className="text-xs font-semibold text-gray-700 mb-2">❌ Waste hours (spend with zero conversions)</p>
              {data.waste_hours.length === 0 ? (
                <p className="text-xs text-gray-500">None — no large waste detected.</p>
              ) : (
                <div className="space-y-1">
                  {data.waste_hours.slice(0, 6).map((h, i) => (
                    <div key={i} className="text-xs flex items-center justify-between">
                      <span className="font-mono">{String(h.hour).padStart(2, '0')}:00</span>
                      <span className="text-gray-600">{fmtCur(h.spend, currency)} ({((h.spend_share || 0) * 100).toFixed(1)}%) · {fmtNum(h.clicks)} clicks · 0 conv</span>
                    </div>
                  ))}
                  <p className="text-[10px] text-gray-500 mt-2">→ Apply ad scheduling (dayparting)</p>
                </div>
              )}
            </div>
            <div className="bg-green-50 rounded-lg p-3">
              <p className="text-xs font-semibold text-gray-700 mb-2">✅ Peak hours (high ROAS)</p>
              {data.peak_hours.length === 0 ? (
                <p className="text-xs text-gray-500">None — no clear peak yet.</p>
              ) : (
                <div className="space-y-1">
                  {data.peak_hours.slice(0, 6).map((h, i) => (
                    <div key={i} className="text-xs flex items-center justify-between">
                      <span className="font-mono">{String(h.hour).padStart(2, '0')}:00</span>
                      <span className="text-gray-600">{h.roas.toFixed(2)}x ROAS · {fmtNum(h.conversions)} conv</span>
                    </div>
                  ))}
                  <p className="text-[10px] text-gray-500 mt-2">→ Increase bids during these hours</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </PanelShell>
  )
}

// Tiny shim so we can use fragments in a TS-strict setting where React is in scope via JSX.
function ReactFragment({ children }: { children: React.ReactNode }) {
  return <>{children}</>
}
