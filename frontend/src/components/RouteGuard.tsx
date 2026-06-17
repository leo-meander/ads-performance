'use client'

import { ReactNode, useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useAuth } from '@/components/AuthContext'
import SectionGuard from '@/components/SectionGuard'

// Maps URL paths to sections for permission gating. Order matters:
// longer/more-specific prefixes come first.
const ROUTE_SECTION_MAP: Array<[string, string]> = [
  ['/login', ''],              // always accessible
  ['/google', 'google_ads'],
  ['/budget', 'budget'],
  ['/rules', 'automation'],
  ['/logs', 'automation'],
  ['/insights', 'ai'],
  ['/transcriptions', 'ai'],
  ['/meta', 'meta_ads'],
  ['/angles', 'meta_ads'],
  ['/creative', 'meta_ads'],
  ['/approvals', 'meta_ads'],
  ['/keypoints', 'meta_ads'],
  ['/ad-research', 'meta_ads'],
  ['/country', 'analytics'],
  ['/action-needed', 'analytics'],
  ['/booking-matches', 'analytics'],
  ['/landing-pages', 'landing_pages'],
  ['/accounts', 'settings'],
  ['/users', 'settings'],   // still admin-gated inside the page itself
  ['/api-keys', 'settings'], // admin-gated inside the page itself
  ['/', 'analytics'],       // dashboard — matched last via exact check
]

function sectionForPath(pathname: string): string | null {
  if (pathname === '/') return 'analytics'
  for (const [prefix, section] of ROUTE_SECTION_MAP) {
    if (prefix === '/') continue
    if (prefix === '' && pathname === '/login') return null
    if (pathname === prefix || pathname.startsWith(prefix + '/')) {
      return section || null
    }
  }
  return null
}

// Maps URL paths to canonical page keys for per-page permission gating.
// Order matters: longer/more-specific prefixes come first. Keep page keys in
// sync with PAGE_SECTION in AuthContext + backend PAGES registry.
const ROUTE_PAGE_MAP: Array<[string, string]> = [
  ['/action-needed', 'dashboard'],
  ['/booking-matches', 'booking_matches'],
  ['/meta/recommendations', 'meta_recommendations'],
  ['/angles', 'angles'],
  ['/creative', 'creative'],
  ['/winning-ads', 'figma'],
  ['/approvals', 'approvals'],
  ['/keypoints', 'keypoints'],
  ['/ad-research', 'ad_research'],
  ['/google/pmax', 'google_pmax'],
  ['/google/search', 'google_search'],
  ['/google/recommendations', 'google_recommendations'],
  ['/google', 'google_overview'],
  ['/budget', 'budget_planner'],
  ['/landing-pages', 'landing_pages_all'],
  ['/tactics', 'tactics'],
  ['/logs', 'logs'],
  ['/insights', 'insights'],
  ['/transcriptions', 'transcriptions'],
  ['/accounts', 'accounts'],
  ['/users', 'users'],
  ['/api-keys', 'api_keys'],
  ['/settings', 'currency_rates'],
]

function pageForPath(pathname: string): string | null {
  if (pathname === '/') return 'dashboard'
  for (const [prefix, page] of ROUTE_PAGE_MAP) {
    if (pathname === prefix || pathname.startsWith(prefix + '/')) {
      return page
    }
  }
  return null
}

export default function RouteGuard({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const { user, loading } = useAuth()

  // Force password change before allowing access to anything except /login and
  // /change-password. Admin reset sets must_change_password = true.
  const mustChange = !!user?.must_change_password
  useEffect(() => {
    if (
      !loading &&
      mustChange &&
      pathname !== '/change-password' &&
      pathname !== '/login'
    ) {
      router.replace('/change-password')
    }
  }, [loading, mustChange, pathname, router])

  // Send unauthenticated users to /login instead of letting protected pages
  // render with no data (looks like a broken empty dashboard).
  useEffect(() => {
    if (!loading && !user && pathname !== '/login') {
      router.replace('/login')
    }
  }, [loading, user, pathname, router])

  // Login page: no guard
  if (pathname === '/login') return <>{children}</>

  // Still booting — render nothing to avoid a flash of an empty/unauthed page.
  if (loading) return null

  // Not logged in: redirect is in-flight; render nothing meanwhile.
  if (!user) return null

  // While the forced-redirect above is in-flight, render nothing to avoid a
  // flash of a gated page the user shouldn't see yet.
  if (mustChange && pathname !== '/change-password') return null

  // Allow access to /change-password for logged-in users regardless of section.
  if (pathname === '/change-password') return <>{children}</>

  const section = sectionForPath(pathname)
  if (!section) return <>{children}</>

  const page = pageForPath(pathname)
  return (
    <SectionGuard section={section} page={page ?? undefined}>
      {children}
    </SectionGuard>
  )
}
