'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

// Rules has been merged into /tactics — the Custom Rule preset covers the same
// use case (build your own condition → action) on top of the daily tactics
// pipeline (auditable, diagnostics panel, one mental model).
//
// Keep this redirect for bookmarks + the legacy /api/rules CRUD endpoints
// continue to work for any external integrations.
export default function RulesRedirect() {
  const router = useRouter()
  useEffect(() => {
    router.replace('/tactics')
  }, [router])
  return (
    <div className="p-6 text-sm text-gray-500">
      Rules has moved to <a href="/tactics" className="text-blue-600 underline">Tactics</a>. Redirecting…
    </div>
  )
}
