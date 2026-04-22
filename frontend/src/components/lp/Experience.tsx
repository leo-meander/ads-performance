import type { LandingPageContent } from '@/lib/landingPage'

export default function Experience({ data }: { data: LandingPageContent['experience'] }) {
  const bundles = (data || []).filter((b) => b.title || b.description)
  if (bundles.length === 0) return null
  return (
    <section className="py-16" style={{ backgroundColor: 'rgba(0,0,0,0.03)' }}>
      <div className="max-w-6xl mx-auto px-6">
        <h2 className="text-2xl md:text-3xl font-semibold mb-8" style={{ fontFamily: 'var(--lp-font-h)' }}>
          The shape of your days
        </h2>
        <div className="grid md:grid-cols-3 gap-6">
          {bundles.map((b, i) => (
            <div key={i} className="bg-white rounded-lg p-5 border border-black/5">
              <h3 className="font-semibold text-lg mb-2" style={{ color: 'var(--lp-primary)' }}>{b.title}</h3>
              <p className="text-sm leading-relaxed text-[var(--lp-dark)]/80 whitespace-pre-line">{b.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}
