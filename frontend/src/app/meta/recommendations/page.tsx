'use client'

import { useEffect, useMemo, useState } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type Severity = 'critical' | 'warning' | 'info'
type Status = 'pending' | 'applied' | 'dismissed' | 'expired' | 'superseded' | 'failed'
type EntityLevel = 'account' | 'campaign' | 'ad_set' | 'ad'

interface Account {
  id: string
  platform: string
  account_name: string
  currency: string
}

interface Recommendation {
  id: string
  rec_type: string
  severity: Severity
  status: Status
  account_id: string
  campaign_id: string | null
  ad_set_id: string | null
  ad_id: string | null
  entity_level: EntityLevel
  funnel_stage: string | null
  targeted_country: string | null
  title: string
  detector_finding: Record<string, any>
  metrics_snapshot: Record<string, any>
  ai_reasoning: string | null
  ai_confidence: number | null
  suggested_action: { function: string | null; kwargs: Record<string, any> }
  auto_applicable: boolean
  warning_text: string
  sop_reference: string | null
  expires_at: string | null
  applied_at: string | null
  dismissed_at: string | null
  dismiss_reason: string | null
  created_at: string
}

const SEVERITY_BADGE: Record<Severity, string> = {
  critical: 'bg-red-100 text-red-700 border-red-200',
  warning: 'bg-amber-100 text-amber-800 border-amber-200',
  info: 'bg-blue-100 text-blue-700 border-blue-200',
}
const STATUS_BADGE: Record<Status, string> = {
  pending: 'bg-gray-100 text-gray-700',
  applied: 'bg-green-100 text-green-700',
  dismissed: 'bg-gray-200 text-gray-500',
  expired: 'bg-gray-200 text-gray-500',
  superseded: 'bg-gray-200 text-gray-500',
  failed: 'bg-red-100 text-red-700',
}

export default function MetaRecommendationsPage() {
  const [items, setItems] = useState<Recommendation[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [accounts, setAccounts] = useState<Account[]>([])
  const [accountFilter, setAccountFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<Status | 'all'>('pending')
  const [severityFilter, setSeverityFilter] = useState<Severity | 'all'>('all')
  const [entityLevelFilter, setEntityLevelFilter] = useState<EntityLevel | 'all'>('all')
  const [funnelFilter, setFunnelFilter] = useState<string>('all')

  const [selected, setSelected] = useState<Recommendation | null>(null)
  const [applyBusy, setApplyBusy] = useState(false)
  const [dismissBusy, setDismissBusy] = useState(false)
  const [confirmWarning, setConfirmWarning] = useState(false)
  const [dismissReason, setDismissReason] = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(res => {
        if (res.success) {
          const metaOnly = (res.data || []).filter((a: Account) => a.platform === 'meta')
          setAccounts(metaOnly)
        }
      })
      .catch(() => {})
  }, [])

  const fetchList = () => {
    setLoading(true)
    const params = new URLSearchParams()
    if (statusFilter !== 'all') params.set('status', statusFilter)
    if (severityFilter !== 'all') params.set('severity', severityFilter)
    if (entityLevelFilter !== 'all') params.set('entity_level', entityLevelFilter)
    if (funnelFilter !== 'all') params.set('funnel_stage', funnelFilter)
    if (accountFilter !== 'all') params.set('account_id', accountFilter)
    params.set('limit', '100')
    fetch(`${API_BASE}/api/meta/recommendations?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(res => {
        if (res.success) {
          setItems(res.data.items || [])
          setTotal(res.data.total || 0)
          setError(null)
        } else {
          setError(res.error || 'Failed to load recommendations')
        }
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchList()
  }, [statusFilter, severityFilter, entityLevelFilter, funnelFilter, accountFilter])

  const onOpen = (rec: Recommendation) => {
    setSelected(rec)
    setConfirmWarning(false)
    setDismissReason('')
  }
  const onClose = () => {
    setSelected(null)
    setConfirmWarning(false)
    setDismissReason('')
  }

  const onApply = async () => {
    if (!selected || !confirmWarning) return
    setApplyBusy(true)
    try {
      const r = await fetch(
        `${API_BASE}/api/meta/recommendations/${selected.id}/apply`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ confirm_warning: true }),
        },
      )
      const res = await r.json()
      if (!r.ok || res.success === false) {
        alert(res.detail || res.error || `Apply failed (HTTP ${r.status})`)
        return
      }
      onClose()
      fetchList()
    } finally {
      setApplyBusy(false)
    }
  }

  const onDismiss = async () => {
    if (!selected) return
    if (!dismissReason.trim()) {
      alert('Please provide a dismiss reason.')
      return
    }
    setDismissBusy(true)
    try {
      const r = await fetch(
        `${API_BASE}/api/meta/recommendations/${selected.id}/dismiss`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: dismissReason.trim() }),
        },
      )
      const res = await r.json()
      if (!r.ok || res.success === false) {
        alert(res.detail || res.error || `Dismiss failed (HTTP ${r.status})`)
        return
      }
      onClose()
      fetchList()
    } finally {
      setDismissBusy(false)
    }
  }

  const onRunNow = async () => {
    setLoading(true)
    try {
      for (const cadence of ['daily', 'weekly', 'monthly', 'seasonality']) {
        await fetch(`${API_BASE}/api/meta/recommendations/run`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cadence }),
        })
      }
      fetchList()
    } finally {
      setLoading(false)
    }
  }

  const counts = useMemo(() => {
    const c: Record<Severity, number> = { critical: 0, warning: 0, info: 0 }
    items.forEach(it => { if (it.status === 'pending') c[it.severity]++ })
    return c
  }, [items])

  const accountNameById = useMemo(() => {
    const m: Record<string, string> = {}
    accounts.forEach(a => { m[a.id] = a.account_name })
    return m
  }, [accounts])

  return (
    <div className="p-8">
      <header className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Meta Ads Recommendations</h1>
          <p className="text-sm text-gray-500 mt-1">
            Playbook-driven optimization suggestions per branch (Saigon, Taipei, 1948, Osaka, Oani, Bread).
          </p>
        </div>
        <button
          onClick={onRunNow}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
          title="Run all cadences now (admin only)"
        >
          Run now
        </button>
      </header>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-white border border-red-200 rounded-lg p-4">
          <div className="text-xs uppercase tracking-wider text-red-600 font-semibold">Critical</div>
          <div className="text-3xl font-bold text-red-700 mt-2">{counts.critical}</div>
        </div>
        <div className="bg-white border border-amber-200 rounded-lg p-4">
          <div className="text-xs uppercase tracking-wider text-amber-600 font-semibold">Warning</div>
          <div className="text-3xl font-bold text-amber-700 mt-2">{counts.warning}</div>
        </div>
        <div className="bg-white border border-blue-200 rounded-lg p-4">
          <div className="text-xs uppercase tracking-wider text-blue-600 font-semibold">Info</div>
          <div className="text-3xl font-bold text-blue-700 mt-2">{counts.info}</div>
        </div>
      </div>

      <div className="flex gap-3 mb-4 flex-wrap">
        <Select label="Branch" value={accountFilter} onChange={setAccountFilter} options={[
          ['all', 'All branches'],
          ...accounts.map(a => [a.id, a.account_name] as [string, string]),
        ]} />
        <Select label="Status" value={statusFilter} onChange={v => setStatusFilter(v as any)} options={[
          ['all', 'All'], ['pending', 'Pending'], ['applied', 'Applied'],
          ['dismissed', 'Dismissed'], ['expired', 'Expired'], ['superseded', 'Superseded'],
          ['failed', 'Failed'],
        ]} />
        <Select label="Severity" value={severityFilter} onChange={v => setSeverityFilter(v as any)} options={[
          ['all', 'All'], ['critical', 'Critical'], ['warning', 'Warning'], ['info', 'Info'],
        ]} />
        <Select label="Entity" value={entityLevelFilter} onChange={v => setEntityLevelFilter(v as any)} options={[
          ['all', 'All'], ['account', 'Branch'], ['campaign', 'Campaign'],
          ['ad_set', 'Ad Set'], ['ad', 'Ad'],
        ]} />
        <Select label="Funnel" value={funnelFilter} onChange={setFunnelFilter} options={[
          ['all', 'All'], ['TOF', 'TOF'], ['MOF', 'MOF'], ['BOF', 'BOF'],
        ]} />
        <div className="ml-auto text-sm text-gray-500 self-end">
          {loading ? 'Loading…' : `${items.length} of ${total}`}
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg mb-4">
          {error}
        </div>
      )}

      <div className="space-y-3" data-testid="rec-list">
        {items.length === 0 && !loading && (
          <div className="bg-white border border-gray-200 rounded-lg p-8 text-center text-gray-500">
            No recommendations match these filters.
          </div>
        )}
        {items.map(rec => (
          <RecommendationCard
            key={rec.id}
            rec={rec}
            branchName={accountNameById[rec.account_id]}
            onOpen={() => onOpen(rec)}
          />
        ))}
      </div>

      {selected && (
        <Modal onClose={onClose} title={selected.title}>
          <div className="space-y-5">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`px-2 py-0.5 text-xs font-semibold rounded border ${SEVERITY_BADGE[selected.severity]}`}>
                {selected.severity.toUpperCase()}
              </span>
              <span className={`px-2 py-0.5 text-xs font-semibold rounded ${STATUS_BADGE[selected.status]}`}>
                {selected.status}
              </span>
              <span className="px-2 py-0.5 text-xs font-mono rounded bg-gray-100 text-gray-600">
                {selected.rec_type}
              </span>
              {selected.entity_level && (
                <span className="px-2 py-0.5 text-xs rounded bg-gray-100 text-gray-600">
                  {selected.entity_level}
                </span>
              )}
              {selected.funnel_stage && (
                <span className="px-2 py-0.5 text-xs rounded bg-purple-100 text-purple-700">
                  {selected.funnel_stage}
                </span>
              )}
              {selected.targeted_country && (
                <span className="px-2 py-0.5 text-xs rounded bg-sky-100 text-sky-700">
                  Target: {selected.targeted_country}
                </span>
              )}
              {selected.sop_reference && (
                <span className="px-2 py-0.5 text-xs font-mono rounded bg-gray-100 text-gray-500">
                  {selected.sop_reference}
                </span>
              )}
            </div>

            {accountNameById[selected.account_id] && (
              <div className="text-xs text-gray-500">
                Branch: <span className="text-gray-800 font-semibold">{accountNameById[selected.account_id]}</span>
              </div>
            )}

            {selected.ai_reasoning && (
              <section>
                <h4 className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-1">Playbook Analysis</h4>
                <p className="text-sm text-gray-800 whitespace-pre-wrap">{selected.ai_reasoning}</p>
              </section>
            )}

            <section>
              <h4 className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2">Evidence</h4>
              <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-auto max-h-48">
                {JSON.stringify(selected.detector_finding, null, 2)}
              </pre>
            </section>

            <section>
              <h4 className="text-xs uppercase tracking-wider text-gray-500 font-semibold mb-2">Metrics Snapshot</h4>
              <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-auto max-h-36">
                {JSON.stringify(selected.metrics_snapshot, null, 2)}
              </pre>
            </section>

            <section className="bg-amber-50 border border-amber-200 rounded p-4">
              <h4 className="text-xs uppercase tracking-wider text-amber-800 font-semibold mb-2">Warning — Read before applying</h4>
              <p className="text-sm text-amber-900">{selected.warning_text}</p>
              {selected.auto_applicable && selected.status === 'pending' && (
                <label className="flex items-start gap-2 mt-3 text-sm text-amber-900 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={confirmWarning}
                    onChange={e => setConfirmWarning(e.target.checked)}
                    className="mt-1"
                  />
                  I have read the warning and confirm this action.
                </label>
              )}
            </section>

            {selected.status === 'pending' && (
              <section className="flex flex-col gap-3">
                {selected.auto_applicable ? (
                  <button
                    onClick={onApply}
                    disabled={!confirmWarning || applyBusy}
                    className="w-full px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 disabled:opacity-40"
                  >
                    {applyBusy ? 'Applying…' : 'Apply via Meta Ads API'}
                  </button>
                ) : (
                  <div className="text-sm text-gray-600 bg-gray-50 border border-gray-200 rounded p-3">
                    This recommendation is guidance only. Follow the warning text manually in Meta Ads Manager.
                  </div>
                )}

                <div className="border-t border-gray-200 pt-3">
                  <label className="block text-xs uppercase tracking-wider text-gray-500 font-semibold mb-1">
                    Or dismiss with a reason
                  </label>
                  <textarea
                    value={dismissReason}
                    onChange={e => setDismissReason(e.target.value)}
                    placeholder="e.g. handled manually, false positive, not applicable to this campaign"
                    className="w-full text-sm border border-gray-300 rounded p-2 resize-none"
                    rows={2}
                  />
                  <button
                    onClick={onDismiss}
                    disabled={dismissBusy || !dismissReason.trim()}
                    className="mt-2 px-4 py-1.5 bg-white text-gray-700 text-sm font-medium rounded border border-gray-300 hover:bg-gray-50 disabled:opacity-40"
                  >
                    {dismissBusy ? 'Dismissing…' : 'Dismiss'}
                  </button>
                </div>
              </section>
            )}
          </div>
        </Modal>
      )}
    </div>
  )
}


function Select({
  label, value, onChange, options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: [string, string][]
}) {
  return (
    <div>
      <label className="block text-[10px] uppercase tracking-wider text-gray-400 font-semibold mb-1">
        {label}
      </label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="text-sm border border-gray-300 rounded px-2 py-1.5 bg-white"
      >
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </div>
  )
}


function RecommendationCard({
  rec, branchName, onOpen,
}: {
  rec: Recommendation
  branchName: string | undefined
  onOpen: () => void
}) {
  const spend_7d = Number(rec.metrics_snapshot?.spend_7d || 0)
  const conversions_7d = Number(rec.metrics_snapshot?.conversions_7d || 0)
  const roas_7d = Number(rec.metrics_snapshot?.roas_7d || 0)
  const freq = Number(rec.metrics_snapshot?.frequency_7d_avg || 0)
  return (
    <button
      onClick={onOpen}
      className="w-full text-left bg-white border border-gray-200 rounded-lg p-4 hover:border-gray-400 hover:shadow-sm transition"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`px-2 py-0.5 text-[10px] font-bold rounded border ${SEVERITY_BADGE[rec.severity]}`}>
              {rec.severity.toUpperCase()}
            </span>
            <span className="text-[10px] font-mono text-gray-400">{rec.rec_type}</span>
            {rec.entity_level && (
              <span className="text-[10px] font-mono text-gray-400">· {rec.entity_level}</span>
            )}
            {rec.funnel_stage && (
              <span className="text-[10px] font-semibold text-purple-700 bg-purple-50 px-1.5 py-0.5 rounded">
                {rec.funnel_stage}
              </span>
            )}
            {rec.targeted_country && (
              <span className="text-[10px] font-semibold text-sky-700 bg-sky-50 px-1.5 py-0.5 rounded">
                {rec.targeted_country}
              </span>
            )}
            {rec.auto_applicable && (
              <span className="text-[10px] font-semibold text-green-700 bg-green-50 px-1.5 py-0.5 rounded">
                AUTO-APPLY
              </span>
            )}
          </div>
          <h3 className="text-sm font-semibold text-gray-900">{rec.title}</h3>
          {branchName && (
            <div className="text-[11px] text-gray-500 mt-0.5">{branchName}</div>
          )}
          {rec.ai_reasoning && (
            <p className="text-xs text-gray-600 mt-1 line-clamp-2">{rec.ai_reasoning}</p>
          )}
        </div>
        <div className="text-right text-xs text-gray-500 whitespace-nowrap">
          <div>7d spend: <span className="font-semibold text-gray-800">{spend_7d.toLocaleString()}</span></div>
          <div>7d conv: <span className="font-semibold text-gray-800">{conversions_7d}</span></div>
          <div>7d ROAS: <span className="font-semibold text-gray-800">{roas_7d.toFixed(2)}</span></div>
          {freq > 0 && (
            <div>Freq: <span className="font-semibold text-gray-800">{freq.toFixed(2)}</span></div>
          )}
        </div>
      </div>
    </button>
  )
}


function Modal({
  onClose, title, children,
}: {
  onClose: () => void
  title: string
  children: React.ReactNode
}) {
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-start justify-center p-8 overflow-auto" onClick={onClose}>
      <div
        className="bg-white rounded-xl shadow-xl max-w-2xl w-full p-6"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-4">
          <h2 className="text-lg font-bold text-gray-900 pr-8">{title}</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-2xl leading-none"
            aria-label="Close"
          >×</button>
        </div>
        {children}
      </div>
    </div>
  )
}
