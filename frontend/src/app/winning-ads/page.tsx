'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Sparkles, Trophy, LayoutList } from 'lucide-react'
import WinningMonthsTab from '@/components/WinningMonthsTab'
import WinningAdsListTab from '@/components/WinningAdsListTab'
import { useAuth } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Account { id: string; account_name: string; platform: string }

type Tab = 'months' | 'ads'

/**
 * The "winning creative" hub.
 *
 * Winning by Month leads because it's the designer KPI — frozen monthly awards
 * that don't drift when the benchmark moves. It used to live as a tab under
 * /creative, which left the two winning views split across separate pages.
 * The per-ad list (with AI Brief) is the second tab.
 */
export default function WinningAdsPage() {
  const { canEditSection } = useAuth()
  const [tab, setTab] = useState<Tab>('months')
  const [accounts, setAccounts] = useState<Account[]>([])

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) setAccounts(d.data.filter((a: Account) => a.platform === 'meta'))
      })
      .catch(() => {})
  }, [])

  return (
    <div className="p-6">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Winning Ads</h1>
          <p className="text-sm text-gray-500 mt-1">
            Monthly winners locked in for the design KPI, plus every winning creative to reuse.
          </p>
        </div>
        <Link
          href="/winning-ads/brief"
          className="inline-flex items-center gap-1.5 px-3 py-2 text-sm bg-purple-600 text-white rounded hover:bg-purple-700"
        >
          <Sparkles className="w-4 h-4" /> AI Brief
        </Link>
      </div>

      <div className="flex gap-1 border-b border-gray-200 mb-6 overflow-x-auto">
        {([
          { key: 'months', label: 'Winning by Month', icon: Trophy },
          { key: 'ads', label: 'All Winning Ads', icon: LayoutList },
        ] as const).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap ${tab === key ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
          >
            <Icon className="w-4 h-4" />{label}
          </button>
        ))}
      </div>

      {tab === 'months' && (
        <WinningMonthsTab accounts={accounts} canEdit={canEditSection('meta_ads')} />
      )}
      {tab === 'ads' && <WinningAdsListTab accounts={accounts} />}
    </div>
  )
}
