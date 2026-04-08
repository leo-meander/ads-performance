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
}

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`)
      .then((res) => res.json())
      .then((data) => {
        if (data.success) setAccounts(data.data)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Ad Accounts</h1>

      <div className="bg-white rounded-xl border border-gray-200 p-6">
        {loading ? (
          <p className="text-gray-500">Loading accounts...</p>
        ) : accounts.length === 0 ? (
          <div>
            <p className="text-gray-500">No accounts connected yet.</p>
            <p className="text-sm text-gray-400 mt-2">
              Use the API to connect your Meta Ads accounts for each branch.
            </p>
            <pre className="mt-4 bg-gray-50 p-4 rounded-lg text-xs text-gray-600 overflow-x-auto">
{`POST ${API_BASE}/api/accounts
{
  "platform": "meta",
  "account_id": "YOUR_AD_ACCOUNT_ID",
  "account_name": "MEANDER Saigon",
  "currency": "VND",
  "access_token": "YOUR_ACCESS_TOKEN"
}`}
            </pre>
          </div>
        ) : (
          <div className="space-y-3">
            {accounts.map((account) => (
              <div
                key={account.id}
                className="flex items-center justify-between p-4 border border-gray-100 rounded-lg"
              >
                <div>
                  <p className="font-medium text-gray-900">{account.account_name}</p>
                  <p className="text-sm text-gray-500">
                    {account.platform.toUpperCase()} - {account.account_id} - {account.currency}
                  </p>
                </div>
                <span className={`text-xs px-2 py-1 rounded-full ${
                  account.is_active
                    ? 'bg-green-100 text-green-700'
                    : 'bg-gray-100 text-gray-500'
                }`}>
                  {account.is_active ? 'Active' : 'Inactive'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
