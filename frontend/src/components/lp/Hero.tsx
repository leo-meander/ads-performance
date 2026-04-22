import type { LandingPageContent } from '@/lib/landingPage'

export default function Hero({ data, primaryHref }: { data: LandingPageContent['hero']; primaryHref: string }) {
  return (
    <section className="relative min-h-[100vh] md:min-h-[85vh] flex items-end md:items-center">
      {data.image_url && (
        <img
          src={data.image_url}
          alt=""
          /* Preload-friendly hints: fetchpriority + eager load — this is the LCP element */
          // @ts-expect-error fetchpriority is valid HTML but React types lag
          fetchpriority="high"
          loading="eager"
          decoding="async"
          className="absolute inset-0 w-full h-full object-cover"
        />
      )}
      {data.video_url && (
        <video
          src={data.video_url}
          autoPlay
          muted
          loop
          playsInline
          preload="none"
          poster={data.image_url}
          className="absolute inset-0 w-full h-full object-cover"
        />
      )}
      {/* Gradient overlay for text legibility — never a flat dark box */}
      <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-black/30 to-transparent" />

      <div className="relative max-w-3xl mx-auto px-6 pb-16 md:pb-24 text-white">
        <h1
          className="text-3xl md:text-5xl font-semibold leading-tight mb-3"
          style={{ fontFamily: 'var(--lp-font-h)' }}
        >
          {data.headline || '—'}
        </h1>
        <p className="text-base md:text-lg text-white/90 mb-6 max-w-xl">{data.subheadline}</p>
        <div className="flex flex-col md:flex-row items-start md:items-center gap-3">
          <a
            href={primaryHref}
            data-lp-cta="hero-primary"
            className="inline-block px-6 py-3 text-base font-semibold rounded-lg shadow-lg transition-transform hover:scale-[1.02]"
            style={{ backgroundColor: 'var(--lp-primary)', color: '#fff', minHeight: 52 }}
          >
            {data.cta_label || 'Check My Dates'}
          </a>
          {data.secondary_cta_label && (
            <a
              href={data.secondary_cta_anchor || '#rooms'}
              className="text-sm text-white/90 underline-offset-4 hover:underline"
            >
              {data.secondary_cta_label}
            </a>
          )}
        </div>
      </div>
    </section>
  )
}
