'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useAuth } from '@/components/AuthContext'
import { API_BASE } from '@/lib/api'
import { defaultContent, lintHeadline, type LandingPage, type LandingPageContent } from '@/lib/landingPage'

type TabKey =
  | 'hero' | 'trust' | 'one_thing' | 'rooms' | 'location'
  | 'experience' | 'stories' | 'offer' | 'faq' | 'final_cta' | 'theme_seo'

const TABS: { key: TabKey; label: string; help: string }[] = [
  { key: 'hero',        label: '1. Hero',           help: 'First 3 seconds. One visual, one headline, one CTA.' },
  { key: 'trust',       label: '2. Trust Bar',      help: 'Review scores with source. Specific numbers beat badges.' },
  { key: 'one_thing',   label: '3. The One Thing',  help: 'The uncopyable hook. One feature, dramatized.' },
  { key: 'rooms',       label: '4. Rooms',          help: 'Per-room: photos, m², bed, price incl. taxes.' },
  { key: 'location',    label: '5. Location',       help: 'Walk times in minutes. Map. Arrival photo.' },
  { key: 'experience',  label: '6. Experience',     help: '3–5 emotional bundles. Shape of a day.' },
  { key: 'stories',     label: '7. Guest Stories',  help: 'Named people. Real quotes. Sources.' },
  { key: 'offer',       label: '8. Direct-Book Offer', help: 'OTA vs Direct comparison. 2+ concrete perks.' },
  { key: 'faq',         label: '9. FAQ',            help: 'Pre-empt bounces. Cancellation, payment, arrival.' },
  { key: 'final_cta',   label: '10. Final CTA',     help: 'Callback to hero. One decision. One button.' },
  { key: 'theme_seo',   label: '11. Theme + SEO',   help: 'Brand colors, fonts, meta tags.' },
]

export default function LandingPageEditor() {
  const params = useParams()
  const router = useRouter()
  const pageId = params.id as string
  const { canEditSection } = useAuth()
  const canEdit = canEditSection('landing_pages')

  const [page, setPage] = useState<LandingPage | null>(null)
  const [content, setContent] = useState<LandingPageContent>(defaultContent())
  const [activeTab, setActiveTab] = useState<TabKey>('hero')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [changeNote, setChangeNote] = useState('')

  // Approval state
  const [showSubmit, setShowSubmit] = useState(false)
  const [users, setUsers] = useState<{ id: string; full_name: string; email: string }[]>([])
  const [reviewerIds, setReviewerIds] = useState<string[]>([])
  const [latestVersionId, setLatestVersionId] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const res = await fetch(`${API_BASE}/api/landing-pages/${pageId}`, { credentials: 'include' })
        const j = await res.json()
        if (!j.success) {
          setError(j.error)
        } else {
          setPage(j.data)
          if (j.data.current_version?.content) {
            setContent({ ...defaultContent(), ...j.data.current_version.content })
            setLatestVersionId(j.data.current_version.id)
          } else {
            // Check if there are any versions
            const vs = await fetch(`${API_BASE}/api/landing-pages/${pageId}/versions`, { credentials: 'include' })
              .then((r) => r.json())
            if (vs.success && vs.data.length > 0) {
              setLatestVersionId(vs.data[0].id)
              // Load latest draft content
              const vRes = await fetch(`${API_BASE}/api/landing-pages/${pageId}`, { credentials: 'include' })
              const vJ = await vRes.json()
              if (vJ.success && vJ.data.current_version?.content) {
                setContent({ ...defaultContent(), ...vJ.data.current_version.content })
              }
            }
          }
        }
      } catch (e) {
        setError(String(e))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [pageId])

  // Load users for reviewer picker (admins + creators)
  useEffect(() => {
    fetch(`${API_BASE}/api/users`, { credentials: 'include' })
      .then((r) => r.json())
      .then((j) => { if (j.success) setUsers(j.data || []) })
      .catch(() => {})
  }, [])

  const patch = <K extends keyof LandingPageContent>(key: K, value: LandingPageContent[K]) => {
    setContent((c) => ({ ...c, [key]: value }))
    setDirty(true)
  }

  const saveVersion = async () => {
    setSaving(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/landing-pages/${pageId}/versions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ content, change_note: changeNote || null }),
      })
      const j = await res.json()
      if (!j.success) {
        setError(j.error || 'Save failed')
      } else {
        setDirty(false)
        setChangeNote('')
        setLatestVersionId(j.data.id)
        alert(`Saved version #${j.data.version_num}`)
      }
    } finally {
      setSaving(false)
    }
  }

  const submitForApproval = async () => {
    if (!latestVersionId) {
      alert('Save a version first')
      return
    }
    if (reviewerIds.length === 0) {
      alert('Pick at least one reviewer')
      return
    }
    setSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/landing-pages/${pageId}/approvals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          version_id: latestVersionId,
          reviewer_ids: reviewerIds,
          deadline_hours: 48,
        }),
      })
      const j = await res.json()
      if (!j.success) {
        alert(`Submit failed: ${j.error}`)
      } else {
        setShowSubmit(false)
        setReviewerIds([])
        alert('Submitted for approval')
        router.refresh()
        window.location.reload()
      }
    } finally {
      setSaving(false)
    }
  }

  const publish = async () => {
    if (!latestVersionId) return
    if (!confirm('Publish this version to the public URL?')) return
    const res = await fetch(`${API_BASE}/api/landing-pages/${pageId}/publish?version_id=${latestVersionId}`, {
      method: 'POST',
      credentials: 'include',
    })
    const j = await res.json()
    if (!j.success) {
      alert(`Publish failed: ${j.error}`)
    } else {
      alert('Published!')
      window.location.reload()
    }
  }

  if (loading) return <div className="text-gray-500">Loading…</div>
  if (!page) return <div className="text-red-600">Not found</div>

  const isExternal = page.source === 'external'

  return (
    <div className="max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div>
          <Link href="/landing-pages" className="text-xs text-gray-500 hover:underline">&larr; All landing pages</Link>
          <h1 className="text-2xl font-bold text-gray-900 mt-1">{page.title}</h1>
          <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
            <a href={page.public_url} target="_blank" rel="noreferrer" className="font-mono text-xs hover:underline">{page.domain}/{page.slug}</a>
            <span className="text-xs px-2 py-0.5 rounded bg-gray-100">{page.status}</span>
            <span className="text-xs px-2 py-0.5 rounded bg-indigo-50 text-indigo-700">{page.source}</span>
            {page.ta && <span className="text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700">{page.ta}</span>}
          </div>
        </div>
        <div className="flex gap-2">
          <Link href={`/landing-pages/${pageId}/performance`} className="px-3 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50">Analytics</Link>
          {canEdit && !isExternal && (
            <>
              <button onClick={saveVersion} disabled={!dirty || saving} className="px-3 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                {saving ? 'Saving…' : dirty ? 'Save version' : 'Saved'}
              </button>
              {page.status === 'DRAFT' || page.status === 'REJECTED' ? (
                <button onClick={() => setShowSubmit(true)} disabled={!latestVersionId} className="px-3 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50">
                  Submit for Approval
                </button>
              ) : page.status === 'APPROVED' ? (
                <button onClick={publish} className="px-3 py-2 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700">Publish</button>
              ) : null}
            </>
          )}
        </div>
      </div>

      {isExternal && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 px-4 py-2 rounded mb-4 text-sm">
          This is an <strong>external</strong> landing page discovered from ads/Clarity. CMS editing is disabled —
          it lives on an existing site outside our system. Use <Link href={`/landing-pages/${pageId}/performance`} className="underline">Analytics</Link> to evaluate it.
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded mb-4 text-sm">{error}</div>
      )}

      {!isExternal && (
        <>
          {/* Tabs */}
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <div className="flex overflow-x-auto border-b border-gray-200 bg-gray-50">
              {TABS.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setActiveTab(t.key)}
                  className={`px-4 py-3 text-xs font-medium whitespace-nowrap transition-colors ${
                    activeTab === t.key ? 'bg-white text-blue-700 border-b-2 border-blue-600' : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="p-6">
              <p className="text-xs text-gray-500 mb-4">{TABS.find((t) => t.key === activeTab)?.help}</p>

              {activeTab === 'hero' && <HeroEditor content={content} patch={patch} />}
              {activeTab === 'trust' && <TrustEditor content={content} patch={patch} />}
              {activeTab === 'one_thing' && <OneThingEditor content={content} patch={patch} />}
              {activeTab === 'rooms' && <RoomsEditor content={content} patch={patch} />}
              {activeTab === 'location' && <LocationEditor content={content} patch={patch} />}
              {activeTab === 'experience' && <ExperienceEditor content={content} patch={patch} />}
              {activeTab === 'stories' && <StoriesEditor content={content} patch={patch} />}
              {activeTab === 'offer' && <OfferEditor content={content} patch={patch} />}
              {activeTab === 'faq' && <FAQEditor content={content} patch={patch} />}
              {activeTab === 'final_cta' && <FinalCtaEditor content={content} patch={patch} />}
              {activeTab === 'theme_seo' && <ThemeSeoEditor content={content} patch={patch} />}
            </div>
          </div>

          {/* Change note (optional) */}
          {dirty && (
            <div className="mt-4 bg-white border border-gray-200 rounded-lg p-4">
              <label className="text-xs text-gray-600 block mb-1">Change note (optional)</label>
              <input value={changeNote} onChange={(e) => setChangeNote(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="e.g., Updated hero headline based on review mining" />
            </div>
          )}
        </>
      )}

      {/* Submit-for-approval modal */}
      {showSubmit && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl w-[500px] p-6">
            <h2 className="text-lg font-bold mb-2">Submit for Approval</h2>
            <p className="text-sm text-gray-600 mb-4">
              Pick reviewers. All reviewers must approve before the page can be published.
              Any single rejection marks the version REJECTED and sends it back to you.
            </p>
            <label className="text-xs text-gray-600 block mb-1">Reviewers</label>
            <div className="max-h-48 overflow-auto border border-gray-200 rounded p-2 space-y-1">
              {users.map((u) => (
                <label key={u.id} className="flex items-center gap-2 text-sm py-1 hover:bg-gray-50 px-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={reviewerIds.includes(u.id)}
                    onChange={(e) => {
                      if (e.target.checked) setReviewerIds([...reviewerIds, u.id])
                      else setReviewerIds(reviewerIds.filter((i) => i !== u.id))
                    }}
                  />
                  <span>{u.full_name}</span>
                  <span className="text-xs text-gray-500">{u.email}</span>
                </label>
              ))}
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button onClick={() => setShowSubmit(false)} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded">Cancel</button>
              <button onClick={submitForApproval} disabled={reviewerIds.length === 0 || saving} className="px-3 py-1.5 text-sm bg-emerald-600 text-white rounded hover:bg-emerald-700 disabled:opacity-50">
                {saving ? 'Submitting…' : `Submit (${reviewerIds.length})`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─────────────── Editors per tab ───────────────────────────────

type EditorProps = {
  content: LandingPageContent
  patch: <K extends keyof LandingPageContent>(k: K, v: LandingPageContent[K]) => void
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <label className="text-xs font-medium text-gray-700 block mb-1">{label}</label>
      {children}
      {hint && <p className="text-[11px] text-gray-500 mt-1">{hint}</p>}
    </div>
  )
}

function HeroEditor({ content, patch }: EditorProps) {
  const warnings = lintHeadline(content.hero.headline)
  return (
    <div className="grid grid-cols-2 gap-6">
      <div>
        <Field label="Headline" hint="≤8 words. Specific, sensory, unfinished-feel. No 'Welcome to'.">
          <input value={content.hero.headline} onChange={(e) => patch('hero', { ...content.hero, headline: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="There's a slide between the floors." />
          {warnings.map((w, i) => (<p key={i} className="text-[11px] text-amber-700 mt-1">⚠ {w}</p>))}
        </Field>
        <Field label="Subheadline" hint="One concrete credibility anchor. Score, years, or walk-time.">
          <input value={content.hero.subheadline} onChange={(e) => patch('hero', { ...content.hero, subheadline: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="8.8/10 on Booking. Rooftop opens at 5pm." />
        </Field>
        <Field label="Primary CTA label" hint="Action + outcome. Not 'Learn More'.">
          <input value={content.hero.cta_label} onChange={(e) => patch('hero', { ...content.hero, cta_label: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
        </Field>
        <Field label="Secondary anchor label" hint='e.g., "See Rooms" — jumps to #rooms'>
          <input value={content.hero.secondary_cta_label || ''} onChange={(e) => patch('hero', { ...content.hero, secondary_cta_label: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
        </Field>
      </div>
      <div>
        <Field label="Hero image URL" hint="Vertical crop (2:3 or 3:4). Human in the scene. <300KB.">
          <input value={content.hero.image_url} onChange={(e) => patch('hero', { ...content.hero, image_url: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="https://..." />
          {content.hero.image_url && <img src={content.hero.image_url} alt="" className="mt-2 rounded border border-gray-200 max-h-48 object-cover" />}
        </Field>
        <Field label="Hero video URL (optional)" hint="Silent loop only. Autoplay OK, audio = conversion killer.">
          <input value={content.hero.video_url || ''} onChange={(e) => patch('hero', { ...content.hero, video_url: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
        </Field>
      </div>
    </div>
  )
}

function TrustEditor({ content, patch }: EditorProps) {
  const items = content.trust_bar.items
  const update = (idx: number, field: string, val: string) => {
    const arr = [...items]
    arr[idx] = { ...arr[idx], [field]: val }
    patch('trust_bar', { ...content.trust_bar, items: arr })
  }
  return (
    <div>
      <p className="text-xs text-gray-500 mb-3">Ex: <code className="bg-gray-100 px-1 rounded">9.2 · Hostelworld · 1,247 reviews</code></p>
      <div className="space-y-2">
        {items.map((it, i) => (
          <div key={i} className="grid grid-cols-[1fr_2fr_1fr_auto] gap-2">
            <input placeholder="Score (9.2)" value={it.score || ''} onChange={(e) => update(i, 'score', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
            <input placeholder="Source (Booking.com)" value={it.source || ''} onChange={(e) => update(i, 'source', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
            <input placeholder="Count (1,247)" value={it.count || ''} onChange={(e) => update(i, 'count', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
            <button onClick={() => patch('trust_bar', { ...content.trust_bar, items: items.filter((_, idx) => idx !== i) })} className="text-xs text-red-600 hover:underline">Remove</button>
          </div>
        ))}
      </div>
      <button onClick={() => patch('trust_bar', { ...content.trust_bar, items: [...items, { score: '', source: '', count: '' }] })} className="mt-3 text-sm text-blue-600 hover:underline">+ Add trust item</button>
    </div>
  )
}

function OneThingEditor({ content, patch }: EditorProps) {
  return (
    <div className="grid grid-cols-2 gap-6">
      <div>
        <Field label="The One Thing headline" hint="The one uncopyable feature. Specific, physical, photographable.">
          <input value={content.one_thing.headline} onChange={(e) => patch('one_thing', { ...content.one_thing, headline: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="Yes, there is an actual slide." />
        </Field>
        <Field label="Vignette (40–60 words, zero adjectives)">
          <textarea value={content.one_thing.vignette} onChange={(e) => patch('one_thing', { ...content.one_thing, vignette: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" rows={5} />
        </Field>
        <Field label="Review quote (optional)">
          <textarea value={content.one_thing.quote || ''} onChange={(e) => patch('one_thing', { ...content.one_thing, quote: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" rows={2} />
        </Field>
      </div>
      <div>
        <Field label="Media URL (photo or loop)">
          <input value={content.one_thing.media_url} onChange={(e) => patch('one_thing', { ...content.one_thing, media_url: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
          {content.one_thing.media_url && <img src={content.one_thing.media_url} alt="" className="mt-2 rounded border border-gray-200 max-h-48 object-cover" />}
        </Field>
      </div>
    </div>
  )
}

function RoomsEditor({ content, patch }: EditorProps) {
  const rooms = content.rooms
  const update = (idx: number, field: keyof (typeof rooms)[0], val: any) => {
    const arr = [...rooms]
    arr[idx] = { ...arr[idx], [field]: val }
    patch('rooms', arr)
  }
  return (
    <div className="space-y-4">
      {rooms.map((r, i) => (
        <div key={i} className="border border-gray-200 rounded p-4 space-y-2">
          <div className="grid grid-cols-4 gap-2">
            <input placeholder="Name (Deluxe Double)" value={r.name} onChange={(e) => update(i, 'name', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm col-span-2" />
            <input placeholder="Size (18 m²)" value={r.size_sqm || ''} onChange={(e) => update(i, 'size_sqm', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
            <input placeholder="Bed (Queen)" value={r.bed || ''} onChange={(e) => update(i, 'bed', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
          </div>
          <div className="grid grid-cols-4 gap-2">
            <input placeholder="View (Garden)" value={r.view || ''} onChange={(e) => update(i, 'view', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
            <input placeholder="From (1,450,000)" value={r.price_from || ''} onChange={(e) => update(i, 'price_from', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
            <input placeholder="Currency (VND)" value={r.price_currency || ''} onChange={(e) => update(i, 'price_currency', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
            <input placeholder="Rating (9.1)" value={r.rating || ''} onChange={(e) => update(i, 'rating', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
          </div>
          <input placeholder="Price includes (incl. breakfast + all taxes)" value={r.price_includes || ''} onChange={(e) => update(i, 'price_includes', e.target.value)} className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm" />
          <input placeholder="Book URL (deep link)" value={r.book_url || ''} onChange={(e) => update(i, 'book_url', e.target.value)} className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm" />
          <input placeholder="Photo URLs (comma-separated)" value={(r.photos || []).join(', ')} onChange={(e) => update(i, 'photos', e.target.value.split(',').map((s) => s.trim()).filter(Boolean))} className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm" />
          <button onClick={() => patch('rooms', rooms.filter((_, idx) => idx !== i))} className="text-xs text-red-600 hover:underline">Remove room</button>
        </div>
      ))}
      <button onClick={() => patch('rooms', [...rooms, { name: '' }])} className="text-sm text-blue-600 hover:underline">+ Add room</button>
    </div>
  )
}

function LocationEditor({ content, patch }: EditorProps) {
  return (
    <div>
      <Field label="Neighborhood paragraph (≤40 words)">
        <textarea value={content.location.paragraph || ''} onChange={(e) => patch('location', { ...content.location, paragraph: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" rows={3} />
      </Field>
      <Field label="Walk times (one per line, format: '2|Exit Y13 at Taipei Main Station')">
        <textarea
          value={(content.location.walk_times || []).map((w) => `${w.minutes}|${w.place}`).join('\n')}
          onChange={(e) => patch('location', { ...content.location, walk_times: e.target.value.split('\n').filter(Boolean).map((line) => { const [m, ...rest] = line.split('|'); return { minutes: m.trim(), place: rest.join('|').trim() } }) })}
          className="w-full px-3 py-2 border border-gray-300 rounded text-sm font-mono"
          rows={6}
        />
      </Field>
      <div className="grid grid-cols-2 gap-4">
        <Field label="Map embed URL (Google Maps iframe src)">
          <input value={content.location.map_embed_url || ''} onChange={(e) => patch('location', { ...content.location, map_embed_url: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
        </Field>
        <Field label="Arrival photo URL">
          <input value={content.location.arrival_photo_url || ''} onChange={(e) => patch('location', { ...content.location, arrival_photo_url: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
        </Field>
      </div>
    </div>
  )
}

function ExperienceEditor({ content, patch }: EditorProps) {
  const bundles = content.experience
  return (
    <div className="space-y-3">
      {bundles.map((b, i) => (
        <div key={i} className="border border-gray-200 rounded p-3 space-y-2">
          <input placeholder="Bundle title (Your mornings)" value={b.title} onChange={(e) => patch('experience', bundles.map((x, idx) => idx === i ? { ...x, title: e.target.value } : x))} className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm font-medium" />
          <textarea placeholder="Description — specific, sensory, one micro-story" value={b.description} onChange={(e) => patch('experience', bundles.map((x, idx) => idx === i ? { ...x, description: e.target.value } : x))} className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm" rows={3} />
          <button onClick={() => patch('experience', bundles.filter((_, idx) => idx !== i))} className="text-xs text-red-600 hover:underline">Remove bundle</button>
        </div>
      ))}
      <button onClick={() => patch('experience', [...bundles, { title: '', description: '' }])} className="text-sm text-blue-600 hover:underline">+ Add bundle</button>
    </div>
  )
}

function StoriesEditor({ content, patch }: EditorProps) {
  const stories = content.stories
  const update = (idx: number, field: any, val: string) => {
    patch('stories', stories.map((s, i) => i === idx ? { ...s, [field]: val } : s))
  }
  return (
    <div className="space-y-3">
      {stories.map((s, i) => (
        <div key={i} className="border border-gray-200 rounded p-3 grid grid-cols-2 gap-2">
          <input placeholder="Guest first name" value={s.name} onChange={(e) => update(i, 'name', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
          <input placeholder="Country" value={s.country || ''} onChange={(e) => update(i, 'country', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
          <input placeholder="Trip type (Solo)" value={s.trip_type || ''} onChange={(e) => update(i, 'trip_type', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
          <input placeholder="Date (June 2025)" value={s.date || ''} onChange={(e) => update(i, 'date', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
          <textarea placeholder="Quote (30-60 words, edited only for brevity)" value={s.quote} onChange={(e) => update(i, 'quote', e.target.value)} className="col-span-2 px-3 py-1.5 border border-gray-300 rounded text-sm" rows={3} />
          <input placeholder="Source (Hostelworld)" value={s.source || ''} onChange={(e) => update(i, 'source', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
          <input placeholder="Rating (10/10)" value={s.rating || ''} onChange={(e) => update(i, 'rating', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
          <input placeholder="Photo URL (optional)" value={s.photo_url || ''} onChange={(e) => update(i, 'photo_url', e.target.value)} className="col-span-2 px-3 py-1.5 border border-gray-300 rounded text-sm" />
          <button onClick={() => patch('stories', stories.filter((_, idx) => idx !== i))} className="col-span-2 text-xs text-red-600 hover:underline text-left">Remove story</button>
        </div>
      ))}
      <button onClick={() => patch('stories', [...stories, { name: '', quote: '' }])} className="text-sm text-blue-600 hover:underline">+ Add story</button>
    </div>
  )
}

function OfferEditor({ content, patch }: EditorProps) {
  const rows = content.offer.comparison
  const update = (idx: number, field: any, val: string) => {
    patch('offer', { ...content.offer, comparison: rows.map((r, i) => i === idx ? { ...r, [field]: val } : r) })
  }
  return (
    <div>
      <p className="text-xs text-gray-500 mb-3">Playbook §8: at least 2 OTA-beating perks required. This is the module that earns the page its reason to exist.</p>
      <div className="space-y-2">
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[2fr_1fr_1fr_auto] gap-2">
            <input placeholder="Benefit (Free welcome drink)" value={r.benefit} onChange={(e) => update(i, 'benefit', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
            <input placeholder="OTA (—)" value={r.ota || ''} onChange={(e) => update(i, 'ota', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
            <input placeholder="Direct (Yes)" value={r.direct || ''} onChange={(e) => update(i, 'direct', e.target.value)} className="px-3 py-1.5 border border-gray-300 rounded text-sm" />
            <button onClick={() => patch('offer', { ...content.offer, comparison: rows.filter((_, idx) => idx !== i) })} className="text-xs text-red-600 hover:underline">Remove</button>
          </div>
        ))}
      </div>
      <button onClick={() => patch('offer', { ...content.offer, comparison: [...rows, { benefit: '', ota: '', direct: '' }] })} className="mt-3 text-sm text-blue-600 hover:underline">+ Add row</button>
    </div>
  )
}

function FAQEditor({ content, patch }: EditorProps) {
  const rows = content.faq
  return (
    <div className="space-y-3">
      {rows.map((r, i) => (
        <div key={i} className="border border-gray-200 rounded p-3 space-y-2">
          <input placeholder="Question" value={r.q} onChange={(e) => patch('faq', rows.map((x, idx) => idx === i ? { ...x, q: e.target.value } : x))} className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm font-medium" />
          <textarea placeholder="Answer (specific, no hedging)" value={r.a} onChange={(e) => patch('faq', rows.map((x, idx) => idx === i ? { ...x, a: e.target.value } : x))} className="w-full px-3 py-1.5 border border-gray-300 rounded text-sm" rows={2} />
          <button onClick={() => patch('faq', rows.filter((_, idx) => idx !== i))} className="text-xs text-red-600 hover:underline">Remove</button>
        </div>
      ))}
      <button onClick={() => patch('faq', [...rows, { q: '', a: '' }])} className="text-sm text-blue-600 hover:underline">+ Add FAQ</button>
    </div>
  )
}

function FinalCtaEditor({ content, patch }: EditorProps) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <Field label="Closing headline (callback to hero, 6-12 words)">
        <input value={content.final_cta.headline} onChange={(e) => patch('final_cta', { ...content.final_cta, headline: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
      </Field>
      <Field label="Urgency line (ONLY if true)">
        <input value={content.final_cta.urgency_line || ''} onChange={(e) => patch('final_cta', { ...content.final_cta, urgency_line: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="Only 2 dorm beds left this Friday" />
      </Field>
      <Field label="Primary CTA label (must match hero)">
        <input value={content.final_cta.cta_label} onChange={(e) => patch('final_cta', { ...content.final_cta, cta_label: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
      </Field>
      <Field label="Sub-CTA label (WhatsApp/Email)">
        <input value={content.final_cta.sub_cta_label || ''} onChange={(e) => patch('final_cta', { ...content.final_cta, sub_cta_label: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="WhatsApp the front desk" />
      </Field>
      <Field label="Sub-CTA href">
        <input value={content.final_cta.sub_cta_href || ''} onChange={(e) => patch('final_cta', { ...content.final_cta, sub_cta_href: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="https://wa.me/..." />
      </Field>
    </div>
  )
}

function ThemeSeoEditor({ content, patch }: EditorProps) {
  return (
    <div className="grid grid-cols-2 gap-6">
      <div>
        <h3 className="text-sm font-semibold mb-3">Theme</h3>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Primary (CTA) color">
            <input type="color" value={content.theme.primary_color} onChange={(e) => patch('theme', { ...content.theme, primary_color: e.target.value })} className="w-full h-9" />
          </Field>
          <Field label="Dark">
            <input type="color" value={content.theme.dark} onChange={(e) => patch('theme', { ...content.theme, dark: e.target.value })} className="w-full h-9" />
          </Field>
          <Field label="Light">
            <input type="color" value={content.theme.light} onChange={(e) => patch('theme', { ...content.theme, light: e.target.value })} className="w-full h-9" />
          </Field>
          <Field label="Trust blue">
            <input type="color" value={content.theme.trust_blue || '#6A9BCC'} onChange={(e) => patch('theme', { ...content.theme, trust_blue: e.target.value })} className="w-full h-9" />
          </Field>
          <Field label="Heading font">
            <input value={content.theme.font_heading} onChange={(e) => patch('theme', { ...content.theme, font_heading: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
          </Field>
          <Field label="Body font">
            <input value={content.theme.font_body} onChange={(e) => patch('theme', { ...content.theme, font_body: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
          </Field>
        </div>
      </div>
      <div>
        <h3 className="text-sm font-semibold mb-3">SEO</h3>
        <Field label="Page title (≤60 chars)">
          <input value={content.seo.title} onChange={(e) => patch('seo', { ...content.seo, title: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" maxLength={70} />
        </Field>
        <Field label="Meta description (≤160 chars)">
          <textarea value={content.seo.description} onChange={(e) => patch('seo', { ...content.seo, description: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" rows={3} maxLength={170} />
        </Field>
        <Field label="OG image URL (social preview)">
          <input value={content.seo.og_image || ''} onChange={(e) => patch('seo', { ...content.seo, og_image: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" />
        </Field>
      </div>
    </div>
  )
}
