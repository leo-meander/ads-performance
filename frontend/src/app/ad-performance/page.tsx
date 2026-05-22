'use client'

import { useEffect, useMemo, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import { ArrowUpDown, RefreshCw } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface AdRow {
  account_id: string
  ad_id: string
  ad_name: string | null
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
}
interface DailyRow {
  date: string; ad_id: string; ad_name: string | null
  campaign_name: string | null; adset_name: string | null
  spend: number | null; roas: number | null; conversions: number
  leads: number; cost_per_lead: number | null; cost_per_purchase: number | null
  ctr: number | null; hook_rate: number | null
}
interface Account { id: string; account_name: string; platform: string }

// Today as YYYY-MM-DD (local).
const todayISO = () => new Date().toISOString().slice(0, 10)

const fmtNum = (n: number) => Math.round(n).toLocaleString()

// Chart-able metrics. `pct` => stored as a 0..1 fraction.
type MetricKey = 'roas' | 'spend' | 'conversions' | 'leads' | 'cost_per_lead' | 'cost_per_purchase' | 'ctr' | 'hook_rate'
const METRICS: Record<MetricKey, { label: string; pct?: boolean; fmt: (v: number | null) => string }> = {
  roas: { label: 'ROAS', fmt: v => v == null ? '—' : `${v.toFixed(2)}x` },
  spend: { label: 'Spend', fmt: v => v == null ? '—' : fmtNum(v) },
  conversions: { label: 'Bookings', fmt: v => v == null ? '—' : String(v) },
  leads: { label: 'Leads', fmt: v => v == null ? '—' : String(v) },
  cost_per_lead: { label: 'Cost / Lead', fmt: v => v == null ? '—' : fmtNum(v) },
  cost_per_purchase: { label: 'CPP', fmt: v => v == null ? '—' : fmtNum(v) },
  ctr: { label: 'CTR', pct: true, fmt: v => v == null ? '—' : `${(v * 100).toFixed(2)}%` },
  hook_rate: { label: 'Hook rate', pct: true, fmt: v => v == null ? '—' : `${(v * 100).toFixed(1)}%` },
}

const COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6', '#6366f1']

export default function AdPerformancePage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [rows, setRows] = useState<AdRow[]>([])
  const [loading, setLoading] = useState(true)

  // Filters
  const [fBranch, setFBranch] = useState('')
  const [fCampaign, setFCampaign] = useState('')
  const [dateFrom, setDateFrom] = useState('2026-05-01')
  const [dateTo, setDateTo] = useState(todayISO())
  const [metric, setMetric] = useState<MetricKey>('roas')

  // Sort (server-side)
  const [sortBy, setSortBy] = useState('spend')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  // Comparison selection (by ad_id)
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

  // Fetch the aggregated list whenever filters/sort change.
  useEffect(() => {
    const params = new URLSearchParams()
    if (fBranch) params.set('branch_id', fBranch)
    if (fCampaign) params.set('campaign_id', fCampaign)
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    params.set('sort_by', sortBy)
    params.set('sort_dir', sortDir)
    setLoading(true)
    fetch(`${API_BASE}/api/ad-performance?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setRows(d.data.items) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [fBranch, fCampaign, dateFrom, dateTo, sortBy, sortDir])

  // Fetch per-day series for the selected ads (drill / compare).
  useEffect(() => {
    if (selected.length === 0) { setDaily([]); return }
    const params = new URLSearchParams()
    params.set('ad_ids', selected.join(','))
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    fetch(`${API_BASE}/api/ad-performance/daily?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setDaily(d.data.items) })
      .catch(() => {})
  }, [selected, dateFrom, dateTo])

  const refetchList = () => {
    const params = new URLSearchParams()
    if (fBranch) params.set('branch_id', fBranch)
    if (fCampaign) params.set('campaign_id', fCampaign)
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    params.set('sort_by', sortBy); params.set('sort_dir', sortDir)
    fetch(`${API_BASE}/api/ad-performance?${params}`, { credentials: 'include' })
      .then(r => r.json()).then(d => { if (d.success) setRows(d.data.items) }).catch(() => {})
  }

  const runSync = () => {
    setSyncing(true)
    setSyncMsg('Đang đồng bộ từ Meta...')
    fetch(`${API_BASE}/api/ad-performance/sync`, { method: 'POST', credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (!d.success) { setSyncMsg(`Lỗi: ${d.error}`); setSyncing(false); return }
        setSyncMsg('Đã kích hoạt đồng bộ — dữ liệu sẽ cập nhật trong ít phút.')
        // Background job; refetch a couple of times then stop the spinner.
        setTimeout(refetchList, 8000)
        setTimeout(() => { refetchList(); setSyncing(false) }, 20000)
      })
      .catch(() => { setSyncMsg('Đồng bộ thất bại'); setSyncing(false) })
  }

  const toggleSort = (col: string) => {
    if (sortBy === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    else { setSortBy(col); setSortDir('desc') }
  }

  const toggleSelect = (adId: string) => {
    setSelected(prev => prev.includes(adId) ? prev.filter(x => x !== adId) : [...prev, adId])
  }

  const accName = (id: string) => accounts.find(a => a.id === id)?.account_name || '—'

  // Campaign filter options derived from the current rows.
  const campaigns = useMemo(() => {
    const m = new Map<string, string>()
    rows.forEach(r => { if (r.campaign_id) m.set(r.campaign_id, r.campaign_name || r.campaign_id) })
    return Array.from(m.entries()).sort((a, b) => a[1].localeCompare(b[1]))
  }, [rows])

  // Reshape daily series into recharts rows: { date, [ad_id]: metricValue }.
  const chartData = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string | null>>()
    daily.forEach(d => {
      const row = byDate.get(d.date) || { date: d.date }
      row[d.ad_id] = (d as Record<string, number | null>)[metric] ?? null
      byDate.set(d.date, row)
    })
    return Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)))
  }, [daily, metric])

  // ad_id -> display label for legend.
  const adLabel = useMemo(() => {
    const m: Record<string, string> = {}
    rows.forEach(r => { m[r.ad_id] = r.ad_name || r.ad_id })
    daily.forEach(d => { if (!m[d.ad_id]) m[d.ad_id] = d.ad_name || d.ad_id })
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
          <p className="text-xs text-gray-500 mt-1">Theo dõi từng ad theo ngày — pull từ Meta (chỉ ads có chi tiêu).</p>
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
        <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="px-2 py-1.5 border border-gray-200 rounded-lg text-sm" />
        <span className="text-gray-400 text-sm">→</span>
        <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="px-2 py-1.5 border border-gray-200 rounded-lg text-sm" />
        <span className="text-xs text-gray-400 ml-2">Chỉ số chart:</span>
        <select value={metric} onChange={e => setMetric(e.target.value as MetricKey)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-sm">
          {(Object.keys(METRICS) as MetricKey[]).map(k => <option key={k} value={k}>{METRICS[k].label}</option>)}
        </select>
      </div>

      {/* Comparison chart */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-700">{mcfg.label} theo ngày {selected.length > 0 ? `— ${selected.length} ad` : ''}</h2>
          {selected.length > 0 && <button onClick={() => setSelected([])} className="text-xs text-blue-600">Bỏ chọn</button>}
        </div>
        {selected.length === 0 ? (
          <div className="h-[300px] flex items-center justify-center text-gray-400 text-sm">Tick chọn 1 hoặc nhiều ad ở bảng dưới để xem đường tăng/giảm theo ngày.</div>
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v: string) => v.slice(5)} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => mcfg.pct ? `${(v * 100).toFixed(0)}%` : (metric === 'roas' ? `${v.toFixed(1)}x` : fmtNum(v))} />
              <Tooltip formatter={(v: number) => mcfg.fmt(v)} labelFormatter={(l) => `Ngày: ${l}`} />
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
          <div className="p-8 text-center text-gray-400">Đang tải...</div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-gray-400">Chưa có dữ liệu. Bấm "Sync from Meta" để kéo về.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="bg-gray-50 border-b">
                <th className="py-2 px-2 w-8"></th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Campaign</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Ad Set</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Ad Name</th>
                <th className="text-left py-2 px-2 text-gray-500 font-medium text-xs">Branch</th>
                <SortHeader col="spend" label="Spend" />
                <SortHeader col="roas" label="ROAS" />
                <SortHeader col="conversions" label="Book." />
                <SortHeader col="leads" label="Leads" />
                <SortHeader col="cost_per_lead" label="CPL" />
                <SortHeader col="ctr" label="CTR" />
                <SortHeader col="hook_rate" label="Hook" />
              </tr></thead>
              <tbody>{rows.map(r => {
                const sel = selected.includes(r.ad_id)
                return (
                  <tr key={r.ad_id} className={`border-b border-gray-50 hover:bg-gray-50 cursor-pointer ${sel ? 'bg-blue-50/40' : ''}`} onClick={() => toggleSelect(r.ad_id)}>
                    <td className="py-2 px-2 text-center"><input type="checkbox" checked={sel} onChange={() => toggleSelect(r.ad_id)} onClick={e => e.stopPropagation()} className="w-3.5 h-3.5" /></td>
                    <td className="py-2 px-2 text-xs text-gray-600 max-w-[160px] truncate" title={r.campaign_name || ''}>{r.campaign_name || '—'}</td>
                    <td className="py-2 px-2 text-xs text-gray-600 max-w-[160px] truncate" title={r.adset_name || ''}>{r.adset_name || '—'}</td>
                    <td className="py-2 px-2 text-xs font-medium text-gray-900 max-w-[200px] truncate" title={r.ad_name || ''}>{r.ad_name || '—'}</td>
                    <td className="py-2 px-2 text-xs text-gray-600">{accName(r.account_id)}</td>
                    <td className="py-2 px-2 text-right text-xs">{r.spend != null ? fmtNum(r.spend) : '—'}</td>
                    <td className="py-2 px-2 text-right text-xs font-semibold">{r.roas != null ? `${r.roas.toFixed(2)}x` : '—'}</td>
                    <td className="py-2 px-2 text-right text-xs">{r.conversions}</td>
                    <td className="py-2 px-2 text-right text-xs">{r.leads}</td>
                    <td className="py-2 px-2 text-right text-xs">{r.cost_per_lead != null ? fmtNum(r.cost_per_lead) : '—'}</td>
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
