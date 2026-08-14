'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Sparkles, Trophy, LayoutList, Globe } from 'lucide-react'
import WinningMonthsTab from '@/components/WinningMonthsTab'
import WinningAdsListTab from '@/components/WinningAdsListTab'
import { useAuth } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Account { id: string; account_name: string; platform: string }

type Tab = 'months' | 'all-months' | 'ads'

/**
 * The "winning creative" hub.
 *
 * Winning by Month leads because it's the designer KPI — frozen monthly awards
 * that don't drift when the benchmark moves. It used to live as a tab under
 * /creative, which left the two winning views split across separate pages.
 * The per-ad list (with AI Brief) is the last tab.
 *
 * "Ads Winning (All)" is the same monthly view over an unfiltered universe —
 * every ad, KOL-named ones and Bread included, judged against each branch's
 * full blended benchmark. It is Mason's own tracking view and deliberately NOT
 * the KPI: the backend freezes the two verdict sets independently
 * (winning_ad_months.scope), so an ad can be WIN in one tab and LOSE in the
 * other. It sits second so the KPI stays the first thing read.
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
          // The exclusion is in the label, not just the tooltip: side by side
          // with "Ads Winning (All)" the two tabs otherwise look like the same
          // report, and the whole reason their numbers differ is this scope.
          { key: 'months', label: 'Winning by Month (Exclude KOL)', icon: Trophy, hint: 'The design KPI — KOL-named ads and Bread excluded.' },
          { key: 'all-months', label: 'Ads Winning (All)', icon: Globe, hint: 'Same rules over every ad, no exclusions — KOL ads and Bread included. Tracking view, not the KPI.' },
          { key: 'ads', label: 'All Winning Ads', icon: LayoutList, hint: 'Every winning creative, with AI Brief.' },
        ] as const).map(({ key, label, icon: Icon, hint }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            title={hint}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap ${tab === key ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'}`}
          >
            <Icon className="w-4 h-4" />{label}
          </button>
        ))}
      </div>

      {/* `key` forces a remount when switching between the two scopes —
          without it React reuses the instance and the previous scope's months
          stay on screen (with its selected month) until the new fetch lands. */}
      {tab === 'months' && (
        <WinningMonthsTab key="kpi" accounts={accounts} canEdit={canEditSection('meta_ads')} />
      )}
      {tab === 'all-months' && (
        <WinningMonthsTab key="all" scope="all" accounts={accounts} canEdit={canEditSection('meta_ads')} />
      )}
      {tab === 'ads' && <WinningAdsListTab accounts={accounts} />}
    </div>
  )
}
