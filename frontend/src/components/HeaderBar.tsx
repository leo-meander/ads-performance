'use client'

import { useState } from 'react'
import { useAuth } from '@/components/AuthContext'
import NotificationBell from '@/components/NotificationBell'
import ActivityLogDrawer from '@/components/ActivityLogDrawer'
import { useRouter } from 'next/navigation'
import { Clock } from 'lucide-react'

export default function HeaderBar() {
  const { user, logout } = useAuth()
  const router = useRouter()
  const [drawerOpen, setDrawerOpen] = useState(false)

  if (!user) return null

  return (
    <>
      <header className="h-12 bg-white border-b border-gray-200 px-6 flex items-center justify-end gap-3 shrink-0">
        <button
          onClick={() => setDrawerOpen(true)}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-indigo-600 border border-gray-200 hover:border-indigo-300 rounded-full px-2.5 py-1 transition-colors"
          title="Activity Log"
        >
          <Clock className="w-3.5 h-3.5" />
          Activity
        </button>
        <NotificationBell />
        <div className="text-sm text-gray-600">{user.full_name}</div>
        <button
          onClick={async () => { await logout(); router.push('/login') }}
          className="text-xs text-gray-400 hover:text-gray-600"
        >
          Logout
        </button>
      </header>
      <ActivityLogDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} />
    </>
  )
}
