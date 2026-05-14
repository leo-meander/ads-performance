'use client'

import { useCallback, useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Campaign {
  id: string
  name: string
  objective: string | null
  daily_budget: number | null
  status: string
}

interface AdSetOption {
  id: string
  name: string
  platform_adset_id: string
  country: string | null
  daily_budget: number | null
  status: string
}

interface PreflightFix {
  target: 'account' | 'auto_config'
  target_id?: string
  field?: string
  account_name?: string
  country?: string
  ta?: string
  language?: string
  branch_id?: string | null
}

interface PreflightCheck {
  key: string
  label: string
  status: 'ok' | 'missing'
  detail: string
  fix: PreflightFix | null
}

interface Preflight {
  mode: 'existing' | 'new' | null
  ready: boolean
  checks: PreflightCheck[]
}

export default function LaunchPage() {
  const { id } = useParams()
  const router = useRouter()
  const [mode, setMode] = useState<'existing' | 'new'>('existing')
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [selectedCampaign, setSelectedCampaign] = useState('')
  const [adsets, setAdsets] = useState<AdSetOption[]>([])
  const [selectedAdset, setSelectedAdset] = useState('')
  const [adsetsLoading, setAdsetsLoading] = useState(false)
  const [country, setCountry] = useState('')
  const [ta, setTa] = useState('')
  const [language, setLanguage] = useState('')
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const [preflight, setPreflight] = useState<Preflight | null>(null)
  const [preflightLoading, setPreflightLoading] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/api/launch/campaigns`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setCampaigns(data.data.items || []) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    setSelectedAdset('')
    if (!selectedCampaign) { setAdsets([]); return }
    setAdsetsLoading(true)
    fetch(`${API_BASE}/api/launch/adsets?campaign_id=${selectedCampaign}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setAdsets(data.data.items || []) })
      .catch(() => {})
      .finally(() => setAdsetsLoading(false))
  }, [selectedCampaign])

  const loadPreflight = useCallback(() => {
    const params = new URLSearchParams()
    if (mode === 'existing') {
      if (!selectedCampaign) { setPreflight(null); return }
      params.set('campaign_id', selectedCampaign)
      if (selectedAdset) params.set('adset_id', selectedAdset)
    } else {
      if (!country || !ta || !language) { setPreflight(null); return }
      params.set('country', country)
      params.set('ta', ta)
      params.set('language', language)
    }
    setPreflightLoading(true)
    fetch(`${API_BASE}/api/launch/${id}/preflight?${params.toString()}`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setPreflight(data.data); else setPreflight(null) })
      .catch(() => setPreflight(null))
      .finally(() => setPreflightLoading(false))
  }, [id, mode, selectedCampaign, selectedAdset, country, ta, language])

  useEffect(() => { loadPreflight() }, [loadPreflight])

  const handleLaunch = async () => {
    setLaunching(true)
    setError('')

    try {
      const endpoint = mode === 'existing' ? '/api/launch/existing' : '/api/launch/new-campaign'
      const body = mode === 'existing'
        ? { approval_id: id, campaign_id: selectedCampaign, adset_id: selectedAdset || null }
        : { approval_id: id, country, ta, language }

      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(body),
      })
      const data = await res.json()
      if (data.success) {
        setSuccess(true)
      } else {
        setError(data.error || 'Launch failed')
      }
    } catch {
      setError('Network error')
    }
    setLaunching(false)
  }

  if (success) {
    return (
      <div className="max-w-xl mx-auto mt-8">
        <div className="bg-green-50 border border-green-200 rounded-xl p-6 text-center">
          <div className="text-3xl mb-2">&#x1F680;</div>
          <h2 className="text-lg font-bold text-green-800 mb-1">Launch Successful!</h2>
          <p className="text-sm text-green-600 mb-4">Your ad has been created on Meta Ads.</p>
          <button
            onClick={() => router.push(`/approvals/${id}`)}
            className="bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700"
          >
            Back to Approval
          </button>
        </div>
      </div>
    )
  }

  const missing = preflight?.checks.filter(c => c.status === 'missing') ?? []
  const launchDisabled =
    launching
    || !preflight?.ready
    || (mode === 'existing' && (!selectedCampaign || adsets.length === 0))
    || (mode === 'new' && (!country || !ta || !language))

  return (
    <div className="max-w-xl mx-auto">
      <button onClick={() => router.push(`/approvals/${id}`)} className="text-sm text-blue-600 hover:text-blue-700 mb-4">
        &larr; Back to Approval
      </button>

      <h1 className="text-2xl font-bold text-gray-900 mb-6">Launch to Meta Ads</h1>

      {error && (
        <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm mb-4">{error}</div>
      )}

      {/* Mode selector */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setMode('existing')}
          className={`flex-1 px-4 py-3 rounded-lg border text-sm font-medium ${
            mode === 'existing' ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-gray-200 text-gray-600'
          }`}
        >
          Add to Existing Campaign
        </button>
        <button
          onClick={() => setMode('new')}
          className={`flex-1 px-4 py-3 rounded-lg border text-sm font-medium ${
            mode === 'new' ? 'bg-blue-50 border-blue-300 text-blue-700' : 'bg-white border-gray-200 text-gray-600'
          }`}
        >
          Auto-Create New Campaign
        </button>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 p-6">
        {mode === 'existing' ? (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Select Campaign</label>
              <select
                value={selectedCampaign}
                onChange={e => setSelectedCampaign(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
              >
                <option value="">Choose a campaign...</option>
                {campaigns.map(c => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>

            {selectedCampaign && (
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Select Ad Set
                  <span className="text-xs font-normal text-gray-400 ml-2">
                    Meta requires the ad to live under an ad set
                  </span>
                </label>
                {adsetsLoading ? (
                  <p className="text-xs text-gray-400">Loading ad sets...</p>
                ) : adsets.length === 0 ? (
                  <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                    No active ad set under this campaign. Pick another campaign or use &quot;Auto-Create New Campaign&quot;.
                  </p>
                ) : (
                  <select
                    value={selectedAdset}
                    onChange={e => setSelectedAdset(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
                  >
                    <option value="">Auto-pick (most recent active)</option>
                    {adsets.map(a => (
                      <option key={a.id} value={a.id}>
                        {a.name}{a.country ? ` — ${a.country}` : ''}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Country</label>
              <select value={country} onChange={e => setCountry(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                <option value="">Select country</option>
                <option value="VN">Vietnam</option>
                <option value="TW">Taiwan</option>
                <option value="JP">Japan</option>
                <option value="AU">Australia</option>
                <option value="KR">Korea</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Target Audience</label>
              <select value={ta} onChange={e => setTa(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                <option value="">Select TA</option>
                <option value="Solo">Solo</option>
                <option value="Couple">Couple</option>
                <option value="Friend">Friend</option>
                <option value="Group">Group</option>
                <option value="Business">Business</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Language</label>
              <select value={language} onChange={e => setLanguage(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                <option value="">Select language</option>
                <option value="vi">Vietnamese</option>
                <option value="en">English</option>
                <option value="zh">Chinese</option>
                <option value="ja">Japanese</option>
                <option value="de">German</option>
              </select>
            </div>
          </div>
        )}

        {/* Preflight checklist */}
        {(preflightLoading || preflight) && (
          <div className="mt-6 border-t border-gray-100 pt-4">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-700">Publish readiness</h3>
              {preflightLoading && <span className="text-xs text-gray-400">Checking...</span>}
              {!preflightLoading && preflight?.ready && (
                <span className="text-xs font-medium text-green-600">All checks passed</span>
              )}
              {!preflightLoading && preflight && !preflight.ready && (
                <span className="text-xs font-medium text-amber-600">{missing.length} item(s) to fix</span>
              )}
            </div>
            <ul className="space-y-1.5">
              {preflight?.checks.map(check => (
                <li key={check.key} className="text-sm">
                  <div className="flex items-start gap-2">
                    <span className={check.status === 'ok' ? 'text-green-600' : 'text-amber-600'}>
                      {check.status === 'ok' ? '✓' : '!'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <span className={check.status === 'ok' ? 'text-gray-600' : 'text-gray-800 font-medium'}>
                        {check.label}
                      </span>
                      <span className="text-xs text-gray-400 ml-2">{check.detail}</span>
                      {check.status === 'missing' && check.fix && (
                        <FixWidget fix={check.fix} onFixed={loadPreflight} />
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        <button
          onClick={handleLaunch}
          disabled={launchDisabled}
          className="mt-6 w-full bg-blue-600 text-white px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {launching ? 'Launching...' : 'Confirm Launch'}
        </button>
        {!launching && preflight && !preflight.ready && (
          <p className="text-xs text-gray-400 text-center mt-2">
            Fix the items above to enable launch.
          </p>
        )}
      </div>
    </div>
  )
}

// ── Inline fix widgets ───────────────────────────────────────

function FixWidget({ fix, onFixed }: { fix: PreflightFix; onFixed: () => void }) {
  if (fix.target === 'account') return <AccountFieldFix fix={fix} onFixed={onFixed} />
  if (fix.target === 'auto_config') return <AutoConfigFix fix={fix} onFixed={onFixed} />
  return null
}

function AccountFieldFix({ fix, onFixed }: { fix: PreflightFix; onFixed: () => void }) {
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const save = async () => {
    if (!value.trim()) return
    setSaving(true)
    setErr('')
    try {
      const res = await fetch(`${API_BASE}/api/accounts/${fix.target_id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ [fix.field as string]: value.trim() }),
      })
      const data = await res.json()
      if (data.success) onFixed()
      else setErr(data.error || 'Save failed')
    } catch {
      setErr('Network error')
    }
    setSaving(false)
  }

  return (
    <div className="mt-1.5 flex flex-col gap-1">
      <div className="flex gap-2">
        <input
          value={value}
          onChange={e => setValue(e.target.value)}
          placeholder={fix.field === 'meta_page_id' ? 'Facebook Page ID' : 'https://...'}
          className="flex-1 px-2 py-1 border border-gray-200 rounded text-xs"
        />
        <button
          onClick={save}
          disabled={saving || !value.trim()}
          className="bg-gray-800 text-white px-3 py-1 rounded text-xs font-medium disabled:opacity-40"
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
      {err && <span className="text-xs text-red-600">{err}</span>}
    </div>
  )
}

function AutoConfigFix({ fix, onFixed }: { fix: PreflightFix; onFixed: () => void }) {
  const [template, setTemplate] = useState('Mason_{COUNTRY}_{FUNNEL} {TA}')
  const [objective, setObjective] = useState('CONVERSIONS')
  const [budget, setBudget] = useState('')
  const [funnel, setFunnel] = useState('TOF')
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const save = async () => {
    if (!fix.branch_id || !budget) {
      setErr(!fix.branch_id ? 'No branch on this combo' : 'Daily budget required')
      return
    }
    setSaving(true)
    setErr('')
    try {
      const res = await fetch(`${API_BASE}/api/launch/auto-config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          account_id: fix.branch_id,
          country: fix.country,
          ta: fix.ta,
          language: fix.language,
          campaign_name_template: template,
          default_objective: objective,
          default_daily_budget: parseFloat(budget),
          default_funnel_stage: funnel,
        }),
      })
      const data = await res.json()
      if (data.success) onFixed()
      else setErr(data.error || 'Create failed')
    } catch {
      setErr('Network error')
    }
    setSaving(false)
  }

  return (
    <div className="mt-1.5 flex flex-col gap-1.5 bg-gray-50 border border-gray-200 rounded p-2">
      <input
        value={template}
        onChange={e => setTemplate(e.target.value)}
        placeholder="Campaign name template"
        className="px-2 py-1 border border-gray-200 rounded text-xs"
      />
      <div className="flex gap-1.5">
        <select value={objective} onChange={e => setObjective(e.target.value)}
          className="flex-1 px-2 py-1 border border-gray-200 rounded text-xs">
          <option value="CONVERSIONS">Conversions</option>
          <option value="OUTCOME_TRAFFIC">Traffic</option>
          <option value="OUTCOME_AWARENESS">Awareness</option>
          <option value="OUTCOME_ENGAGEMENT">Engagement</option>
        </select>
        <select value={funnel} onChange={e => setFunnel(e.target.value)}
          className="px-2 py-1 border border-gray-200 rounded text-xs">
          <option value="TOF">TOF</option>
          <option value="MOF">MOF</option>
          <option value="BOF">BOF</option>
        </select>
        <input
          value={budget}
          onChange={e => setBudget(e.target.value)}
          placeholder="Daily budget"
          type="number"
          className="w-24 px-2 py-1 border border-gray-200 rounded text-xs"
        />
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={save}
          disabled={saving}
          className="bg-gray-800 text-white px-3 py-1 rounded text-xs font-medium disabled:opacity-40"
        >
          {saving ? 'Creating...' : 'Create auto-config'}
        </button>
        {err && <span className="text-xs text-red-600">{err}</span>}
      </div>
    </div>
  )
}
