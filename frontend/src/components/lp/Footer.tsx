import type { LandingPageContent } from '@/lib/landingPage'

export default function Footer({ data, pageTitle }: { data: LandingPageContent['footer']; pageTitle: string }) {
  return (
    <footer className="py-10 text-xs" style={{ backgroundColor: 'rgba(0,0,0,0.03)' }}>
      <div className="max-w-6xl mx-auto px-6 grid md:grid-cols-3 gap-6">
        <div>
          <p className="font-semibold mb-2">{pageTitle}</p>
          {data.contact?.address && <p className="text-[var(--lp-dark)]/70">{data.contact.address}</p>}
        </div>
        <div className="space-y-1">
          {data.contact?.phone && (
            <p><a href={`tel:${data.contact.phone}`} className="text-[var(--lp-dark)]/80 hover:underline">☎ {data.contact.phone}</a></p>
          )}
          {data.contact?.whatsapp && (
            <p><a href={data.contact.whatsapp} className="text-[var(--lp-dark)]/80 hover:underline">WhatsApp</a></p>
          )}
          {data.contact?.email && (
            <p><a href={`mailto:${data.contact.email}`} className="text-[var(--lp-dark)]/80 hover:underline">✉ {data.contact.email}</a></p>
          )}
        </div>
        <div className="space-y-1">
          {(data.policies || []).map((p, i) => (
            <p key={i}><a href={p.url} className="text-[var(--lp-dark)]/70 hover:underline">{p.label}</a></p>
          ))}
          {(data.social || []).map((s, i) => (
            <p key={`s${i}`}><a href={s.url} target="_blank" rel="noreferrer" className="text-[var(--lp-dark)]/70 hover:underline">{s.label}</a></p>
          ))}
        </div>
      </div>
    </footer>
  )
}
