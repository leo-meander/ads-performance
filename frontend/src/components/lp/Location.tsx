import type { LandingPageContent } from '@/lib/landingPage'

export default function Location({ data }: { data: LandingPageContent['location'] }) {
  const hasContent = data.map_embed_url || data.paragraph || (data.walk_times || []).length > 0
  if (!hasContent) return null
  return (
    <section className="py-16">
      <div className="max-w-6xl mx-auto px-6 grid md:grid-cols-2 gap-10 items-start">
        <div>
          <h2 className="text-2xl md:text-3xl font-semibold mb-4" style={{ fontFamily: 'var(--lp-font-h)' }}>Where we are</h2>
          {data.paragraph && <p className="text-base leading-relaxed mb-6 text-[var(--lp-dark)]/80">{data.paragraph}</p>}

          {data.walk_times && data.walk_times.length > 0 && (
            <ul className="space-y-1.5 mb-6">
              {data.walk_times.map((w, i) => (
                <li key={i} className="flex items-baseline gap-3 text-sm">
                  <span className="font-bold tabular-nums" style={{ color: 'var(--lp-primary)' }}>{w.minutes} min</span>
                  <span className="text-[var(--lp-dark)]/80">→ {w.place}</span>
                </li>
              ))}
            </ul>
          )}

          {data.arrival_photo_url && (
            <figure className="rounded-lg overflow-hidden border border-black/5">
              <img src={data.arrival_photo_url} alt="Arrival from transit" loading="lazy" className="w-full aspect-[4/3] object-cover" />
              <figcaption className="text-xs text-[var(--lp-dark)]/50 p-2">From the transit exit — the path to the door.</figcaption>
            </figure>
          )}
        </div>

        {data.map_embed_url && (
          <div className="aspect-[4/3] md:aspect-square rounded-lg overflow-hidden border border-black/5">
            <iframe
              src={data.map_embed_url}
              className="w-full h-full border-0"
              loading="lazy"
              referrerPolicy="no-referrer-when-downgrade"
              allowFullScreen
            />
          </div>
        )}
      </div>
    </section>
  )
}
