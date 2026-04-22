import type { LandingPageContent } from '@/lib/landingPage'

export default function Offer({ data }: { data: LandingPageContent['offer'] }) {
  const rows = (data.comparison || []).filter((r) => r.benefit)
  if (rows.length === 0) return null
  return (
    <section className="py-16" style={{ backgroundColor: 'var(--lp-light)' }}>
      <div className="max-w-3xl mx-auto px-6">
        <h2 className="text-2xl md:text-3xl font-semibold mb-2 text-center" style={{ fontFamily: 'var(--lp-font-h)' }}>
          Book direct. It's better here.
        </h2>
        <p className="text-center text-sm text-[var(--lp-dark)]/60 mb-8">Same price, more perks. The math:</p>

        <div className="bg-white rounded-lg overflow-hidden border border-black/10 shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-[var(--lp-dark)] text-white">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Benefit</th>
                <th className="px-4 py-3 text-center font-medium">On an OTA</th>
                <th className="px-4 py-3 text-center font-medium" style={{ backgroundColor: 'var(--lp-primary)' }}>Book direct</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-black/[0.02]'}>
                  <td className="px-4 py-3">{r.benefit}</td>
                  <td className="px-4 py-3 text-center text-[var(--lp-dark)]/60">{r.ota || '—'}</td>
                  <td className="px-4 py-3 text-center font-semibold">{r.direct || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}
