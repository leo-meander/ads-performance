'use client'

import { useEffect, useState } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Account {
  id: string
  platform: string
  account_id: string
  account_name: string
  currency: string
  is_active: boolean
  created_at: string | null
}

const PLATFORM_LABELS: Record<string, { label: string; color: string; bg: string }> = {
  meta: { label: 'Meta', color: 'text-blue-700', bg: 'bg-blue-50' },
  google: { label: 'Google', color: 'text-green-700', bg: 'bg-green-50' },
  tiktok: { label: 'TikTok', color: 'text-pink-700', bg: 'bg-pink-50' },
}

const CURRENCIES = ['USD', 'VND', 'TWD', 'JPY', 'THB', 'SGD', 'EUR']

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [syncing, setSyncing] = useState<string | null>(null)
  const [syncResult, setSyncResult] = useState<string | null>(null)

  // Form state
  const [platform, setPlatform] = useState('meta')
  const [accountId, setAccountId] = useState('')
  const [accountName, setAccountName] = useState('')
  const [currency, setCurrency] = useState('USD')
  const [accessToken, setAccessToken] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  const loadAccounts = () => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setAccounts(data.data) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadAccounts() }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setFormError('')
    setSubmitting(true)

    try {
      const resp = await fetch(`${API_BASE}/api/accounts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          platform,
          account_id: accountId,
          account_name: accountName,
          currency,
          access_token: accessToken || null,
        }),
      })
      const data = await resp.json()
      if (data.success) {
        setShowForm(false)
        setAccountId('')
        setAccountName('')
        setAccessToken('')
        loadAccounts()
      } else {
        setFormError(data.error || 'Failed to create account')
      }
    } catch {
      setFormError('Network error')
    } finally {
      setSubmitting(false)
    }
  }

  const handleSync = async (accountId: string, accountPlatform: string) => {
    setSyncing(accountId)
    setSyncResult(null)
    try {
      let url = ''
      if (accountPlatform === 'meta') {
        url = `${API_BASE}/api/sync/manual`
      } else if (accountPlatform === 'google') {
        url = `${API_BASE}/api/google/sync?account_id=${accountId}`
      }
      if (!url) {
        setSyncResult(`Sync not available for ${accountPlatform}`)
        setSyncing(null)
        return
      }

      const resp = await fetch(url, { method: 'POST', credentials: 'include' })
      const data = await resp.json()
      if (data.success) {
        setSyncResult('Sync completed successfully!')
      } else {
        setSyncResult(`Sync error: ${data.error}`)
      }
    } catch {
      setSyncResult('Sync failed - network error')
    } finally {
      setSyncing(null)
    }
  }

  const platformHelp: Record<string, { idLabel: string; idPlaceholder: string; idHint: string; tokenLabel: string; tokenHint: string }> = {
    meta: {
      idLabel: 'Ad Account ID',
      idPlaceholder: 'act_123456789',
      idHint: 'Format: act_XXXXXXXXX (from Meta Business Suite)',
      tokenLabel: 'Access Token',
      tokenHint: 'Long-lived token from Meta Business settings',
    },
    google: {
      idLabel: 'Customer ID',
      idPlaceholder: '123-456-7890',
      idHint: 'Format: XXX-XXX-XXXX (from Google Ads dashboard)',
      tokenLabel: 'Refresh Token (optional)',
      tokenHint: 'Uses global credentials from .env if not provided',
    },
    tiktok: {
      idLabel: 'Advertiser ID',
      idPlaceholder: '7123456789',
      idHint: 'From TikTok Ads Manager',
      tokenLabel: 'Access Token',
      tokenHint: 'From TikTok Marketing API',
    },
  }

  const help = platformHelp[platform]
  const metaCount = accounts.filter(a => a.platform === 'meta').length
  const googleCount = accounts.filter(a => a.platform === 'google').length
  const tiktokCount = accounts.filter(a => a.platform === 'tiktok').length

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Ad Accounts</h1>
          <p className="text-sm text-gray-500 mt-1">
            {accounts.length} accounts connected
            {metaCount > 0 && ` · ${metaCount} Meta`}
            {googleCount > 0 && ` · ${googleCount} Google`}
            {tiktokCount > 0 && ` · ${tiktokCount} TikTok`}
          </p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
        >
          {showForm ? 'Cancel' : '+ Add Account'}
        </button>
      </div>

      {/* Sync result toast */}
      {syncResult && (
        <div className={`p-3 rounded-lg text-sm ${syncResult.includes('error') || syncResult.includes('failed') ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
          {syncResult}
          <button onClick={() => setSyncResult(null)} className="ml-3 underline text-xs">dismiss</button>
        </div>
      )}

      {/* Create Account Form */}
      {showForm && (
        <form onSubmit={handleSubmit} className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <h2 className="font-semibold text-gray-900">Add New Account</h2>

          {/* Platform Selection */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">Platform</label>
            <div className="flex gap-3">
              {(['meta', 'google', 'tiktok'] as const).map(p => {
                const info = PLATFORM_LABELS[p]
                return (
                  <button
                    key={p}
                    type="button"
                    onClick={() => setPlatform(p)}
                    className={`px-4 py-2 rounded-lg text-sm font-medium border transition-colors ${
                      platform === p
                        ? `${info.bg} ${info.color} border-current`
                        : 'bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100'
                    }`}
                  >
                    {info.label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Account ID */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">{help.idLabel}</label>
            <input
              type="text"
              value={accountId}
              onChange={e => setAccountId(e.target.value)}
              placeholder={help.idPlaceholder}
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <p className="text-xs text-gray-400 mt-1">{help.idHint}</p>
          </div>

          {/* Account Name */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Account Name</label>
            <input
              type="text"
              value={accountName}
              onChange={e => setAccountName(e.target.value)}
              placeholder="e.g. MEANDER Saigon"
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            {/* Currency */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Currency</label>
              <select
                value={currency}
                onChange={e => setCurrency(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                {CURRENCIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>

            {/* Access Token */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{help.tokenLabel}</label>
              <input
                type="password"
                value={accessToken}
                onChange={e => setAccessToken(e.target.value)}
                placeholder="Paste token here"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
              <p className="text-xs text-gray-400 mt-1">{help.tokenHint}</p>
            </div>
          </div>

          {/* Google-specific note */}
          {platform === 'google' && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs text-blue-700">
              <strong>Google Ads setup:</strong> Set these in your <code className="bg-blue-100 px-1 rounded">.env</code> file:
              <br />GOOGLE_DEVELOPER_TOKEN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, GOOGLE_LOGIN_CUSTOMER_ID
            </div>
          )}

          {formError && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">{formError}</div>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium disabled:opacity-50"
          >
            {submitting ? 'Creating...' : 'Create Account'}
          </button>
        </form>
      )}

      {/* Accounts List */}
      {loading ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400">Loading...</div>
      ) : accounts.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center">
          <p className="text-gray-500 text-lg">No accounts connected yet</p>
          <p className="text-sm text-gray-400 mt-2">Click "+ Add Account" to connect your first ad account</p>
        </div>
      ) : (
        <div className="space-y-3">
          {accounts.map(account => {
            const info = PLATFORM_LABELS[account.platform] || { label: account.platform, color: 'text-gray-700', bg: 'bg-gray-50' }
            return (
              <div key={account.id} className="bg-white rounded-xl border border-gray-200 p-5 flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${info.bg} ${info.color}`}>
                    {info.label}
                  </span>
                  <div>
                    <p className="font-medium text-gray-900">{account.account_name}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{account.account_id} · {account.currency}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => handleSync(account.id, account.platform)}
                    disabled={syncing === account.id}
                    className="px-3 py-1.5 text-xs font-medium bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50"
                  >
                    {syncing === account.id ? 'Syncing...' : 'Sync Now'}
                  </button>
                  <span className={`text-xs px-2 py-1 rounded-full ${
                    account.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                  }`}>
                    {account.is_active ? 'Active' : 'Inactive'}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
