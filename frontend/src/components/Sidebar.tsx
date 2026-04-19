'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useAuth } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type NavItem = {
  href: string
  label: string
  section: string
  badge?: boolean
  adminOnly?: boolean
}

type NavSection = {
  label: string
  items: NavItem[]
}

const navSections: NavSection[] = [
  {
    label: 'Analytics',
    items: [
      { href: '/', label: 'Dashboard', section: 'analytics' },
      { href: '/country', label: 'Country Dashboard', section: 'analytics' },
      { href: '/booking-matches', label: 'Booking from Ads', section: 'analytics' },
    ],
  },
  {
    label: 'Meta Ads',
    items: [
      { href: '/meta/recommendations', label: 'Recommendations', section: 'meta_ads' },
      { href: '/angles', label: 'Ad Angles', section: 'meta_ads' },
      { href: '/creative', label: 'Creative Library', section: 'meta_ads' },
      { href: '/approvals', label: 'Approvals', section: 'meta_ads', badge: true },
      { href: '/keypoints', label: 'Keypoints', section: 'meta_ads' },
      { href: '/ad-research', label: 'Spy Ads', section: 'meta_ads' },
    ],
  },
  {
    label: 'Google Ads',
    items: [
      { href: '/google/pmax', label: 'PMax Campaigns', section: 'google_ads' },
      { href: '/google/search', label: 'Search Campaigns', section: 'google_ads' },
      { href: '/google/recommendations', label: 'Recommendations', section: 'google_ads' },
    ],
  },
  {
    label: 'Budget',
    items: [{ href: '/budget', label: 'Budget Planner', section: 'budget' }],
  },
  {
    label: 'Automation',
    items: [
      { href: '/rules', label: 'Rules', section: 'automation' },
      { href: '/logs', label: 'Action Logs', section: 'automation' },
    ],
  },
  {
    label: 'AI',
    items: [
      { href: '/insights', label: 'AI Insights', section: 'ai' },
      { href: '/transcriptions', label: 'Video Transcriptions', section: 'ai' },
    ],
  },
  {
    label: 'Settings',
    items: [
      { href: '/accounts', label: 'Accounts', section: 'settings' },
      { href: '/users', label: 'Users', section: 'settings', adminOnly: true },
    ],
  },
]

export default function Sidebar() {
  const pathname = usePathname()
  const { user, canAccessSection } = useAuth()
  const [unreadCount, setUnreadCount] = useState(0)

  const isAdmin = !!user && (user.is_admin || (user.roles || []).includes('admin'))

  useEffect(() => {
    if (!user) return
    fetch(`${API_BASE}/api/notifications?limit=1`, { credentials: 'include' })
      .then((r) => r.json())
      .then((data) => { if (data.success) setUnreadCount(data.data.unread_count) })
      .catch(() => {})

    const interval = setInterval(() => {
      fetch(`${API_BASE}/api/notifications?limit=1`, { credentials: 'include' })
        .then((r) => r.json())
        .then((data) => { if (data.success) setUnreadCount(data.data.unread_count) })
        .catch(() => {})
    }, 30000)
    return () => clearInterval(interval)
  }, [user])

  const isItemVisible = (item: NavItem): boolean => {
    if (item.adminOnly && !isAdmin) return false
    return canAccessSection(item.section)
  }

  return (
    <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
      <div className="p-6 border-b border-gray-200">
        <h1 className="text-lg font-bold text-gray-900">Ads Platform</h1>
        <p className="text-xs text-gray-500 mt-1">MEANDER Group</p>
      </div>
      <nav className="flex-1 p-4 space-y-4 overflow-auto">
        {navSections.map((section) => {
          const visibleItems = section.items.filter(isItemVisible)
          if (visibleItems.length === 0) return null
          return (
            <div key={section.label}>
              <p className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold px-3 mb-1">
                {section.label}
              </p>
              <div className="space-y-0.5">
                {visibleItems.map((item) => {
                  const isActive =
                    pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href))
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`flex items-center justify-between px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                        isActive
                          ? 'bg-blue-50 text-blue-700'
                          : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                      }`}
                    >
                      {item.label}
                      {item.badge && unreadCount > 0 && (
                        <span className="bg-red-500 text-white text-[10px] font-bold rounded-full px-1.5 py-0.5 leading-none">
                          {unreadCount > 9 ? '9+' : unreadCount}
                        </span>
                      )}
                    </Link>
                  )
                })}
              </div>
            </div>
          )
        })}
      </nav>
      <div className="p-4 border-t border-gray-200">
        <p className="text-xs text-gray-400">Phase 7 - Google Ads</p>
      </div>
    </aside>
  )
}
