'use client'

import { Suspense, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Sparkles, X } from 'lucide-react'
import { useAuth } from '@/components/AuthContext'
import { API_BASE } from '@/lib/api'
import type { LandingPage } from '@/lib/landingPage'

type ListResp = { items: LandingPage[]; total: number }

const STATUS_COLORS: Record<string, string> = {
  DRAFT: 'bg-gray-100 text-gray-700',
  PENDING_APPROVAL: 'bg-amber-100 text-amber-800',
  APPROVED: 'bg-emerald-100 text-emerald-800',
  PUBLISHED: 'bg-blue-100 text-blue-800',
  REJECTED: 'bg-red-100 text-red-700',
  DISCOVERED: 'bg-purple-100 text-purple-800',
  ARCHIVED: 'bg-gray-200 text-gray-500',
}

function LandingPagesListInner() {
  const { canEditSection } = useAuth()
  const canEdit = canEditSection('landing_pages')
  // Deep-link inputs from /funnel-recommendations cards: branches=Saigon&country=VN&range=7d
  const search0 = useSearchParams()
  const initialBranches = (search0?.get('branches') || '').split(',').map((s) => s.trim()).filter(Boolean)
  const initialCountry = (search0?.get('country') || '').toUpperCase()
  const initialSearch = initialBranches[0] || ''
  const [pages, setPages] = useState<LandingPage[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filterStatus, setFilterStatus] = useState<string>('')
  const [filterSource, setFilterSource] = useState<string>('')
  const [search, setSearch] = useState(initialSearch)
  const [importBusy, setImportBusy] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [recContext, setRecContext] = useState<{ branches: string[]; country: string } | null>(
    initialBranches.length > 0 || initialCountry
      ? { branches: initialBranches, country: initialCountry }
      : null,
  )

  const load = async () => {
    setLoading(true)
    setError(null)
    const params = new URLSearchParams({ limit: '200' })
    if (filterStatus) params.set('status', filterStatus)
    if (filterSource) params.set('source', filterSource)
    if (search) params.set('q', search)
    try {
      const res = await fetch(`${API_BASE}/api/landing-pages?${params}`, { credentials: 'include' })
      const j = await res.json()
      if (!j.success) {
        setError(j.error || 'Failed to load')
      } else {
        const data = j.data as ListResp
        setPages(data.items)
        setTotal(data.total)
      }
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStatus, filterSource])

  const runImport = async () => {
    if (!confirm('Scan all ads + Clarity data for new landing pages? This may take a minute.')) return
    setImportBusy(true)
    try {
      const res = await fetch(`${API_BASE}/api/landing-pages/import-from-ads`, {
        method: 'POST',
        credentials: 'include',
      })
      const j = await res.json()
      if (!j.success) {
        alert(`Import failed: ${j.error}`)
      } else {
        const s = j.data
        alert(
          `Import done:\n` +
          `  Meta ads scanned: ${s.meta_ads_scanned}\n` +
          `  Google asset groups: ${s.google_asset_groups_scanned}\n` +
          `  Clarity UTMs matched: ${s.clarity_utm?.campaigns_matched ?? 0}\n` +
          `  Pages created: ${s.pages_created}\n` +
          `  Ad-links created: ${s.ad_links_created + (s.clarity_utm?.ad_links_created ?? 0)}`
        )
        load()
      }
    } finally {
      setImportBusy(false)
    }
  }

  return (
    <div className="max-w-7xl mx-auto">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Landing Pages</h1>
          <p className="text-sm text-gray-500 mt-1">
            {total} pages — managed in CMS + discovered from ads & Clarity
          </p>
        </div>
        <div className="flex gap-2">
          {canEdit && (
            <button
              onClick={runImport}
              disabled={importBusy}
              className="px-3 py-2 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
              title="Scan all ads for destination URLs and auto-create external landing pages"
            >
              {importBusy ? 'Importing…' : 'Import from Ads'}
            </button>
          )}
          {canEdit && (
            <button
              onClick={() => setShowCreate(true)}
              className="px-3 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              + New Landing Page
            </button>
          )}
        </div>
      </div>

      {/* Recommendation context banner — shown when user opened from a
          Funnel Recommendation deep-link. Mirrors the slice they were looking
          at so they don't lose context when jumping pages. */}
      {recContext && (
        <div className="bg-indigo-50 border border-indigo-200 text-indigo-800 rounded-lg px-4 py-2 mb-4 flex items-center justify-between text-sm">
          <span className="flex items-center gap-2">
            <Sparkles className="w-4 h-4" />
            Opened from <strong>Click → Search</strong> bottleneck
            {recContext.branches.length > 0 && <> for <strong>{recContext.branches.join(', ')}</strong></>}
            {recContext.country && <> in <strong>{recContext.country}</strong></>}
            <span className="text-indigo-500">— review LP load + relevance for these pages.</span>
          </span>
          <button
            onClick={() => { setRecContext(null); setSearch('') }}
            className="text-indigo-500 hover:text-indigo-700"
            title="Clear recommendation context"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Filters */}
      <div className="bg-white rounded-lg border border-gray-200 p-4 mb-4 flex gap-3 flex-wrap">
        <input
          type="search"
          placeholder="Search title, domain, slug…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()}
          className="px-3 py-1.5 border border-gray-300 rounded text-sm flex-1 min-w-[240px]"
        />
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="px-3 py-1.5 border border-gray-300 rounded text-sm"
        >
          <option value="">All statuses</option>
          <option value="DRAFT">Draft</option>
          <option value="PENDING_APPROVAL">Pending Approval</option>
          <option value="APPROVED">Approved</option>
          <option value="PUBLISHED">Published</option>
          <option value="REJECTED">Rejected</option>
          <option value="DISCOVERED">Discovered</option>
        </select>
        <select
          value={filterSource}
          onChange={(e) => setFilterSource(e.target.value)}
          className="px-3 py-1.5 border border-gray-300 rounded text-sm"
        >
          <option value="">All sources</option>
          <option value="managed">Managed (CMS)</option>
          <option value="external">External (imported)</option>
        </select>
        <button
          onClick={load}
          className="px-3 py-1.5 bg-gray-100 text-gray-700 rounded text-sm hover:bg-gray-200"
        >
          Search
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded mb-4 text-sm">
          {error}
        </div>
      )}

      {loading && <div className="text-gray-500 text-sm">Loading…</div>}

      {!loading && pages.length === 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
          No landing pages yet. Click <strong>Import from Ads</strong> to discover existing
          ones, or <strong>+ New Landing Page</strong> to build one in the CMS.
        </div>
      )}

      {!loading && pages.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-2 text-left font-medium text-gray-700">Title</th>
                <th className="px-4 py-2 text-left font-medium text-gray-700">URL</th>
                <th className="px-4 py-2 text-left font-medium text-gray-700">Source</th>
                <th className="px-4 py-2 text-left font-medium text-gray-700">Status</th>
                <th className="px-4 py-2 text-left font-medium text-gray-700">Updated</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {pages.map((p) => (
                <tr key={p.id} className="border-b border-gray-100 hover:bg-gray-50">
                  <td className="px-4 py-2 font-medium text-gray-900">
                    <Link href={`/landing-pages/${p.id}`} className="hover:text-blue-700">
                      {p.title || `${p.domain}/${p.slug}`}
                    </Link>
                    {p.ta && <span className="ml-2 text-xs text-gray-500">{p.ta}</span>}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-gray-600">
                    <a href={p.public_url} target="_blank" rel="noreferrer" className="hover:underline">
                      {p.domain}/{p.slug}
                    </a>
                  </td>
                  <td className="px-4 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded ${p.source === 'managed' ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-600'}`}>
                      {p.source}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_COLORS[p.status] || 'bg-gray-100 text-gray-700'}`}>
                      {p.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-gray-500">
                    {new Date(p.updated_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-2 text-right">
                    <Link
                      href={`/landing-pages/${p.id}/performance`}
                      className="text-xs text-blue-600 hover:underline mr-3"
                    >
                      Analytics
                    </Link>
                    <Link
                      href={`/landing-pages/${p.id}`}
                      className="text-xs text-gray-600 hover:underline"
                    >
                      {p.source === 'managed' ? 'Edit' : 'Open'}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && <CreatePageModal onClose={() => setShowCreate(false)} onCreated={(id) => { setShowCreate(false); load(); window.location.href = `/landing-pages/${id}` }} />}
    </div>
  )
}

export default function LandingPagesList() {
  return (
    <Suspense fallback={<div className="p-6 text-gray-400">Loading...</div>}>
      <LandingPagesListInner />
    </Suspense>
  )
}

function CreatePageModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: string) => void }) {
  const [form, setForm] = useState({
    title: '',
    domain: '',
    slug: '',
    ta: '',
    language: 'en',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/api/landing-pages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          source: 'managed',
          title: form.title,
          domain: form.domain.toLowerCase(),
          slug: form.slug.replace(/^\/+|\/+$/g, ''),
          ta: form.ta || null,
          language: form.language,
        }),
      })
      const j = await res.json()
      if (!j.success) {
        setError(j.error || 'Create failed')
      } else {
        onCreated(j.data.id)
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl w-[520px] p-6">
        <h2 className="text-lg font-bold mb-4">New Landing Page</h2>
        <div className="space-y-3">
          <div>
            <label className="text-xs text-gray-600 block mb-1">Title (internal)</label>
            <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="Saigon — Couple traveler direct booking" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-600 block mb-1">Domain</label>
              <input value={form.domain} onChange={(e) => setForm({ ...form, domain: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="sgn.staymeander.com" />
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">Slug (path)</label>
              <input value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" placeholder="couple-traveler-direct" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-600 block mb-1">Target Audience</label>
              <select value={form.ta} onChange={(e) => setForm({ ...form, ta: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm">
                <option value="">—</option>
                <option value="Solo">Solo</option>
                <option value="Couple">Couple</option>
                <option value="Friend">Friend Group</option>
                <option value="Group">Group</option>
                <option value="Business">Business</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">Language</label>
              <select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })} className="w-full px-3 py-2 border border-gray-300 rounded text-sm">
                <option value="en">English</option>
                <option value="zh">繁體中文</option>
                <option value="vi">Tiếng Việt</option>
                <option value="ja">日本語</option>
              </select>
            </div>
          </div>
        </div>
        {error && <div className="text-sm text-red-600 mt-3">{error}</div>}
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded">Cancel</button>
          <button onClick={submit} disabled={!form.title || !form.domain || !form.slug || busy} className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">{busy ? 'Creating…' : 'Create'}</button>
        </div>
      </div>
    </div>
  )
}
