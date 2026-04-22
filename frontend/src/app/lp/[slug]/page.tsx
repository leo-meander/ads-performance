/**
 * Public landing page SSR renderer.
 *
 * Served at /lp/{slug}. Fetches content from the backend's public endpoint
 * (which returns the PUBLISHED version) and renders the 11 canonical modules
 * per the Hotel Landing Page Conversion Playbook.
 *
 * Mobile-first. Target LCP < 1.8s on 4G (playbook §5.3).
 */
import { notFound } from 'next/navigation'
import type { Metadata } from 'next'
import ClarityScript from '@/components/lp/ClarityScript'
import StickyBookBar from '@/components/lp/StickyBookBar'
import Hero from '@/components/lp/Hero'
import TrustBar from '@/components/lp/TrustBar'
import OneThing from '@/components/lp/OneThing'
import Rooms from '@/components/lp/Rooms'
import Location from '@/components/lp/Location'
import Experience from '@/components/lp/Experience'
import Stories from '@/components/lp/Stories'
import Offer from '@/components/lp/Offer'
import FAQ from '@/components/lp/FAQ'
import FinalCTA from '@/components/lp/FinalCTA'
import Footer from '@/components/lp/Footer'
import type { LandingPageContent } from '@/lib/landingPage'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type PageData = {
  page: {
    id: string
    title: string
    domain: string
    slug: string
    language: string | null
    ta: string | null
    clarity_project_id: string | null
    published_at: string | null
  }
  version: {
    id: string
    version_num: number
    content: LandingPageContent
  }
}

async function fetchPublished(host: string, slug: string): Promise<PageData | null> {
  try {
    const res = await fetch(`${API_BASE}/api/public/lp/${host}/${slug}`, {
      cache: 'no-store', // always fresh — the backend already caches via DB
    })
    if (!res.ok) return null
    const j = await res.json()
    if (!j.success || !j.data) return null
    return j.data
  } catch {
    return null
  }
}

/**
 * Slug in the URL path is the page slug. Domain in this deployment is
 * inferred from the request host header at runtime. For local preview
 * (where Next runs on localhost:3000) we fall back to a `?host=...` query
 * param which the public user never sees in production.
 */
export async function generateMetadata({ params, searchParams }: { params: { slug: string }; searchParams: { host?: string } }): Promise<Metadata> {
  const host = searchParams.host || 'preview.staymeander.com'
  const data = await fetchPublished(host, params.slug)
  if (!data) return { title: 'Not found' }
  const { content, } = data.version
  return {
    title: content.seo.title || data.page.title,
    description: content.seo.description,
    openGraph: {
      title: content.seo.title || data.page.title,
      description: content.seo.description,
      images: content.seo.og_image ? [content.seo.og_image] : undefined,
    },
  }
}

export default async function PublicLandingPage({ params, searchParams }: { params: { slug: string }; searchParams: { host?: string } }) {
  const host = searchParams.host || 'preview.staymeander.com'
  const data = await fetchPublished(host, params.slug)
  if (!data) notFound()

  const { content } = data.version
  const theme = content.theme

  // Inject CSS variables for theme — components read via var(--lp-*)
  const themeStyle = {
    ['--lp-primary' as any]: theme.primary_color,
    ['--lp-dark' as any]: theme.dark,
    ['--lp-light' as any]: theme.light,
    ['--lp-trust' as any]: theme.trust_blue || '#6A9BCC',
    ['--lp-eco' as any]: theme.eco_green || '#788C5D',
    ['--lp-font-h' as any]: `"${theme.font_heading}", system-ui, sans-serif`,
    ['--lp-font-b' as any]: `"${theme.font_body}", Georgia, serif`,
    backgroundColor: theme.light,
    color: theme.dark,
    fontFamily: `var(--lp-font-b)`,
  } as React.CSSProperties

  return (
    <>
      {data.page.clarity_project_id && <ClarityScript projectId={data.page.clarity_project_id} />}
      <div style={themeStyle} className="min-h-screen">
        <Hero data={content.hero} primaryHref="#book" />
        <TrustBar data={content.trust_bar} />
        <OneThing data={content.one_thing} />
        <Rooms data={content.rooms} anchor="rooms" />
        <Location data={content.location} />
        <Experience data={content.experience} />
        <Stories data={content.stories} />
        <Offer data={content.offer} />
        <FAQ data={content.faq} />
        <FinalCTA data={content.final_cta} anchor="book" />
        <Footer data={content.footer} pageTitle={data.page.title} />
        {/* Sticky mobile-only book bar — playbook §5.2 (+15-40% conversion) */}
        <StickyBookBar
          price={content.rooms[0]?.price_from}
          currency={content.rooms[0]?.price_currency}
          ctaLabel={content.hero.cta_label}
          primaryHref="#book"
          pageId={data.page.id}
        />
      </div>
    </>
  )
}
