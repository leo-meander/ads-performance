'use client'

import { ReactNode } from 'react'
import { usePathname } from 'next/navigation'
import Sidebar from '@/components/Sidebar'
import HeaderBar from '@/components/HeaderBar'
import RouteGuard from '@/components/RouteGuard'
import FloatingChatWidget from '@/components/FloatingChatWidget'

/**
 * Decides whether to render admin chrome (Sidebar + HeaderBar + RouteGuard)
 * or a bare layout suitable for public landing pages.
 *
 * Public routes:
 *   /lp/*   — customer-facing landing pages, SSR'd from our CMS.
 *             These must be fast (LCP < 1.8s per playbook §5.3) and render
 *             edge-to-edge without admin UI.
 */
export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const isPublicLanding = pathname?.startsWith('/lp/') ?? false
  const isLogin = pathname === '/login'

  if (isPublicLanding || isLogin) {
    // Bare shell — page owns its own full viewport
    return <>{children}</>
  }

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <HeaderBar />
        <main className="flex-1 overflow-auto p-6">
          <RouteGuard>{children}</RouteGuard>
        </main>
      </div>
      <FloatingChatWidget />
    </div>
  )
}
