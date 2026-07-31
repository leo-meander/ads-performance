'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { API_BASE } from '@/lib/api'

// Revenue is reported in each property's own currency — never sum across
// branches. Same rule as the ads dashboard.
const BRANCH_CURRENCY: Record<string, string> = {
  Saigon: 'VND', Taipei: 'TWD', '1948': 'TWD', Osaka: 'JPY', Oani: 'TWD',
}

type HostScope = 'all' | 'site' | 'booking'

type Property = {
  property_id: string
  account_id: string
  account_names: string[]
  branch: string | null
}

type Envelope = {
  branch: string
  property_id: string
  date_from: string
  date_to: string
  host_scope: HostScope
  conversion_metric: string
  shared_property_with: string[]
}

type Summary = {
  sessions: number; active_users: number; new_users: number; page_views: number
  engaged_sessions: number; engagement_rate: number | null
  avg_session_duration_sec: number | null; bounce_rate: number | null
  key_events: number; revenue: number
  conversion_rate: number | null; revenue_per_session: number | null
}

type TrendPoint = { date: string; sessions: number; active_users: number; key_events: number; revenue: number }
type Overview = Envelope & { summary: Summary; previous: (Summary & { date_from: string; date_to: string }) | null; trend: TrendPoint[] }

type Breakdown = {
  sessions: number; engaged_sessions: number; engagement_rate: number | null
  key_events: number; revenue: number
  conversion_rate: number | null; revenue_per_session: number | null
}
type ChannelRow = Breakdown & { channel: string }
type SourceRow = Breakdown & { source_medium: string }
type DeviceRow = Breakdown & { device: string }
type PageRow = Breakdown & { page: string }
type CountryRow = Breakdown & { country: string }
type HostRow = Breakdown & { host: string }

type Acquisition = Envelope & {
  channels: ChannelRow[]
  sources: SourceRow[]
  campaigns: (Breakdown & { campaign: string })[]
  self_referral: { detected: boolean; rows: SourceRow[]; note: string | null }
}

type Devices = Envelope & {
  devices: DeviceRow[]
  device_channel_matrix: { device: string; channel: string; sessions: number; key_events: number; revenue: number; conversion_rate: number | null }[]
  verdict: { best_revenue_per_session: string | null; desktop_vs_mobile_rps_ratio: number | null }
}

type FunnelStep = {
  event: string; label: string; users: number; count: number
  pct_of_top: number | null; step_conversion: number | null; dropoff: number | null; present: boolean
}
type Funnel = Envelope & {
  steps: FunnelStep[]
  by_device: { device: string; steps: { event: string; label: string; users: number }[]; top_to_purchase: number | null }[]
  other_events: { event: string; count: number; users: number }[]
  caveat: string
}

type Pages = Envelope & {
  pages: PageRow[]; countries: CountryRow[]; hosts: HostRow[]; foreign_branch_hosts: HostRow[]
}

const PRESETS: Record<string, number> = { '7d': 7, '28d': 28, '90d': 90 }

function isoDaysAgo(n: number) {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

function fmtInt(n: number | null | undefined) {
  if (n === null || n === undefined) return '—'
  return Math.round(n).toLocaleString('en-US')
}

function fmtPct(n: number | null | undefined, digits = 1) {
  if (n === null || n === undefined) return '—'
  return `${(n * 100).toFixed(digits)}%`
}

function fmtMoney(n: number | null | undefined, currency: string) {
  if (n === null || n === undefined) return '—'
  const digits = currency === 'VND' || currency === 'JPY' ? 0 : 0
  return `${Math.round(n).toLocaleString('en-US', { maximumFractionDigits: digits })} ${currency}`
}

function fmtDuration(sec: number | null | undefined) {
  if (!sec) return '—'
  const m = Math.floor(sec / 60)
  const s = Math.round(sec % 60)
  return `${m}m ${s}s`
}

function delta(current: number | null | undefined, previous: number | null | undefined) {
  if (current === null || current === undefined || !previous) return null
  return (current - previous) / previous
}

function DeltaBadge({ value, invert = false }: { value: number | null; invert?: boolean }) {
  if (value === null || !isFinite(value)) return null
  const good = invert ? value < 0 : value > 0
  const cls = Math.abs(value) < 0.005 ? 'text-gray-400' : good ? 'text-emerald-600' : 'text-rose-600'
  return (
    <span className={`text-xs font-medium ${cls}`}>
      {value > 0 ? '+' : ''}{(value * 100).toFixed(1)}%
    </span>
  )
}

function Card({ label, value, sub, delta: d, invert }: {
  label: string; value: string; sub?: string; delta?: number | null; invert?: boolean
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-xl font-semibold text-gray-900 mt-1">{value}</div>
      <div className="flex items-center gap-2 mt-1">
        {d !== undefined && <DeltaBadge value={d ?? null} invert={invert} />}
        {sub && <span className="text-xs text-gray-400">{sub}</span>}
      </div>
    </div>
  )
}

function Section({ title, note, children, right }: {
  title: string; note?: string; children: React.ReactNode; right?: React.ReactNode
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <h2 className="text-sm font-semibold text-gray-700">{title}</h2>
          {note && <p className="text-xs text-gray-400 mt-0.5 max-w-2xl">{note}</p>}
        </div>
        {right}
      </div>
      {children}
    </div>
  )
}

function Banner({ tone, title, children }: {
  tone: 'warn' | 'info'; title: string; children: React.ReactNode
}) {
  const cls = tone === 'warn'
    ? 'bg-amber-50 border-amber-200 text-amber-900'
    : 'bg-sky-50 border-sky-200 text-sky-900'
  return (
    <div className={`border rounded-xl px-4 py-3 mb-4 text-xs ${cls}`}>
      <div className="font-semibold mb-0.5">{title}</div>
      <div className="leading-relaxed">{children}</div>
    </div>
  )
}

const TH = 'py-2 px-3 text-gray-500 font-medium text-xs'
const TD = 'py-2 px-3 text-xs text-gray-700'

export default function AnalyticsPage() {
  const [properties, setProperties] = useState<Property[]>([])
  const [branch, setBranch] = useState<string>('')
  const [preset, setPreset] = useState<string>('28d')
  const [dateFrom, setDateFrom] = useState(isoDaysAgo(28))
  const [dateTo, setDateTo] = useState(isoDaysAgo(1))
  const [hostScope, setHostScope] = useState<HostScope>('all')

  const [overview, setOverview] = useState<Overview | null>(null)
  const [acquisition, setAcquisition] = useState<Acquisition | null>(null)
  const [devices, setDevices] = useState<Devices | null>(null)
  const [funnel, setFunnel] = useState<Funnel | null>(null)
  const [pages, setPages] = useState<Pages | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const currency = BRANCH_CURRENCY[branch] || ''

  useEffect(() => {
    fetch(`${API_BASE}/api/ga4/properties`, { credentials: 'include' })
      .then(r => r.json())
      .then(body => {
        if (!body.success) { setError(body.error); return }
        const props: Property[] = (body.data.properties || []).filter((p: Property) => p.branch)
        setProperties(props)
        if (props.length && !branch) setBranch(props[0].branch as string)
      })
      .catch(e => setError(String(e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const applyPreset = (key: string) => {
    setPreset(key)
    if (PRESETS[key]) {
      setDateFrom(isoDaysAgo(PRESETS[key]))
      setDateTo(isoDaysAgo(1))
    }
  }

  const load = useCallback(async () => {
    if (!branch) return
    setLoading(true)
    setError(null)
    const qs = `branch=${encodeURIComponent(branch)}&date_from=${dateFrom}&date_to=${dateTo}&host_scope=${hostScope}`
    try {
      // Five parallel requests — one combined endpoint would serialise ~12
      // GA4 reports behind a single spinner.
      const [ov, ac, dv, fn, pg] = await Promise.all([
        fetch(`${API_BASE}/api/ga4/overview?${qs}`, { credentials: 'include' }).then(r => r.json()),
        fetch(`${API_BASE}/api/ga4/acquisition?${qs}`, { credentials: 'include' }).then(r => r.json()),
        fetch(`${API_BASE}/api/ga4/devices?${qs}`, { credentials: 'include' }).then(r => r.json()),
        fetch(`${API_BASE}/api/ga4/funnel?${qs}`, { credentials: 'include' }).then(r => r.json()),
        fetch(`${API_BASE}/api/ga4/pages?${qs}`, { credentials: 'include' }).then(r => r.json()),
      ])
      const firstError = [ov, ac, dv, fn, pg].find(b => !b.success)
      if (firstError) setError(firstError.error)
      setOverview(ov.success ? ov.data : null)
      setAcquisition(ac.success ? ac.data : null)
      setDevices(dv.success ? dv.data : null)
      setFunnel(fn.success ? fn.data : null)
      setPages(pg.success ? pg.data : null)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [branch, dateFrom, dateTo, hostScope])

  useEffect(() => { load() }, [load])

  const s = overview?.summary
  const prev = overview?.previous

  const funnelChartData = useMemo(
    () => (funnel?.steps || []).map(st => ({ name: st.label, users: st.users })),
    [funnel],
  )

  const deviceLeader = devices?.verdict.best_revenue_per_session
  const rpsRatio = devices?.verdict.desktop_vs_mobile_rps_ratio

  return (
    <div className="p-6 max-w-[1400px]">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">GA4 Analytics</h1>
          <p className="text-xs text-gray-500 mt-1">
            Live from the Google Analytics Data API — no sync, no cache staleness beyond 10 minutes.
            Traffic sources, device behaviour, and the booking funnel.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={branch} onChange={e => setBranch(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          {properties.map(p => <option key={p.property_id} value={p.branch as string}>{p.branch}</option>)}
        </select>
        <select value={preset} onChange={e => applyPreset(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="7d">Last 7 days</option>
          <option value="28d">Last 28 days</option>
          <option value="90d">Last 90 days</option>
          <option value="custom">Custom</option>
        </select>
        <input type="date" value={dateFrom} onChange={e => { setDateFrom(e.target.value); setPreset('custom') }} className="px-2 py-1.5 border border-gray-200 rounded-lg text-sm" />
        <span className="text-gray-400 text-sm">→</span>
        <input type="date" value={dateTo} onChange={e => { setDateTo(e.target.value); setPreset('custom') }} className="px-2 py-1.5 border border-gray-200 rounded-lg text-sm" />
        <span className="text-xs text-gray-400 ml-2">Hosts:</span>
        <select value={hostScope} onChange={e => setHostScope(e.target.value as HostScope)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="all">All hosts in property</option>
          <option value="site">Branch site only</option>
          <option value="booking">Booking engine only</option>
        </select>
        {overview && (
          <span className="text-xs text-gray-400 ml-2">
            Property {overview.property_id} · {overview.date_from} → {overview.date_to}
          </span>
        )}
      </div>

      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-800 rounded-xl px-4 py-3 mb-4 text-sm">{error}</div>
      )}

      {overview && overview.shared_property_with.length > 0 && hostScope === 'all' && (
        <Banner tone="warn" title="This property is shared with other branches">
          Property {overview.property_id} is also tagged on the{' '}
          <strong>{overview.shared_property_with.join(' and ')}</strong> site{overview.shared_property_with.length > 1 ? 's' : ''},
          so these property-wide totals double-count that traffic. Switch Hosts to{' '}
          <strong>Branch site only</strong> for numbers that belong to {overview.branch} alone — or fix the GA4/GTM
          tagging so each site reports to one property.
        </Banner>
      )}

      {pages && pages.foreign_branch_hosts.length > 0 && hostScope === 'all' && (
        <Banner tone="warn" title="Another branch's site is reporting into this property">
          {pages.foreign_branch_hosts.map(h => `${h.host} (${fmtInt(h.sessions)} sessions)`).join(', ')}.
          Those sessions are included in every total on this page while Hosts is set to “All hosts in property”.
        </Banner>
      )}

      {acquisition?.self_referral.detected && (
        <Banner tone="info" title="Booking-engine self-referral detected">
          {acquisition.self_referral.note} Channel-level conversion counts below are directional —
          for settlement-grade revenue attribution use the ads platform numbers and Booking from Ads.
        </Banner>
      )}

      {hostScope === 'site' && (
        <Banner tone="info" title="Branch-site scope excludes the booking engine">
          Purchases fire on the Cloudbeds host, so conversions and revenue will read near zero here.
          This scope answers “how is my site performing”, not “how many bookings did we get”.
        </Banner>
      )}

      {/* ── KPI row ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-4">
        <Card label="Sessions" value={fmtInt(s?.sessions)} delta={delta(s?.sessions, prev?.sessions)} />
        <Card label="Active users" value={fmtInt(s?.active_users)} delta={delta(s?.active_users, prev?.active_users)} />
        <Card label="New users" value={fmtInt(s?.new_users)} sub={s ? `${fmtPct(s.new_users / (s.active_users || 1))} of users` : ''} />
        <Card label="Engagement rate" value={fmtPct(s?.engagement_rate)} delta={delta(s?.engagement_rate, prev?.engagement_rate)} />
        <Card label="Avg session" value={fmtDuration(s?.avg_session_duration_sec)} />
        <Card label="Bounce rate" value={fmtPct(s?.bounce_rate)} invert />
        <Card label="Key events" value={fmtInt(s?.key_events)} delta={delta(s?.key_events, prev?.key_events)} />
        <Card label="Conversion rate" value={fmtPct(s?.conversion_rate, 2)} delta={delta(s?.conversion_rate, prev?.conversion_rate)} />
        <Card label="Revenue" value={fmtMoney(s?.revenue, currency)} delta={delta(s?.revenue, prev?.revenue)} />
        <Card label="Revenue / session" value={fmtMoney(s?.revenue_per_session, currency)} delta={delta(s?.revenue_per_session, prev?.revenue_per_session)} />
        <Card label="Page views" value={fmtInt(s?.page_views)} />
        <Card label="Engaged sessions" value={fmtInt(s?.engaged_sessions)} />
      </div>

      {prev && (
        <p className="text-xs text-gray-400 mb-4">
          Deltas compare against {prev.date_from} → {prev.date_to} (the preceding equal-length period).
        </p>
      )}

      {/* ── trend ───────────────────────────────────────────────────── */}
      <Section title="Daily trend">
        {overview?.trend?.length ? (
          <ResponsiveContainer width="100%" height={260}>
            <AreaChart data={overview.trend}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} />
              <YAxis yAxisId="l" tick={{ fontSize: 11 }} />
              <YAxis yAxisId="r" orientation="right" tick={{ fontSize: 11 }} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Area yAxisId="l" type="monotone" dataKey="sessions" name="Sessions" stroke="#2563eb" fill="#dbeafe" />
              <Area yAxisId="r" type="monotone" dataKey="key_events" name="Key events" stroke="#059669" fill="#d1fae5" />
            </AreaChart>
          </ResponsiveContainer>
        ) : <div className="h-[200px] flex items-center justify-center text-gray-400 text-sm">No data</div>}
      </Section>

      {/* ── devices ─────────────────────────────────────────────────── */}
      <Section
        title="Device — who actually books"
        note="Mobile always wins on session volume, so compare revenue per session instead. That is the number that tells you which device converts."
      >
        {deviceLeader && (
          <div className="mb-4 text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-lg px-4 py-3">
            <strong className="capitalize">{deviceLeader}</strong> earns the most per session
            {rpsRatio ? <> — desktop is <strong>{rpsRatio.toFixed(1)}×</strong> mobile on revenue per session</> : null}.
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="bg-gray-50 border-b">
              <th className={`text-left ${TH}`}>Device</th>
              <th className={`text-right ${TH}`}>Sessions</th>
              <th className={`text-right ${TH}`}>Share</th>
              <th className={`text-right ${TH}`}>Engagement</th>
              <th className={`text-right ${TH}`}>Key events</th>
              <th className={`text-right ${TH}`}>Conv. rate</th>
              <th className={`text-right ${TH}`}>Revenue</th>
              <th className={`text-right ${TH}`}>Rev / session</th>
            </tr></thead>
            <tbody>
              {(devices?.devices || []).map(d => {
                const total = (devices?.devices || []).reduce((a, x) => a + x.sessions, 0) || 1
                return (
                  <tr key={d.device} className="border-b last:border-0">
                    <td className={`${TD} font-medium capitalize`}>{d.device}</td>
                    <td className={`${TD} text-right`}>{fmtInt(d.sessions)}</td>
                    <td className={`${TD} text-right text-gray-400`}>{fmtPct(d.sessions / total)}</td>
                    <td className={`${TD} text-right`}>{fmtPct(d.engagement_rate)}</td>
                    <td className={`${TD} text-right`}>{fmtInt(d.key_events)}</td>
                    <td className={`${TD} text-right`}>{fmtPct(d.conversion_rate, 2)}</td>
                    <td className={`${TD} text-right`}>{fmtMoney(d.revenue, currency)}</td>
                    <td className={`${TD} text-right font-semibold`}>{fmtMoney(d.revenue_per_session, currency)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {!!devices?.device_channel_matrix?.length && (
          <>
            <h3 className="text-xs font-semibold text-gray-600 mt-6 mb-2">Device × channel</h3>
            <div className="overflow-x-auto max-h-[320px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0"><tr className="bg-gray-50 border-b">
                  <th className={`text-left ${TH}`}>Device</th>
                  <th className={`text-left ${TH}`}>Channel</th>
                  <th className={`text-right ${TH}`}>Sessions</th>
                  <th className={`text-right ${TH}`}>Key events</th>
                  <th className={`text-right ${TH}`}>Conv. rate</th>
                  <th className={`text-right ${TH}`}>Revenue</th>
                </tr></thead>
                <tbody>
                  {devices.device_channel_matrix.slice(0, 40).map((r, i) => (
                    <tr key={i} className="border-b last:border-0">
                      <td className={`${TD} capitalize`}>{r.device}</td>
                      <td className={TD}>{r.channel}</td>
                      <td className={`${TD} text-right`}>{fmtInt(r.sessions)}</td>
                      <td className={`${TD} text-right`}>{fmtInt(r.key_events)}</td>
                      <td className={`${TD} text-right`}>{fmtPct(r.conversion_rate, 2)}</td>
                      <td className={`${TD} text-right`}>{fmtMoney(r.revenue, currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>

      {/* ── funnel ──────────────────────────────────────────────────── */}
      <Section title="Booking funnel" note={funnel?.caveat}>
        <div className="grid lg:grid-cols-2 gap-6">
          <div>
            {funnelChartData.length > 0 && (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={funnelChartData} layout="vertical" margin={{ left: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 11 }} />
                  <Tooltip contentStyle={{ fontSize: 12 }} />
                  <Bar dataKey="users" name="Users" fill="#2563eb" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="bg-gray-50 border-b">
                <th className={`text-left ${TH}`}>Step</th>
                <th className={`text-right ${TH}`}>Users</th>
                <th className={`text-right ${TH}`}>Events</th>
                <th className={`text-right ${TH}`}>vs step above</th>
                <th className={`text-right ${TH}`}>vs sessions</th>
              </tr></thead>
              <tbody>
                {(funnel?.steps || []).map(st => (
                  <tr key={st.event} className={`border-b last:border-0 ${st.present ? '' : 'opacity-40'}`}>
                    <td className={TD}>
                      <div className="font-medium">{st.label}</div>
                      <div className="text-[10px] text-gray-400 font-mono">{st.event}</div>
                    </td>
                    <td className={`${TD} text-right`}>{fmtInt(st.users)}</td>
                    <td className={`${TD} text-right text-gray-400`}>{fmtInt(st.count)}</td>
                    <td className={`${TD} text-right`}>
                      {st.step_conversion === null ? '—' : (
                        <span className={st.dropoff !== null && st.dropoff > 0.7 ? 'text-rose-600 font-medium' : ''}>
                          {fmtPct(st.step_conversion)}
                        </span>
                      )}
                    </td>
                    <td className={`${TD} text-right text-gray-500`}>{fmtPct(st.pct_of_top, 2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {!!funnel?.by_device?.length && (
          <>
            <h3 className="text-xs font-semibold text-gray-600 mt-6 mb-2">Funnel by device</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="bg-gray-50 border-b">
                  <th className={`text-left ${TH}`}>Device</th>
                  {(funnel.steps || []).map(st => <th key={st.event} className={`text-right ${TH}`}>{st.label}</th>)}
                  <th className={`text-right ${TH}`}>Session → booking</th>
                </tr></thead>
                <tbody>
                  {funnel.by_device.map(d => (
                    <tr key={d.device} className="border-b last:border-0">
                      <td className={`${TD} font-medium capitalize`}>{d.device}</td>
                      {d.steps.map(st => <td key={st.event} className={`${TD} text-right`}>{fmtInt(st.users)}</td>)}
                      <td className={`${TD} text-right font-semibold`}>{fmtPct(d.top_to_purchase, 2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Section>

      {/* ── acquisition ─────────────────────────────────────────────── */}
      <Section title="Traffic sources" note="Channel group is GA4's own classification. Source / medium is the raw truth underneath it.">
        <div className="grid lg:grid-cols-2 gap-6">
          <div>
            <h3 className="text-xs font-semibold text-gray-600 mb-2">By channel group</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead><tr className="bg-gray-50 border-b">
                  <th className={`text-left ${TH}`}>Channel</th>
                  <th className={`text-right ${TH}`}>Sessions</th>
                  <th className={`text-right ${TH}`}>Conv. rate</th>
                  <th className={`text-right ${TH}`}>Revenue</th>
                </tr></thead>
                <tbody>
                  {(acquisition?.channels || []).map(c => (
                    <tr key={c.channel} className="border-b last:border-0">
                      <td className={TD}>{c.channel}</td>
                      <td className={`${TD} text-right`}>{fmtInt(c.sessions)}</td>
                      <td className={`${TD} text-right`}>{fmtPct(c.conversion_rate, 2)}</td>
                      <td className={`${TD} text-right`}>{fmtMoney(c.revenue, currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <h3 className="text-xs font-semibold text-gray-600 mb-2">By source / medium</h3>
            <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0"><tr className="bg-gray-50 border-b">
                  <th className={`text-left ${TH}`}>Source / medium</th>
                  <th className={`text-right ${TH}`}>Sessions</th>
                  <th className={`text-right ${TH}`}>Conv. rate</th>
                  <th className={`text-right ${TH}`}>Revenue</th>
                </tr></thead>
                <tbody>
                  {(acquisition?.sources || []).map(sr => (
                    <tr key={sr.source_medium} className="border-b last:border-0">
                      <td className={`${TD} max-w-[220px] truncate`} title={sr.source_medium}>{sr.source_medium}</td>
                      <td className={`${TD} text-right`}>{fmtInt(sr.sessions)}</td>
                      <td className={`${TD} text-right`}>{fmtPct(sr.conversion_rate, 2)}</td>
                      <td className={`${TD} text-right`}>{fmtMoney(sr.revenue, currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </Section>

      {/* ── pages / countries / hosts ───────────────────────────────── */}
      <Section title="Landing pages, countries, hosts">
        <div className="grid lg:grid-cols-3 gap-6">
          {[
            { title: 'Top landing pages', rows: pages?.pages || [], key: 'page' as const },
            { title: 'Countries', rows: pages?.countries || [], key: 'country' as const },
            { title: 'Hosts in this property', rows: pages?.hosts || [], key: 'host' as const },
          ].map(block => (
            <div key={block.title}>
              <h3 className="text-xs font-semibold text-gray-600 mb-2">{block.title}</h3>
              <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0"><tr className="bg-gray-50 border-b">
                    <th className={`text-left ${TH}`}>Name</th>
                    <th className={`text-right ${TH}`}>Sessions</th>
                    <th className={`text-right ${TH}`}>Revenue</th>
                  </tr></thead>
                  <tbody>
                    {(block.rows as any[]).map((r, i) => (
                      <tr key={i} className="border-b last:border-0">
                        <td className={`${TD} max-w-[200px] truncate`} title={r[block.key]}>{r[block.key] || '—'}</td>
                        <td className={`${TD} text-right`}>{fmtInt(r.sessions)}</td>
                        <td className={`${TD} text-right`}>{fmtMoney(r.revenue, currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {!!funnel?.other_events?.length && (
        <Section title="All other events" note="Anything fired outside the funnel — useful for spotting a new GTM tag or a broken one.">
          <div className="flex flex-wrap gap-2">
            {funnel.other_events.map(e => (
              <span key={e.event} className="text-xs bg-gray-100 text-gray-700 rounded-lg px-2 py-1">
                <span className="font-mono">{e.event}</span>
                <span className="text-gray-400 ml-1.5">{fmtInt(e.count)}</span>
              </span>
            ))}
          </div>
        </Section>
      )}
    </div>
  )
}
