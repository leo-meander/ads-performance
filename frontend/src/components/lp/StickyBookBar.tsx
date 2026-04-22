'use client'

import { useEffect, useState } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

/**
 * Mobile-only sticky bottom bar (playbook §5.2: +15–40% conversion).
 * Appears after the visitor scrolls past the hero. Emits a `cta_click`
 * event to our backend when tapped (for custom funnel tracking beyond
 * what Clarity sees).
 */
export default function StickyBookBar({
  price,
  currency,
  ctaLabel,
  primaryHref,
  pageId,
}: {
  price?: string
  currency?: string
  ctaLabel: string
  primaryHref: string
  pageId: string
}) {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const onScroll = () => setVisible(window.scrollY > 600)
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  const onClick = () => {
    // fire-and-forget beacon
    const utm = new URLSearchParams(window.location.search)
    navigator.sendBeacon?.(
      `${API_BASE}/api/public/lp/${pageId}/event`,
      new Blob(
        [
          JSON.stringify({
            event_type: 'cta_click',
            event_label: 'sticky-book-bar',
            utm_source: utm.get('utm_source') || undefined,
            utm_campaign: utm.get('utm_campaign') || undefined,
            utm_content: utm.get('utm_content') || undefined,
          }),
        ],
        { type: 'application/json' },
      ),
    )
  }

  return (
    <div
      aria-hidden={!visible}
      className={`md:hidden fixed bottom-0 left-0 right-0 z-40 transition-transform ${visible ? 'translate-y-0' : 'translate-y-full'}`}
      style={{ backgroundColor: 'var(--lp-dark)', color: 'var(--lp-light)' }}
    >
      <div className="flex items-center justify-between px-4 py-2.5 gap-3">
        {price && (
          <div className="text-sm">
            <span className="opacity-70 text-xs">From</span>{' '}
            <span className="font-semibold">{currency} {price}</span>
          </div>
        )}
        <a
          href={primaryHref}
          onClick={onClick}
          data-lp-cta="sticky-book-bar"
          className="flex-1 text-center px-4 py-2.5 text-sm font-semibold rounded"
          style={{ backgroundColor: 'var(--lp-primary)', color: '#fff', minHeight: 44 }}
        >
          {ctaLabel}
        </a>
      </div>
    </div>
  )
}
