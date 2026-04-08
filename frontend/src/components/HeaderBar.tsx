'use client'

import { useAuth } from '@/components/AuthContext'
import NotificationBell from '@/components/NotificationBell'
import { useRouter } from 'next/navigation'

export default function HeaderBar() {
  const { user, logout } = useAuth()
  const router = useRouter()

  if (!user) return null

  return (
    <header className="h-12 bg-white border-b border-gray-200 px-6 flex items-center justify-end gap-3 shrink-0">
      <NotificationBell />
      <div className="text-sm text-gray-600">{user.full_name}</div>
      <button
        onClick={async () => { await logout(); router.push('/login') }}
        className="text-xs text-gray-400 hover:text-gray-600"
      >
        Logout
      </button>
    </header>
  )
}
