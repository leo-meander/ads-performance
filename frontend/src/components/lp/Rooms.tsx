import type { LandingPageContent } from '@/lib/landingPage'

export default function Rooms({ data, anchor }: { data: LandingPageContent['rooms']; anchor: string }) {
  if (!data || data.length === 0) return null
  return (
    <section id={anchor} className="py-16" style={{ backgroundColor: 'rgba(0,0,0,0.03)' }}>
      <div className="max-w-6xl mx-auto px-6">
        <h2 className="text-2xl md:text-3xl font-semibold mb-8" style={{ fontFamily: 'var(--lp-font-h)' }}>
          Where you'll sleep
        </h2>
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
          {data.map((room, i) => (
            <article key={i} className="bg-white rounded-lg overflow-hidden shadow-sm border border-black/5">
              {room.photos && room.photos[0] && (
                <div className="aspect-[4/3] overflow-hidden">
                  <img src={room.photos[0]} alt={room.name} loading="lazy" decoding="async" className="w-full h-full object-cover" />
                </div>
              )}
              <div className="p-4">
                <h3 className="font-semibold text-lg mb-1">{room.name}</h3>
                <p className="text-xs text-[var(--lp-dark)]/60 mb-2">
                  {[room.size_sqm, room.bed, room.view].filter(Boolean).join(' · ')}
                </p>
                {room.price_from && (
                  <p className="text-sm mb-1">
                    <span className="font-semibold text-lg">{room.price_currency} {room.price_from}</span>
                    <span className="text-[var(--lp-dark)]/60 text-xs"> / night</span>
                  </p>
                )}
                {room.price_includes && <p className="text-xs text-[var(--lp-dark)]/60 mb-3">{room.price_includes}</p>}
                {room.rating && <p className="text-xs mb-3" style={{ color: 'var(--lp-trust)' }}>{room.rating} · guest rating</p>}
                {room.book_url && (
                  <a
                    href={room.book_url}
                    data-lp-cta={`room-${i}`}
                    className="block text-center px-4 py-2 text-sm font-semibold rounded text-white transition-opacity hover:opacity-90"
                    style={{ backgroundColor: 'var(--lp-primary)', minHeight: 44 }}
                  >
                    Book this room
                  </a>
                )}
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
