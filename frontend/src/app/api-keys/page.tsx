'use client'

import { useEffect, useState } from 'react'
import { useAuth } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface ApiKeyItem {
  id: string
  name: string
  key_prefix: string
  is_active: boolean
  last_used_at: string | null
  daily_request_count: number
  created_by: string | null
  created_at: string | null
}

interface CreatedKey {
  id: string
  name: string
  key: string
  key_prefix: string
  created_at: string | null
}

const ENDPOINTS = [
  { path: '/api/export/accounts', desc: 'Ad accounts (branches)' },
  { path: '/api/export/angles', desc: 'Ad angles (global)' },
  { path: '/api/export/keypoints', desc: 'Branch keypoints' },
  { path: '/api/export/copies', desc: 'Ad copies' },
  { path: '/api/export/materials', desc: 'Ad materials' },
  { path: '/api/export/combos', desc: 'Ad combos with metrics' },
  { path: '/api/export/campaigns', desc: 'Campaigns (all platforms)' },
  { path: '/api/export/ads', desc: 'Ads' },
  { path: '/api/export/countries', desc: 'Per-country × date metrics' },
  { path: '/api/export/spy-ads', desc: 'Spy Ads library' },
  { path: '/api/export/budget/monthly', desc: 'Monthly budget' },
  { path: '/api/export/spend/daily', desc: 'Daily spend' },
  { path: '/api/export/booking-matches', desc: 'Booking from Ads rows' },
  { path: '/api/export/booking-matches/summary', desc: 'Booking KPI roll-up' },
]

export default function ApiKeysPage() {
  const { user } = useAuth()
  const [keys, setKeys] = useState<ApiKeyItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [newlyCreated, setNewlyCreated] = useState<CreatedKey | null>(null)
  const [copied, setCopied] = useState(false)

  const isAdmin = user?.is_admin || user?.roles?.includes('admin')

  const loadKeys = () => {
    fetch(`${API_BASE}/api/export/keys`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => {
        if (data.success) setKeys(data.data || [])
        else setError(data.error || 'Failed to load keys')
      })
      .catch(() => setError('Network error'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (isAdmin) loadKeys()
    else setLoading(false)
  }, [isAdmin])

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setCreating(true)
    try {
      const res = await fetch(`${API_BASE}/api/export/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name }),
      })
      const data = await res.json()
      if (data.success) {
        setNewlyCreated(data.data)
        setShowForm(false)
        setName('')
        loadKeys()
      } else {
        setError(data.error || 'Failed to create key')
      }
    } catch {
      setError('Network error')
    } finally {
      setCreating(false)
    }
  }

  const handleDeactivate = async (id: string, keyName: string) => {
    if (!confirm(`Deactivate "${keyName}"? External systems using this key will stop working immediately.`)) return
    try {
      const res = await fetch(`${API_BASE}/api/export/keys/${id}`, {
        method: 'DELETE',
        credentials: 'include',
      })
      const data = await res.json()
      if (data.success) loadKeys()
      else alert(`Error: ${data.error}`)
    } catch {
      alert('Network error')
    }
  }

  const copyKey = () => {
    if (!newlyCreated) return
    navigator.clipboard.writeText(newlyCreated.key)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (!isAdmin) {
    return (
      <div className="p-8">
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
          <p className="text-red-700 font-medium">Admin only</p>
          <p className="text-sm text-red-500 mt-1">You need admin role to manage API keys.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Export API Keys</h1>
          <p className="text-sm text-gray-500 mt-1">
            Issue keys for external systems to pull data via <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">X-API-Key</code> header.
            {keys.length > 0 && ` · ${keys.filter(k => k.is_active).length} active · ${keys.length} total`}
          </p>
        </div>
        <button
          onClick={() => { setShowForm(!showForm); setNewlyCreated(null) }}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium"
        >
          {showForm ? 'Cancel' : '+ New API Key'}
        </button>
      </div>

      {/* Newly created key — shown once */}
      {newlyCreated && (
        <div className="bg-amber-50 border border-amber-300 rounded-xl p-5 space-y-3">
          <div className="flex items-start gap-3">
            <div className="text-amber-600 text-xl">⚠</div>
            <div className="flex-1">
              <h3 className="font-semibold text-amber-900">Copy this key NOW — it will not be shown again</h3>
              <p className="text-xs text-amber-700 mt-1">
                Name: <span className="font-mono">{newlyCreated.name}</span>
              </p>
            </div>
            <button
              onClick={() => setNewlyCreated(null)}
              className="text-amber-600 hover:text-amber-900 text-sm"
            >
              Dismiss
            </button>
          </div>
          <div className="flex items-center gap-2 bg-white border border-amber-200 rounded-lg p-3">
            <code className="flex-1 font-mono text-sm text-gray-800 break-all">{newlyCreated.key}</code>
            <button
              onClick={copyKey}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                copied ? 'bg-green-600 text-white' : 'bg-gray-900 text-white hover:bg-gray-700'
              }`}
            >
              {copied ? '✓ Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}

      {/* Create form */}
      {showForm && (
        <form onSubmit={handleCreate} className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
          <h2 className="font-semibold text-gray-900">New API Key</h2>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name / Purpose</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. BI Dashboard, Looker Studio, Zapier"
              required
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
            <p className="text-xs text-gray-400 mt-1">
              Descriptive name so you can identify which external system uses this key.
            </p>
          </div>
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={creating || !name}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium disabled:opacity-50"
          >
            {creating ? 'Creating…' : 'Generate Key'}
          </button>
        </form>
      )}

      {/* Keys list */}
      {loading ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center text-gray-400">Loading…</div>
      ) : keys.length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-10 text-center">
          <p className="text-gray-500 text-lg">No API keys yet</p>
          <p className="text-sm text-gray-400 mt-2">Click "+ New API Key" to issue one.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Name</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Prefix</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Last Used</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Today</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Created</th>
                <th className="text-left text-xs font-semibold text-gray-500 uppercase tracking-wider px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {keys.map(k => (
                <tr key={k.id} className={!k.is_active ? 'opacity-50' : ''}>
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{k.name}</td>
                  <td className="px-4 py-3 text-xs font-mono text-gray-500">{k.key_prefix}…</td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {k.last_used_at ? new Date(k.last_used_at).toLocaleString() : 'never'}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{k.daily_request_count} req</td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {k.created_at ? new Date(k.created_at).toLocaleDateString() : '—'}
                    {k.created_by && <div className="text-[10px] text-gray-400">by {k.created_by}</div>}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      k.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                    }`}>
                      {k.is_active ? 'Active' : 'Revoked'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {k.is_active && (
                      <button
                        onClick={() => handleDeactivate(k.id, k.name)}
                        className="text-xs text-red-600 hover:text-red-800 font-medium"
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Endpoint reference */}
      <div className="bg-gray-50 border border-gray-200 rounded-xl p-6">
        <h2 className="font-semibold text-gray-900 mb-3">Available Export Endpoints</h2>
        <p className="text-xs text-gray-500 mb-4">
          Send requests with header <code className="bg-white px-1.5 py-0.5 rounded border text-xs">X-API-Key: &lt;your key&gt;</code>
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {ENDPOINTS.map(ep => (
            <div key={ep.path} className="flex items-start gap-2 text-sm">
              <code className="bg-white border border-gray-200 rounded px-1.5 py-0.5 text-xs text-gray-700 font-mono whitespace-nowrap">
                GET {ep.path}
              </code>
              <span className="text-xs text-gray-500 mt-0.5">{ep.desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
