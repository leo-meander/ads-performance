import type { LandingPageContent } from '@/lib/landingPage'

export default function FinalCTA({ data, anchor }: { data: LandingPageContent['final_cta']; anchor: string }) {
  if (!data.headline && !data.cta_label) return null
  return (
    <section id={anchor} className="py-20" style={{ backgroundColor: 'var(--lp-dark)', color: 'var(--lp-light)' }}>
      <div className="max-w-2xl mx-auto px-6 text-center">
        <h2 className="text-3xl md:text-4xl font-semibold leading-tight mb-4" style={{ fontFamily: 'var(--lp-font-h)' }}>
          {data.headline}
        </h2>
        {data.urgency_line && (
          <p className="text-sm mb-6 opacity-80 italic">{data.urgency_line}</p>
        )}
        <a
          href="#book"
          data-lp-cta="final-primary"
          className="inline-block w-full md:w-auto px-8 py-4 text-lg font-semibold rounded-lg shadow-lg transition-transform hover:scale-[1.02]"
          style={{ backgroundColor: 'var(--lp-primary)', color: '#fff', minHeight: 56 }}
        >
          {data.cta_label}
        </a>
        {data.sub_cta_label && data.sub_cta_href && (
          <p className="mt-5">
            <a href={data.sub_cta_href} className="text-sm underline-offset-4 hover:underline opacity-80">
              or {data.sub_cta_label}
            </a>
          </p>
        )}
      </div>
    </section>
  )
}
