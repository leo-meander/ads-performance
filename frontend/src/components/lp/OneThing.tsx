import type { LandingPageContent } from '@/lib/landingPage'

export default function OneThing({ data }: { data: LandingPageContent['one_thing'] }) {
  if (!data.headline && !data.vignette && !data.media_url) return null
  return (
    <section className="py-16 md:py-24">
      <div className="max-w-6xl mx-auto px-6 grid md:grid-cols-2 gap-10 items-center">
        {data.media_url && (
          <div className="aspect-[4/5] md:aspect-square overflow-hidden rounded-lg">
            <img
              src={data.media_url}
              alt=""
              loading="lazy"
              decoding="async"
              className="w-full h-full object-cover"
            />
          </div>
        )}
        <div>
          <h2
            className="text-2xl md:text-4xl font-semibold leading-tight mb-5"
            style={{ fontFamily: 'var(--lp-font-h)' }}
          >
            {data.headline}
          </h2>
          <p className="text-base md:text-lg leading-relaxed text-[var(--lp-dark)]/80 whitespace-pre-line">
            {data.vignette}
          </p>
          {data.quote && (
            <blockquote className="mt-6 pl-4 border-l-4 italic text-sm text-[var(--lp-dark)]/70" style={{ borderColor: 'var(--lp-primary)' }}>
              “{data.quote}”
            </blockquote>
          )}
        </div>
      </div>
    </section>
  )
}
