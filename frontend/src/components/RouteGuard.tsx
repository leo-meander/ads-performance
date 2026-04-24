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

  // Login page: no guard
  if (pathname === '/login') return <>{children}</>

  // Still booting — let the page handle its own loading state
  if (loading) return <>{children}</>

  // Not logged in: don't gate (pages typically redirect to /login themselves)
  if (!user) return <>{children}</>

  // While the forced-redirect above is in-flight, render nothing to avoid a
  // flash of a gated page the user shouldn't see yet.
  if (mustChange && pathname !== '/change-password') return null

  // Allow access to /change-password for logged-in users regardless of section.
  if (pathname === '/change-password') return <>{children}</>

  const section = sectionForPath(pathname)
  if (!section) return <>{children}</>

  return <SectionGuard section={section}>{children}</SectionGuard>
}
