import type { LandingPageContent } from '@/lib/landingPage'

export default function TrustBar({ data }: { data: LandingPageContent['trust_bar'] }) {
  const items = (data.items || []).filter((i) => i.score || i.source)
  if (items.length === 0) return null
  return (
    <section className="py-5 border-y" style={{ borderColor: 'rgba(0,0,0,0.08)' }}>
      <div className="max-w-5xl mx-auto px-6 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm">
        {items.map((it, i) => (
          <div key={i} className="flex items-center gap-1.5">
            {it.score && <span className="font-bold" style={{ color: 'var(--lp-trust)' }}>{it.score}</span>}
            <span className="text-[var(--lp-dark)]/70">on {it.source}</span>
            {it.count && <span className="text-[var(--lp-dark)]/50 text-xs">· {it.count} reviews</span>}
          </div>
        ))}
        {data.badges && data.badges.map((b, i) => (
          <span key={`b${i}`} className="text-xs px-2 py-0.5 rounded border border-current text-[var(--lp-dark)]/60">
            {b}
          </span>
        ))}
      </div>
    </section>
  )
}
