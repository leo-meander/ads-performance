'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Campaign {
  id: string
  name: string
  objective: string | null
  daily_budget: number | null
  status: string
}

export default function LaunchPage() {
  const { id } = useParams()
  const router = useRouter()
  const [mode, setMode] = useState<'existing' | 'new'>('existing')
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [selectedCampaign, setSelectedCampaign] = useState('')
  const [country, setCountry] = useState('')
  const [ta, setTa] = useState('')
  const [language, setLanguage] = useState('')
  const [launching, setLaunching] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/api/launch/campaigns`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setCampaigns(data.data.items || []) })
      .catch(() => {})
  }, [])

  const handleLaunch = async () => {
    setLaunching(true)
    setError('')

    try {
      const endpoint = mode === 'existing' ? '/api/launch/existing' : '/api/launch/new-campaign'
      const body = mode === 'existing'
        ? { approval_id: id, campaign_id: selectedCampaign }
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
              </select>
            </div>
          </div>
        )}

        <button
          onClick={handleLaunch}
          disabled={launching || (mode === 'existing' && !selectedCampaign) || (mode === 'new' && (!country || !ta || !language))}
          className="mt-6 w-full bg-blue-600 text-white px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {launching ? 'Launching...' : 'Confirm Launch'}
        </button>
      </div>
    </div>
  )
}
