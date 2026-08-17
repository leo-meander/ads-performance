'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { ArrowUpDown, ExternalLink, RefreshCw } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

// One table row. In "Ad name" pivot mode `key` is branch+name and ad_id is
// null; in per-ad mode `key` is the ad_id.
interface AdRow {
  key: string
  account_id: string
  ad_id: string | null
  ad_name: string | null
  ad_count: number
  campaign_count: number
  adset_count: number
  campaign_id: string | null
  campaign_name: string | null
  adset_name: string | null
  spend: number | null
  impressions: number
  clicks: number
  conversions: number
  revenue: number | null
  leads: number
  roas: number | null
  cost_per_purchase: number | null
  cost_per_lead: number | null
  ctr: number | null
  engagement_rate: number | null
  hook_rate: number | null
  thruplay_rate: number | null
  video_complete_rate: number | null
  // Live state from meta_ad_states — "right now", not the date window. A
  // pivoted row folds several ads: active_count of state_count are delivering.
  effective_status: string | null
  active_count: number
  state_count: number
  preview_url: string | null
}
interface DailyRow {
  date: string; key: string; ad_id: string | null; ad_name: string | null
  campaign_name: string | null; adset_name: string | null
  spend: number | null; roas: number | null; conversions: number
  leads: number; cost_per_lead: number | null; cost_per_purchase: number | null
  ctr: number | null; hook_rate: number | null
}
interface Account { id: string; account_name: string; platform: string; currency: string }

// Local YYYY-MM-DD (avoids the UTC drift of toISOString()).
const fmtISO = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

// Quick date-range presets for the filter bar. Returns [from, to] inclusive.
type PresetKey = 'yesterday' | 'last7' | 'last30' | 'thisMonth' | 'lastMonth' | 'custom'
const PRESETS: { key: PresetKey; label: string }[] = [
  { key: 'last7', label: 'Last 7 days' },
  { key: 'last30', label: 'Last 30 days' },
  { key: 'thisMonth', label: 'This month' },
  { key: 'lastMonth', label: 'Last month' },
  { key: 'yesterday', label: 'Yesterday' },
  { key: 'custom', label: 'Custom' },
]
const presetRange = (key: PresetKey): [string, string] => {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const shift = (days: number) => { const d = new Date(today); d.setDate(d.getDate() + days); return d }
  switch (key) {
    case 'yesterday': return [fmtISO(shift(-1)), fmtISO(shift(-1))]
    case 'last7': return [fmtISO(shift(-6)), fmtISO(today)]
    case 'last30': return [fmtISO(shift(-29)), fmtISO(today)]
    case 'thisMonth': return [fmtISO(new Date(today.getFullYear(), today.getMonth(), 1)), fmtISO(today)]
    case 'lastMonth': return [
      fmtISO(new Date(today.getFullYear(), today.getMonth() - 1, 1)),
      fmtISO(new Date(today.getFullYear(), today.getMonth(), 0)),
    ]
    default: return [fmtISO(today), fmtISO(today)]
  }
}

const fmtNum = (n: number) => Math.round(n).toLocaleString()

// Monetary values are stored in each branch's native currency.
const CUR_SYM: Record<string, string> = { VND: '₫', TWD: 'NT$', JPY: '¥', USD: '$', EUR: '€', KRW: '₩', THB: '฿' }
const curLabel = (cur?: string | null) => (cur ? (CUR_SYM[cur] || cur) : '')
const money = (n: number | null, cur?: string | null) => {
  if (n == null) return '—'
  const s = curLabel(cur)
  return s ? `${fmtNum(n)} ${s}` : fmtNum(n)
}

// Chart-able metrics. `pct` => stored as a 0..1 fraction.
type MetricKey = 'roas' | 'spend' | 'conversions' | 'leads' | 'cost_per_lead' | 'cost_per_purchase' | 'ctr' | 'hook_rate'
const METRICS: Record<MetricKey, { label: string; pct?: boolean; money?: boolean; fmt: (v: number | null) => string }> = {
  roas: { label: 'ROAS', fmt: v => v == null ? '—' : `${v.toFixed(2)}x` },
  spend: { label: 'Spend', money: true, fmt: v => v == null ? '—' : fmtNum(v) },
  conversions: { label: 'Bookings', fmt: v => v == null ? '—' : String(v) },
  leads: { label: 'Leads', fmt: v => v == null ? '—' : String(v) },
  cost_per_lead: { label: 'Cost / Lead', money: true, fmt: v => v == null ? '—' : fmtNum(v) },
  cost_per_purchase: { label: 'CPP', money: true, fmt: v => v == null ? '—' : fmtNum(v) },
  ctr: { label: 'CTR', pct: true, fmt: v => v == null ? '—' : `${(v * 100).toFixed(2)}%` },
  hook_rate: { label: 'Hook rate', pct: true, fmt: v => v == null ? '—' : `${(v * 100).toFixed(1)}%` },
}

const COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#6366f1']

// Meta effective_status -> what to show. It already folds in the parent ad
// set / campaign switch, so an ad can be ON while its ad set is off — worth
// naming, since that's why a live-looking ad stopped spending.
const STATUS_UI: Record<string, { label: string; dot: string; text: string }> = {
  ACTIVE: { label: 'Active', dot: 'bg-emerald-500', text: 'text-emerald-700' },
  PAUSED: { label: 'Paused', dot: 'bg-gray-400', text: 'text-gray-500' },
  ADSET_PAUSED: { label: 'Ad set off', dot: 'bg-gray-400', text: 'text-gray-500' },
  CAMPAIGN_PAUSED: { label: 'Campaign off', dot: 'bg-gray-400', text: 'text-gray-500' },
  ARCHIVED: { label: 'Archived', dot: 'bg-gray-300', text: 'text-gray-400' },
  DELETED: { label: 'Deleted', dot: 'bg-gray-300', text: 'text-gray-400' },
  DISAPPROVED: { label: 'Rejected', dot: 'bg-red-500', text: 'text-red-600' },
  WITH_ISSUES: { label: 'Issues', dot: 'bg-amber-500', text: 'text-amber-600' },
  PENDING_REVIEW: { label: 'In review', dot: 'bg-amber-400', text: 'text-amber-600' },
  PREAPPROVED: { label: 'Pre-approved', dot: 'bg-amber-400', text: 'text-amber-600' },
  PENDING_BILLING_INFO: { label: 'Billing', dot: 'bg-amber-500', text: 'text-amber-600' },
  IN_PROCESS: { label: 'Processing', dot: 'bg-blue-400', text: 'text-blue-600' },
}

// Row grain. "ad_name" pivots every ad sharing a name (within one branch —
// spend is in the branch's native currency, so names are never merged across
// branches) into a single row.
type GroupKey = 'ad' | 'ad_name'
const GROUPS: { key: GroupKey; label: string }[] = [
  { key: 'ad', label: 'Each ad' },
  { key: 'ad_name', label: 'Ad name (pivot)' },
]

// One status pill. A pivoted row covers several ads, so it also shows how many
// of them are still delivering ("Active 2/3") rather than picking one answer.
const StatusCell = ({ row }: { row: AdRow }) => {
  if (!row.effective_status) {
    return (
      <span className="text-xs text-gray-300" title="No live ad found — deleted from the account, or not synced yet">—</span>
    )
  }
  const ui = STATUS_UI[row.effective_status] ||
    { label: row.effective_status, dot: 'bg-gray-400', text: 'text-gray-500' }
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs whitespace-nowrap ${ui.text}`} title={row.effective_status}>
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${ui.dot}`} />
      {ui.label}{row.state_count > 1 && ` ${row.active_count}/${row.state_count}`}
    </span>
  )
}

export default function AdPerformancePage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [rows, setRows] = useState<AdRow[]>([])
  const [loading, setLoading] = useState(true)

  // Filters
  const [fBranch, setFBranch] = useState('')
  const [fCampaign, setFCampaign] = useState('')
  const [preset, setPreset] = useState<PresetKey>('thisMonth')
  const [dateFrom, setDateFrom] = useState(() => presetRange('thisMonth')[0])
  const [dateTo, setDateTo] = useState(() => presetRange('thisMonth')[1])
  const [metric, setMetric] = useState<MetricKey>('roas')
  const [groupBy, setGroupBy] = useState<GroupKey>('ad')
  const pivot = groupBy === 'ad_name'

  // Pick a preset -> set both date inputs. Manually editing a date below
  // flips the selector back to "Custom".
  const applyPreset = (key: PresetKey) => {
    setPreset(key)
    if (key === 'custom') return
    const [f, t] = presetRange(key)
    setDateFrom(f); setDateTo(t)
  }

  // Sort (server-side)
  const [sortBy, setSortBy] = useState('spend')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  // Comparison selection (row keys — ad_id, or branch+ad_name when pivoted)
  const [selected, setSelected] = useState<string[]>([])
  const [daily, setDaily] = useState<DailyRow[]>([])

  // Sync
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setAccounts(d.data.filter((a: Account) => a.platform === 'meta')) })
      .catch(() => {})
  }, [])

  const listParams = () => {
    const params = new URLSearchParams()
    if (fBranch) params.set('branch_id', fBranch)
    if (fCampaign) params.set('campaign_id', fCampaign)
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    params.set('sort_by', sortBy)
    params.set('sort_dir', sortDir)
    params.set('group_by', groupBy)
    return params
  }

  // Fetch the aggregated list whenever filters/sort/grain change.
  useEffect(() => {
    setLoading(true)
    fetch(`${API_BASE}/api/ad-performance?${listParams()}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setRows(d.data.items) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [fBranch, fCampaign, dateFrom, dateTo, sortBy, sortDir, groupBy])

  // Fetch per-day series for the selected rows (drill / compare). Pivoted rows
  // are requested by name — repeated params, since ad names may contain commas.
  useEffect(() => {
    if (selected.length === 0) { setDaily([]); return }
    const params = new URLSearchParams()
    if (pivot) {
      const names = new Set(selected.map(k => rowByKey[k]?.ad_name).filter((n): n is string => !!n))
      if (names.size === 0) { setDaily([]); return }
      names.forEach(n => params.append('ad_names', n))
    } else {
      params.set('ad_ids', selected.join(','))
    }
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    fetch(`${API_BASE}/api/ad-performance/daily?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setDaily(d.data.items) })
      .catch(() => {})
  }, [selected, dateFrom, dateTo, pivot])

  const refetchList = () => {
    fetch(`${API_BASE}/api/ad-performance?${listParams()}`, { credentials: 'include' })
      .then(r => r.json()).then(d => { if (d.success) setRows(d.data.items) }).catch(() => {})
  }

  const runSync = () => {
    setSyncing(true)
    const params = new URLSearchParams()
    if (dateFrom) params.set('since', dateFrom)
    if (dateTo) params.set('until', dateTo)
    if (fBranch) params.set('branch_id', fBranch)
    const branchLabel = fBranch ? accName(fBranch) : 'all branches'
    setSyncMsg(`Syncing ${branchLabel}, ${dateFrom} → ${dateTo}...`)
    fetch(`${API_BASE}/api/ad-performance/sync?${params}`, { method: 'POST', credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (!d.success) { setSyncMsg(`Error: ${d.error}`); setSyncing(false); return }
        setSyncMsg('Sync triggered — data will update in a few minutes.')
        // Background job; refetch a couple of times then stop the spinner.
        setTimeout(refetchList, 8000)
        setTimeout(() => { refetchList(); setSyncing(false) }, 20000)
      })
      .catch(() => { setSyncMsg('Sync failed'); setSyncing(false) })
  }

  const toggleSort = (col: string) => {
    if (sortBy === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortBy(col); setSortDir('desc') }
  }

  const toggleSelect = (key: string) => {
    setSelected(prev => prev.includes(key) ? prev.filter(x => x !== key) : [...prev, key])
  }

  // Switching grain invalidates every selected key (ad_id vs branch+name).
  const applyGroupBy = (key: GroupKey) => { setGroupBy(key); setSelected([]) }

  // Header tick: select every visible row, or clear when all are already on.
  const allSelected = rows.length > 0 && rows.every(r => selected.includes(r.key))
  const someSelected = rows.some(r => selected.includes(r.key))
  const toggleSelectAll = () => setSelected(allSelected ? [] : rows.map(r => r.key))

  const accName = (id: string) => accounts.find(a => a.id === id)?.account_name || '—'

  const rowByKey = useMemo(() => {
    const m: Record<string, AdRow> = {}
    rows.forEach(r => { m[r.key] = r })
    return m
  }, [rows])

  // Campaign filter options derived from the current rows. Pivoted rows span
  // several campaigns, so keep the options last seen in per-ad mode.
  const [campaigns, setCampaigns] = useState<[string, string][]>([])
  useEffect(() => {
    if (pivot) return
    const m = new Map<string, string>()
    rows.forEach(r => { if (r.campaign_id) m.set(r.campaign_id, r.campaign_name || r.campaign_id) })
    setCampaigns(Array.from(m.entries()).sort((a, b) => a[1].localeCompare(b[1])))
  }, [rows, pivot])

  // Currency lives on each branch (account). Map account/ad -> currency so
  // monetary columns render in the right currency per branch.
  const accountCurrency = useMemo(() => {
    const m: Record<string, string> = {}
    accounts.forEach(a => { m[a.id] = a.currency })
    return m
  }, [accounts])
  const adCurrency = useMemo(() => {
    const m: Record<string, string> = {}
    rows.forEach(r => { m[r.key] = accountCurrency[r.account_id] || '' })
    return m
  }, [rows, accountCurrency])
  // Only label the chart with a currency when the selected rows share one.
  const chartCurrency = useMemo(() => {
    const set = new Set(selected.map(k => adCurrency[k]).filter(Boolean))
    return set.size === 1 ? [...set][0] : ''
  }, [selected, adCurrency])

  // Reshape daily series into recharts rows: { date, [key]: metricValue }.
  const chartData = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string | null>>()
    daily.forEach(d => {
      const row = byDate.get(d.date) || { date: d.date }
      row[d.key] = d[metric] ?? null
      byDate.set(d.date, row)
    })
    return Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)))
  }, [daily, metric])

  // row key -> display label for legend.
  const adLabel = useMemo(() => {
    const m: Record<string, string> = {}
    rows.forEach(r => { m[r.key] = r.ad_name || r.ad_id || r.key })
    daily.forEach(d => { if (!m[d.key]) m[d.key] = d.ad_name || d.key })
    return m
  }, [rows, daily])

  const SortHeader = ({ col, label }: { col: string; label: string }) => (
    <th className="py-2 px-2 text-gray-500 font-medium text-xs cursor-pointer hover:text-gray-700 select-none text-right" onClick={() => toggleSort(col)}>
      <span className="inline-flex items-center gap-0.5">{label}{sortBy === col && <ArrowUpDown className="w-3 h-3" />}</span>
    </th>
  )

  const mcfg = METRICS[metric]

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Ad Name Performance</h1>
          <p className="text-xs text-gray-500 mt-1">
            Track each ad by day — pulled from Meta (only ads with spend).
            {pivot && ' Pivoted: ads sharing a name are merged per branch.'}
            {' '}Status and Preview show the ad as it is now, not inside the date range.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {syncMsg && <span className="text-xs text-gray-500">{syncMsg}</span>}
          <button
            onClick={runSync}
            disabled={syncing}
            className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            <RefreshCw className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`} /> Sync from Meta
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={fBranch} onChange={e => { setFBranch(e.target.value); setFCampaign('') }} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          <option value="">All Branches</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}
        </select>
        <select value={fCampaign} onChange={e => setFCampaign(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm max-w-[220px]">
          <option value="">All Campaigns</option>
          {campaigns.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
        <select value={preset} onChange={e => applyPreset(e.target.value as PresetKey)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          {PRESETS.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
        </select>
        <input type="date" value={dateFrom} onChange={e => { setDateFrom(e.target.value); setPreset('custom') }} className="px-2 py-1.5 border border-gray-200 rounded-lg text-sm" />
        <span className="text-gray-400 text-sm">→</span>
        <input type="date" value={dateTo} onChange={e => { setDateTo(e.target.value); setPreset('custom') }} className="px-2 py-1.5 border border-gray-200 rounded-lg text-sm" />
        <span className="text-xs text-gray-400 ml-2">Group by:</span>
        <select value={groupBy} onChange={e => applyGroupBy(e.target.value as GroupKey)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          {GROUPS.map(g => <option key={g.key} value={g.key}>{g.label}</option>)}
        </select>
        <span className="text-xs text-gray-400 ml-2">Chart metric:</span>
        <select value={metric} onChange={e => setMetric(e.target.value as MetricKey)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          {(Object.keys(METRICS) as MetricKey[]).map(k => <option key={k} value={k}>{METRICS[k].label}</option>)}
        </select>
      </div>

      {/* Comparison chart */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-700">{mcfg.label}{mcfg.money && chartCurrency ? ` (${curLabel(chartCurrency)})` : ''} by day {selected.length > 0 ? `— ${selected.length} ${pivot ? 'ad name' : 'ad'}` : ''}</h2>
          {selected.length > 0 && <button onClick={() => setSelected([])} className="text-xs text-blue-600">Clear selection</button>}
        </div>
        {selected.length === 0 ? (
          <div className="h-[300px] flex items-center justify-center text-gray-400 text-sm">Tick one or more {pivot ? 'ad names' : 'ads'} in the table below to see their daily trend.</div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v: string) => v.slice(5)} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => mcfg.pct ? `${(v * 100).toFixed(0)}%` : (metric === 'roas' ? `${v.toFixed(1)}x` : fmtNum(v))} />
              <Tooltip formatter={(v: number) => mcfg.money && chartCurrency ? `${mcfg.fmt(v)} ${curLabel(chartCurrency)}` : mcfg.fmt(v)} labelFormatter={(l) => `Date: ${l}`} />
              <Legend />
              {selected.map((adId, i) => (
                <Line key={adId} type="monotone" dataKey={adId} name={adLabel[adId] || adId} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-400">Loading...</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-gray-400">No data yet. Click "Sync from Meta" to pull it in.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="bg-gray-50 border-b">
                <th className="py-2 px-2 w-8 text-center">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    ref={el => { if (el) el.indeterminate = someSelected && !allSelected }}
                    onChange={toggleSelectAll}
                    className="w-3.5 h-3.5 cursor-pointer"
                    title={allSelected ? 'Clear all' : 'Select all'}
                  />
                </th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Campaign</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Ad Set</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Ad Name</th>
                <th className="text-center py-2 px-2 text-gray-500 font-medium text-xs">Preview</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Status</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Branch</th>
                {pivot && <SortHeader col="ad_count" label="Ads" />}
                <SortHeader col="spend" label="Spend" />
                <SortHeader col="roas" label="ROAS" />
                <SortHeader col="conversions" label="Book." />
                <SortHeader col="leads" label="Leads" />
                <SortHeader col="cost_per_lead" label="CPL" />
                <SortHeader col="ctr" label="CTR" />
                <SortHeader col="hook_rate" label="Hook" />
              </tr></thead>
              <tbody>{rows.map(r => {
                const sel = selected.includes(r.key)
                // A pivoted row spanning several campaigns/ad sets has no single
                // name to show — surface the count instead.
                const campaignCell = r.campaign_count > 1 ? `${r.campaign_count} campaigns` : (r.campaign_name || '—')
                const adsetCell = r.adset_count > 1 ? `${r.adset_count} ad sets` : (r.adset_name || '—')
                return (
                  <tr key={r.key} className={`border-b border-gray-50 hover:bg-gray-50 cursor-pointer ${sel ? 'bg-blue-50/40' : ''}`} onClick={() => toggleSelect(r.key)}>
                    <td className="py-2 px-2 text-center"><input type="checkbox" checked={sel} onChange={() => toggleSelect(r.key)} onClick={e => e.stopPropagation()} className="w-3.5 h-3.5" /></td>
                    <td className={`py-2 px-2 text-xs max-w-[160px] truncate ${r.campaign_count > 1 ? 'text-gray-400 italic' : 'text-gray-600'}`} title={r.campaign_count > 1 ? '' : (r.campaign_name || '')}>{campaignCell}</td>
                    <td className={`py-2 px-2 text-xs max-w-[160px] truncate ${r.adset_count > 1 ? 'text-gray-400 italic' : 'text-gray-600'}`} title={r.adset_count > 1 ? '' : (r.adset_name || '')}>{adsetCell}</td>
                    <td className="py-2 px-2 text-xs font-medium text-gray-900 max-w-[200px] truncate" title={r.ad_name || ''}>{r.ad_name || '—'}</td>
                    <td className="py-2 px-2 text-center">
                      {r.preview_url ? (
                        <a
                          href={r.preview_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={e => e.stopPropagation()}
                          className="inline-flex text-blue-600 hover:text-blue-800"
                          title={pivot && r.ad_count > 1 ? `Open one of the ${r.ad_count} ads on Meta` : 'Open this ad on Meta'}
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      ) : (
                        <span className="text-xs text-gray-300" title="No preview link — re-run Sync from Meta">—</span>
                      )}
                    </td>
                    <td className="py-2 px-2"><StatusCell row={r} /></td>
                    <td className="py-2 px-2 text-xs text-gray-600">{accName(r.account_id)}</td>
                    {pivot && <td className="py-2 px-2 text-right text-xs text-gray-600">{r.ad_count}</td>}
                    <td className="py-2 px-2 text-right text-xs">{money(r.spend, accountCurrency[r.account_id])}</td>
                    <td className="py-2 px-2 text-right text-xs font-semibold">{r.roas != null ? `${r.roas.toFixed(2)}x` : '—'}</td>
                    <td className="py-2 px-2 text-right text-xs">{r.conversions}</td>
                    <td className="py-2 px-2 text-right text-xs">{r.leads}</td>
                    <td className="py-2 px-2 text-right text-xs">{money(r.cost_per_lead, accountCurrency[r.account_id])}</td>
                    <td className="py-2 px-2 text-right text-xs">{r.ctr != null ? `${(r.ctr * 100).toFixed(2)}%` : '—'}</td>
                    <td className="py-2 px-2 text-right text-xs">{r.hook_rate != null ? `${(r.hook_rate * 100).toFixed(1)}%` : '—'}</td>
                  </tr>
                )
              })}</tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
