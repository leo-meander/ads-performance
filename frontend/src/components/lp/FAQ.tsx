'use client'

import { useState } from 'react'
import type { LandingPageContent } from '@/lib/landingPage'

export default function FAQ({ data }: { data: LandingPageContent['faq'] }) {
  const items = (data || []).filter((i) => i.q && i.a)
  const [openIdx, setOpenIdx] = useState<number | null>(0)
  if (items.length === 0) return null
  return (
    <section className="py-16">
      <div className="max-w-3xl mx-auto px-6">
        <h2 className="text-2xl md:text-3xl font-semibold mb-8" style={{ fontFamily: 'var(--lp-font-h)' }}>
          Before you book
        </h2>
        <div className="space-y-2">
          {items.map((f, i) => {
            const open = openIdx === i
            return (
              <div key={i} className="border border-black/10 rounded-lg bg-white overflow-hidden">
                <button
                  onClick={() => setOpenIdx(open ? null : i)}
                  className="w-full flex items-center justify-between text-left px-4 py-3 hover:bg-black/[0.02] transition-colors"
                  style={{ minHeight: 44 }}
                >
                  <span className="font-medium">{f.q}</span>
                  <span className="text-xl leading-none" style={{ color: 'var(--lp-primary)' }}>{open ? '–' : '+'}</span>
                </button>
                {open && (
                  <div className="px-4 py-3 text-sm leading-relaxed text-[var(--lp-dark)]/80 border-t border-black/5 whitespace-pre-line">
                    {f.a}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}
