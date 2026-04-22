import type { LandingPageContent } from '@/lib/landingPage'

export default function Stories({ data }: { data: LandingPageContent['stories'] }) {
  const stories = (data || []).filter((s) => s.name && s.quote)
  if (stories.length === 0) return null
  return (
    <section className="py-16">
      <div className="max-w-6xl mx-auto px-6">
        <h2 className="text-2xl md:text-3xl font-semibold mb-8" style={{ fontFamily: 'var(--lp-font-h)' }}>
          Guests who stayed
        </h2>
        <div className="grid md:grid-cols-3 gap-6">
          {stories.map((s, i) => (
            <figure key={i} className="bg-white rounded-lg p-5 border border-black/5">
              {s.photo_url && (
                <img src={s.photo_url} alt="" loading="lazy" className="w-full aspect-[4/3] rounded mb-3 object-cover" />
              )}
              <blockquote className="text-sm leading-relaxed text-[var(--lp-dark)]/85 mb-3">
                “{s.quote}”
              </blockquote>
              <figcaption className="text-xs text-[var(--lp-dark)]/70">
                <span className="font-semibold">{s.name}</span>
                {s.country && <span> · {s.country}</span>}
                {s.trip_type && <span> · {s.trip_type}</span>}
                {s.date && <span> · {s.date}</span>}
                {(s.source || s.rating) && (
                  <div className="mt-1 text-[var(--lp-dark)]/50">
                    {s.rating && <strong>{s.rating}</strong>}
                    {s.source && <span> · {s.source}</span>}
                  </div>
                )}
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  )
}
