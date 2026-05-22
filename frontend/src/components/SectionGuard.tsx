'use client'

import { ReactNode } from 'react'
import { useAuth } from '@/components/AuthContext'

interface SectionGuardProps {
  section: string
  /** Optional page key — when set, also requires page-level access. */
  page?: string
  children: ReactNode
  /** Optional custom fallback — defaults to a 403 card. */
  fallback?: ReactNode
}

/**
 * Wrap a page body with this guard to hide it from users who lack access
 * to the given section (and optionally the given page). The backend also
 * enforces 403s — this is purely a UX layer so users don't flash an empty
 * page while the API rejects.
 */
export default function SectionGuard({ section, page, children, fallback }: SectionGuardProps) {
  const { user, loading, canAccessSection, canAccessPage } = useAuth()

  if (loading) {
    return <div className="p-6 text-sm text-gray-500">Loading…</div>
  }

  if (!user) {
    // Not logged in — login page handles redirect; just render nothing here.
    return null
  }

  const allowed = page ? canAccessPage(page) : canAccessSection(section)
  if (!allowed) {
    if (fallback) return <>{fallback}</>
    return (
      <div className="max-w-md mx-auto mt-20 bg-white border border-gray-200 rounded-xl p-8 text-center">
        <div className="text-5xl mb-3">🔒</div>
        <h1 className="text-lg font-semibold text-gray-900 mb-1">Bạn không có quyền truy cập</h1>
        <p className="text-sm text-gray-500">
          Mục <span className="font-mono">{section}</span> chưa được cấp quyền cho tài khoản của
          bạn. Liên hệ admin để được cấp quyền.
        </p>
      </div>
    )
  }

  return <>{children}</>
}
