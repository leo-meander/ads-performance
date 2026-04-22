/**
 * TypeScript types + default content template for the Landing Page CMS.
 *
 * Mirror of the backend JSON schema stored in `landing_page_versions.content`.
 * All 11 canonical modules from the Hotel Landing Page Conversion Playbook.
 */

import { API_BASE } from '@/lib/api'

// ---------------------------------------------------------------- types ---

export type TrustItem = { score?: string; source?: string; count?: string; label?: string }

export type Room = {
  name: string
  size_sqm?: string
  bed?: string
  view?: string
  price_from?: string
  price_currency?: string
  price_includes?: string
  rating?: string
  photos?: string[]
  book_url?: string
}

export type Story = {
  name: string
  country?: string
  trip_type?: string
  quote: string
  source?: string
  rating?: string
  photo_url?: string
  date?: string
}

export type Comparison = { benefit: string; ota?: string; direct?: string }

export type ExperienceBundle = { title: string; description: string }

export type FAQItem = { q: string; a: string }

export type WalkTime = { minutes: string; place: string }

export type LandingPageContent = {
  hero: {
    headline: string
    subheadline: string
    cta_label: string
    image_url: string
    video_url?: string
    secondary_cta_label?: string
    secondary_cta_anchor?: string
  }
  trust_bar: {
    items: TrustItem[]
    badges?: string[]
  }
  one_thing: {
    headline: string
    vignette: string
    media_url: string
    quote?: string
  }
  rooms: Room[]
  location: {
    map_embed_url?: string
    walk_times: WalkTime[]
    paragraph?: string
    arrival_photo_url?: string
    pins?: { name: string; lat?: string; lng?: string }[]
  }
  experience: ExperienceBundle[]
  stories: Story[]
  offer: {
    comparison: Comparison[]
    perks?: string[]
  }
  faq: FAQItem[]
  final_cta: {
    headline: string
    urgency_line?: string
    cta_label: string
    sub_cta_label?: string
    sub_cta_href?: string
  }
  footer: {
    contact?: { phone?: string; email?: string; whatsapp?: string; address?: string }
    policies?: { label: string; url: string }[]
    social?: { label: string; url: string }[]
  }
  theme: {
    primary_color: string
    dark: string
    light: string
    trust_blue?: string
    eco_green?: string
    font_heading: string
    font_body: string
  }
  seo: {
    title: string
    description: string
    og_image?: string
  }
}

export type LandingPage = {
  id: string
  source: 'managed' | 'external'
  branch_id: string | null
  title: string
  domain: string
  slug: string
  public_url: string
  language: string | null
  ta: string | null
  status: string
  current_version_id: string | null
  published_at: string | null
  clarity_project_id: string | null
  created_by: string | null
  notes: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  current_version?: {
    id: string
    version_num: number
    content: LandingPageContent
    change_note: string | null
    published_at: string | null
  }
}

export type AdRollup = {
  spend: number
  impressions: number
  clicks: number
  link_clicks: number
  conversions: number
  revenue: number
  landing_page_views: number
  ctr: number | null
  cpc: number | null
  cpa: number | null
  roas: number | null
}

export type MetricsResponse = {
  landing_page_id: string
  date_from: string
  date_to: string
  ads: {
    totals: AdRollup
    by_platform: Record<string, AdRollup>
    campaign_count: number
  }
  clarity: {
    sessions: number
    distinct_users: number
    avg_scroll_depth: number | null
    total_time_sec: number
    active_time_sec: number
    dead_clicks: number
    rage_clicks: number
    error_clicks: number
    quickback_clicks: number
    excessive_scrolls: number
    script_errors: number
    rage_rate: number | null
    dead_rate: number | null
    quickback_rate: number | null
  }
  clarity_coverage: {
    requested_days: number
    days_with_data: number
    latest_synced_date: string | null
    is_complete: boolean
  }
  ga4: {
    sessions: number
    engaged_sessions: number
    active_users: number
    new_users: number
    page_views: number
    engagement_rate: number | null
    avg_session_duration_sec: number | null
    bounce_rate: number | null
    web_vitals: {
      lcp_p75_ms: number | null
      inp_p75_ms: number | null
      cls_p75: number | null
      fcp_p75_ms: number | null
      lcp_pass: boolean
      inp_pass: boolean
      cls_pass: boolean
    }
  }
  ga4_coverage: {
    requested_days: number
    days_with_data: number
    latest_synced_date: string | null
    is_complete: boolean
  }
  derived: {
    click_to_session_ratio: number | null
    link_click_to_session_ratio: number | null
    lpv_to_session_ratio: number | null
    dbcr: number | null
    dbcr_ga4: number | null
    reconciliation: {
      ga4_vs_meta_lpv?: number
      clarity_vs_ga4?: number
      ga4_vs_clicks?: number
      ga4_vs_link_clicks?: number
    }
  }
}

// ----------------------------------------------------------- defaults ---

/**
 * A fresh managed landing page starts with placeholder copy that matches
 * the playbook's refusal rules (no "Welcome to", no "world-class"). The
 * CMS editor shows these as greyed-out hints so the user can't ship an
 * unconfigured page.
 */
export function defaultContent(overrides: Partial<LandingPageContent> = {}): LandingPageContent {
  return {
    hero: {
      headline: '',
      subheadline: '',
      cta_label: 'Check My Dates',
      image_url: '',
      secondary_cta_label: 'See Rooms',
      secondary_cta_anchor: '#rooms',
    },
    trust_bar: {
      items: [
        { score: '', source: 'Booking.com', count: '' },
        { score: '', source: 'Hostelworld', count: '' },
      ],
    },
    one_thing: {
      headline: '',
      vignette: '',
      media_url: '',
    },
    rooms: [],
    location: {
      walk_times: [],
    },
    experience: [
      { title: 'Your mornings', description: '' },
      { title: 'Your afternoons', description: '' },
      { title: 'Your nights', description: '' },
    ],
    stories: [],
    offer: {
      comparison: [
        { benefit: 'Room rate', ota: '', direct: '' },
        { benefit: 'Free welcome drink', ota: '—', direct: 'Yes' },
        { benefit: 'Late checkout (2pm)', ota: '—', direct: 'Yes, on request' },
        { benefit: 'Flexible cancellation', ota: 'Paid rate only', direct: 'Free up to 24h' },
        { benefit: 'Room upgrade (if available)', ota: '—', direct: 'Yes, at check-in' },
      ],
    },
    faq: [
      { q: 'What is the cancellation policy?', a: '' },
      { q: 'When does the card get charged?', a: '' },
      { q: 'What time is check-in / check-out?', a: '' },
    ],
    final_cta: {
      headline: '',
      cta_label: 'Check My Dates',
    },
    footer: {
      contact: {},
      policies: [],
      social: [],
    },
    theme: {
      primary_color: '#D97757',
      dark: '#141413',
      light: '#FAF9F5',
      trust_blue: '#6A9BCC',
      eco_green: '#788C5D',
      font_heading: 'Poppins',
      font_body: 'Lora',
    },
    seo: {
      title: '',
      description: '',
    },
    ...overrides,
  }
}

// ----------------------------------------------- refusal-rule validator ---

/**
 * Playbook §10.4 refusal rules — phrases banned from hero headlines etc.
 * Surfaces as warnings in the editor; does NOT block save so users can
 * override with justification.
 */
const BANNED_PHRASES = [
  'welcome to',
  'we are',
  'world-class',
  'unforgettable',
  'the perfect getaway',
  'amazing location',
  'warm staff',
]

export function lintHeadline(text: string): string[] {
  const warnings: string[] = []
  const lower = (text || '').toLowerCase()
  for (const phrase of BANNED_PHRASES) {
    if (lower.includes(phrase)) {
      warnings.push(`Playbook refusal rule: avoid "${phrase}" — replace with specificity.`)
    }
  }
  if (text && text.split(/\s+/).length > 14) {
    warnings.push('Headline is long (>14 words). Aim for ≤8 words, one concrete promise.')
  }
  return warnings
}

// --------------------------------------------------- fetch helpers ---

export async function fetchLandingPages(params: URLSearchParams) {
  const res = await fetch(`${API_BASE}/api/landing-pages?${params}`, { credentials: 'include' })
  return res.json()
}

export async function fetchLandingPage(id: string) {
  const res = await fetch(`${API_BASE}/api/landing-pages/${id}`, { credentials: 'include' })
  return res.json()
}

export async function fetchMetrics(id: string, dateFrom: string, dateTo: string) {
  const res = await fetch(
    `${API_BASE}/api/landing-pages/${id}/metrics?date_from=${dateFrom}&date_to=${dateTo}`,
    { credentials: 'include' },
  )
  return res.json()
}

export async function fetchMetricsByUtm(id: string, dateFrom: string, dateTo: string) {
  const res = await fetch(
    `${API_BASE}/api/landing-pages/${id}/metrics/by-utm?date_from=${dateFrom}&date_to=${dateTo}`,
    { credentials: 'include' },
  )
  return res.json()
}
