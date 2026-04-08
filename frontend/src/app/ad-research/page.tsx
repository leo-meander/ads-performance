'use client'

import { useEffect, useRef, useState } from 'react'
import { Search, ExternalLink, Bookmark, BookmarkCheck, UserPlus, Plus, X, Trash2, Tag, Brain, ChevronRight, Eye } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface AdResult {
  ad_archive_id: string; page_id: string; page_name: string; bylines: string
  ad_creative_bodies: string[]; ad_creative_link_titles: string[]; ad_creative_link_captions: string[]
  ad_snapshot_url: string; publisher_platforms: string[]
  ad_delivery_start_time: string | null; ad_delivery_stop_time: string | null
  days_active: number; is_active: boolean
}

interface SavedAd extends AdResult {
  id: string; tags: string[]; notes: string | null; collection: string | null
  country: string | null; media_type: string | null; created_at: string; is_active_ad: boolean
}

interface TrackedPage {
  id: string; page_id: string; page_name: string; category: string | null
  country: string | null; notes: string | null; last_checked_at: string | null; created_at: string
}

interface Collection { name: string; count: number }
interface Report { id: string; title: string; analysis_type: string; input_ad_ids: string[]; model_used: string; created_at: string; has_result: boolean }
interface ReportDetail extends Report { result_markdown: string; input_params: any }

const COUNTRIES = [
  { code: 'ALL', label: 'All Countries' }, { code: 'VN', label: 'Vietnam' }, { code: 'TW', label: 'Taiwan' },
  { code: 'JP', label: 'Japan' }, { code: 'KR', label: 'South Korea' }, { code: 'SG', label: 'Singapore' },
  { code: 'TH', label: 'Thailand' }, { code: 'US', label: 'United States' }, { code: 'AU', label: 'Australia' },
]

const CATEGORIES = ['International Chain', 'OTA', 'Boutique Hotel', 'Local Competitor']

const QUICK_SEARCHES = [
  'boutique hotel', 'luxury hotel', 'hotel booking', 'hotel promotion', 'resort vacation',
  'hotel saigon', 'hotel taipei', 'hotel osaka', 'khach san', 'dat phong khach san',
  'travel deal', 'staycation', 'weekend getaway', 'hotel direct booking',
]

const PLATFORM_COLORS: Record<string, string> = {
  facebook: 'bg-blue-100 text-blue-700', instagram: 'bg-pink-100 text-pink-700',
  messenger: 'bg-purple-100 text-purple-700', audience_network: 'bg-gray-100 text-gray-600',
}

function DaysActiveBadge({ days, isActive }: { days: number; isActive: boolean }) {
  const color = days >= 30 ? 'bg-green-100 text-green-700' : days >= 7 ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${color}`}>
      {days}d {isActive && <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />}
    </span>
  )
}

function AdCard({ ad, savedIds, onSave, onTrackPage }: { ad: AdResult; savedIds: Set<string>; onSave: (ad: AdResult) => void; onTrackPage: (ad: AdResult) => void }) {
  const [expanded, setExpanded] = useState(false)
  const body = (ad.ad_creative_bodies || []).join(' ')
  const isSaved = savedIds.has(ad.ad_archive_id)

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 hover:shadow-sm transition">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-sm text-gray-900">{ad.page_name || 'Unknown Page'}</span>
            <DaysActiveBadge days={ad.days_active} isActive={ad.is_active} />
          </div>
          <div className="flex flex-wrap gap-1 mb-2">
            {(ad.publisher_platforms || []).map(p => (
              <span key={p} className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${PLATFORM_COLORS[p] || 'bg-gray-100 text-gray-600'}`}>
                {p === 'facebook' ? 'FB' : p === 'instagram' ? 'IG' : p === 'audience_network' ? 'AN' : p.toUpperCase()}
              </span>
            ))}
            {ad.ad_delivery_start_time && (
              <span className="text-[10px] text-gray-400">
                Started {new Date(ad.ad_delivery_start_time).toLocaleDateString()}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => onSave(ad)} title={isSaved ? 'Already saved' : 'Save ad'} className={`p-1.5 rounded-lg transition ${isSaved ? 'text-blue-600 bg-blue-50' : 'text-gray-400 hover:text-blue-600 hover:bg-blue-50'}`}>
            {isSaved ? <BookmarkCheck className="w-4 h-4" /> : <Bookmark className="w-4 h-4" />}
          </button>
          <button onClick={() => onTrackPage(ad)} title="Track this page" className="p-1.5 rounded-lg text-gray-400 hover:text-green-600 hover:bg-green-50 transition">
            <UserPlus className="w-4 h-4" />
          </button>
          {ad.ad_snapshot_url && (
            <a href={ad.ad_snapshot_url} target="_blank" rel="noopener noreferrer" title="View snapshot" className="p-1.5 rounded-lg text-gray-400 hover:text-purple-600 hover:bg-purple-50 transition">
              <ExternalLink className="w-4 h-4" />
            </a>
          )}
        </div>
      </div>

      {body && (
        <div className="mt-2">
          <p className={`text-sm text-gray-700 ${expanded ? '' : 'line-clamp-3'}`}>{body}</p>
          {body.length > 200 && (
            <button onClick={() => setExpanded(!expanded)} className="text-xs text-blue-600 mt-1">
              {expanded ? 'Show less' : 'Show more'}
            </button>
          )}
        </div>
      )}

      {(ad.ad_creative_link_titles || []).length > 0 && (
        <p className="text-xs text-gray-500 mt-1 truncate">
          {ad.ad_creative_link_titles[0]}
        </p>
      )}
    </div>
  )
}

export default function SpyAdsPage() {
  const [activeTab, setActiveTab] = useState<'search' | 'competitors' | 'saved' | 'analysis'>('search')

  // ── Search state ──
  const [searchQuery, setSearchQuery] = useState('')
  const [country, setCountry] = useState('ALL')
  const [activeStatus, setActiveStatus] = useState('ACTIVE')
  const [platform, setPlatform] = useState('ALL')
  const [mediaType, setMediaType] = useState('ALL')
  const [searchResults, setSearchResults] = useState<AdResult[]>([])
  const [pagingCursor, setPagingCursor] = useState<string | null>(null)
  const [isSearching, setIsSearching] = useState(false)
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set())

  // ── Competitors state ──
  const [trackedPages, setTrackedPages] = useState<TrackedPage[]>([])
  const [showAddModal, setShowAddModal] = useState(false)
  const [newPage, setNewPage] = useState({ page_id: '', page_name: '', category: 'Boutique Hotel', country: 'VN', notes: '' })
  const [competitorAds, setCompetitorAds] = useState<AdResult[]>([])
  const [viewingPage, setViewingPage] = useState<TrackedPage | null>(null)

  // ── Saved state ──
  const [savedAds, setSavedAds] = useState<SavedAd[]>([])
  const [savedTotal, setSavedTotal] = useState(0)
  const [collections, setCollections] = useState<Collection[]>([])
  const [filterCollection, setFilterCollection] = useState('')
  const [savedSortBy, setSavedSortBy] = useState('created_at')
  const [selectedSavedIds, setSelectedSavedIds] = useState<Set<string>>(new Set())

  // ── Analysis state ──
  const [reports, setReports] = useState<Report[]>([])
  const [selectedReport, setSelectedReport] = useState<ReportDetail | null>(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [streamingText, setStreamingText] = useState('')
  const [analysisType, setAnalysisType] = useState('pattern_analysis')
  const [showAnalyzeModal, setShowAnalyzeModal] = useState(false)
  const streamRef = useRef<HTMLDivElement>(null)

  // ── Load initial data ──
  useEffect(() => {
    loadTrackedPages()
    loadCollections()
    loadSavedAds()
    loadReports()
    // Load saved IDs for bookmarks
    fetch(`${API_BASE}/api/spy-ads/saved-ads?limit=200`).then(r => r.json()).then(d => {
      if (d.success) setSavedIds(new Set(d.data.items.map((a: SavedAd) => a.ad_archive_id)))
    }).catch(() => {})
  }, [])

  const loadTrackedPages = () => {
    fetch(`${API_BASE}/api/spy-ads/tracked-pages`).then(r => r.json()).then(d => {
      if (d.success) setTrackedPages(d.data)
    }).catch(() => {})
  }

  const loadCollections = () => {
    fetch(`${API_BASE}/api/spy-ads/saved-ads/collections`).then(r => r.json()).then(d => {
      if (d.success) setCollections(d.data)
    }).catch(() => {})
  }

  const loadSavedAds = (collection?: string, sortBy?: string) => {
    const params = new URLSearchParams({ limit: '100', sort_by: sortBy || savedSortBy, sort_dir: 'desc' })
    if (collection) params.set('collection', collection)
    fetch(`${API_BASE}/api/spy-ads/saved-ads?${params}`).then(r => r.json()).then(d => {
      if (d.success) { setSavedAds(d.data.items); setSavedTotal(d.data.total) }
    }).catch(() => {})
  }

  const loadReports = () => {
    fetch(`${API_BASE}/api/spy-ads/reports`).then(r => r.json()).then(d => {
      if (d.success) setReports(d.data.items)
    }).catch(() => {})
  }

  // ── Search functions ──
  const doSearch = (query?: string, append = false) => {
    const q = query ?? searchQuery
    if (!q.trim() && !platform) return
    setIsSearching(true)
    const params = new URLSearchParams({
      q, country, active_status: activeStatus, platform, media_type: mediaType, limit: '25',
    })
    if (append && pagingCursor) params.set('after', pagingCursor)

    fetch(`${API_BASE}/api/spy-ads/search?${params}`).then(r => r.json()).then(d => {
      if (d.success) {
        if (append) setSearchResults(prev => [...prev, ...d.data.ads])
        else setSearchResults(d.data.ads)
        setPagingCursor(d.data.paging?.after || null)
      }
    }).catch(() => {}).finally(() => setIsSearching(false))
  }

  const handleSaveAd = (ad: AdResult) => {
    fetch(`${API_BASE}/api/spy-ads/saved-ads`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...ad, country }),
    }).then(r => r.json()).then(d => {
      if (d.success) {
        setSavedIds(prev => new Set([...prev, ad.ad_archive_id]))
        loadCollections()
      }
    }).catch(() => {})
  }

  const handleTrackPage = (ad: AdResult) => {
    fetch(`${API_BASE}/api/spy-ads/tracked-pages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_id: ad.page_id, page_name: ad.page_name, category: 'Boutique Hotel', country }),
    }).then(r => r.json()).then(d => {
      if (d.success) loadTrackedPages()
    }).catch(() => {})
  }

  // ── Competitor functions ──
  const addTrackedPage = () => {
    fetch(`${API_BASE}/api/spy-ads/tracked-pages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newPage),
    }).then(r => r.json()).then(d => {
      if (d.success) {
        loadTrackedPages()
        setShowAddModal(false)
        setNewPage({ page_id: '', page_name: '', category: 'Boutique Hotel', country: 'VN', notes: '' })
      }
    }).catch(() => {})
  }

  const removeTrackedPage = (id: string) => {
    fetch(`${API_BASE}/api/spy-ads/tracked-pages/${id}`, { method: 'DELETE' })
      .then(r => r.json()).then(d => { if (d.success) loadTrackedPages() }).catch(() => {})
  }

  const viewPageAds = (page: TrackedPage) => {
    setViewingPage(page)
    setCompetitorAds([])
    fetch(`${API_BASE}/api/spy-ads/tracked-pages/${page.id}/ads?limit=25`)
      .then(r => r.json()).then(d => { if (d.success) setCompetitorAds(d.data.ads) }).catch(() => {})
  }

  // ── Saved ads functions ──
  const deleteSavedAd = (id: string) => {
    fetch(`${API_BASE}/api/spy-ads/saved-ads/${id}`, { method: 'DELETE' })
      .then(r => r.json()).then(d => {
        if (d.success) loadSavedAds(filterCollection)
      }).catch(() => {})
  }

  const toggleSelectSaved = (id: string) => {
    setSelectedSavedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // ── Analysis functions ──
  const runAnalysis = () => {
    const ids = [...selectedSavedIds]
    if (ids.length === 0) return
    setIsAnalyzing(true)
    setStreamingText('')
    setShowAnalyzeModal(false)

    fetch(`${API_BASE}/api/spy-ads/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ad_ids: ids, analysis_type: analysisType }),
    }).then(async resp => {
      const reader = resp.body?.getReader()
      if (!reader) return
      const decoder = new TextDecoder()
      let result = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        result += decoder.decode(value, { stream: true })
        setStreamingText(result)
        streamRef.current?.scrollTo(0, streamRef.current.scrollHeight)
      }
    }).catch(() => {}).finally(() => {
      setIsAnalyzing(false)
      loadReports()
    })
  }

  const viewReport = (id: string) => {
    fetch(`${API_BASE}/api/spy-ads/reports/${id}`).then(r => r.json()).then(d => {
      if (d.success) setSelectedReport(d.data)
    }).catch(() => {})
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Spy Ads</h1>
          <p className="text-sm text-gray-500 mt-1">Research & analyze competitor Meta Ads</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-100 rounded-lg p-1 w-fit">
        {[
          { key: 'search' as const, label: 'Search' },
          { key: 'competitors' as const, label: `Competitors (${trackedPages.length})` },
          { key: 'saved' as const, label: `Saved (${savedTotal})` },
          { key: 'analysis' as const, label: `Analysis (${reports.length})` },
        ].map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)} className={`px-4 py-2 rounded-md text-sm font-medium transition ${activeTab === t.key ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ═══ SEARCH TAB ═══ */}
      {activeTab === 'search' && (
        <div className="space-y-4">
          {/* Search bar + filters */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="flex gap-2 mb-3">
              <div className="flex-1 relative">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                <input type="text" value={searchQuery} onChange={e => setSearchQuery(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && doSearch()}
                  placeholder="Search keywords or advertiser name..."
                  className="w-full pl-10 pr-4 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <button onClick={() => doSearch()} disabled={isSearching}
                className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition disabled:opacity-50">
                {isSearching ? 'Searching...' : 'Search'}
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              <select value={country} onChange={e => setCountry(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-xs">
                {COUNTRIES.map(c => <option key={c.code} value={c.code}>{c.label}</option>)}
              </select>
              <select value={activeStatus} onChange={e => setActiveStatus(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-xs">
                <option value="ACTIVE">Active Only</option>
                <option value="INACTIVE">Inactive Only</option>
                <option value="ALL">All Status</option>
              </select>
              <select value={platform} onChange={e => setPlatform(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-xs">
                <option value="ALL">All Platforms</option>
                <option value="FACEBOOK">Facebook</option>
                <option value="INSTAGRAM">Instagram</option>
              </select>
              <select value={mediaType} onChange={e => setMediaType(e.target.value)} className="px-3 py-1.5 border border-gray-200 rounded-lg text-xs">
                <option value="ALL">All Media</option>
                <option value="IMAGE">Image</option>
                <option value="VIDEO">Video</option>
                <option value="MIXIN">Carousel</option>
              </select>
            </div>
          </div>

          {/* Quick searches */}
          <div className="flex flex-wrap gap-1.5">
            {QUICK_SEARCHES.map(q => (
              <button key={q} onClick={() => { setSearchQuery(q); doSearch(q) }}
                className="px-3 py-1 bg-white hover:bg-blue-50 hover:text-blue-700 border border-gray-200 rounded-full text-xs text-gray-600 transition">
                {q}
              </button>
            ))}
          </div>

          {/* Results */}
          {searchResults.length > 0 && (
            <div className="space-y-3">
              <p className="text-xs text-gray-400">{searchResults.length} results {pagingCursor ? '(more available)' : ''}</p>
              {searchResults.map(ad => (
                <AdCard key={ad.ad_archive_id} ad={ad} savedIds={savedIds} onSave={handleSaveAd} onTrackPage={handleTrackPage} />
              ))}
              {pagingCursor && (
                <button onClick={() => doSearch(undefined, true)} disabled={isSearching}
                  className="w-full py-3 bg-white border border-gray-200 rounded-xl text-sm text-gray-600 hover:bg-gray-50 transition disabled:opacity-50">
                  {isSearching ? 'Loading...' : 'Load More'}
                </button>
              )}
            </div>
          )}

          {!isSearching && searchResults.length === 0 && searchQuery && (
            <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
              No results. Try different keywords or filters.
            </div>
          )}

          {/* Tips */}
          {searchResults.length === 0 && !searchQuery && (
            <div className="bg-blue-50 rounded-xl border border-blue-100 p-5">
              <h3 className="text-sm font-semibold text-blue-900 mb-2">Research Tips</h3>
              <ul className="text-xs text-blue-800 space-y-1">
                <li>- Ads running 30+ days are likely profitable (green badge)</li>
                <li>- Search competitor brand names to see their strategy</li>
                <li>- Save interesting ads and run AI analysis to find patterns</li>
                <li>- Track competitor pages to monitor their new ads</li>
              </ul>
            </div>
          )}
        </div>
      )}

      {/* ═══ COMPETITORS TAB ═══ */}
      {activeTab === 'competitors' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-500">Track competitor pages to monitor their Meta Ads.</p>
            <button onClick={() => setShowAddModal(true)} className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 transition">
              <Plus className="w-4 h-4" /> Add Competitor
            </button>
          </div>

          {/* Add modal */}
          {showAddModal && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-900">Add Competitor Page</h3>
                <button onClick={() => setShowAddModal(false)} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <input placeholder="Meta Page ID" value={newPage.page_id} onChange={e => setNewPage({ ...newPage, page_id: e.target.value })} className="px-3 py-2 border border-gray-200 rounded-lg text-sm" />
                <input placeholder="Page Name" value={newPage.page_name} onChange={e => setNewPage({ ...newPage, page_name: e.target.value })} className="px-3 py-2 border border-gray-200 rounded-lg text-sm" />
                <select value={newPage.category} onChange={e => setNewPage({ ...newPage, category: e.target.value })} className="px-3 py-2 border border-gray-200 rounded-lg text-sm">
                  {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <select value={newPage.country} onChange={e => setNewPage({ ...newPage, country: e.target.value })} className="px-3 py-2 border border-gray-200 rounded-lg text-sm">
                  {COUNTRIES.filter(c => c.code !== 'ALL').map(c => <option key={c.code} value={c.code}>{c.label}</option>)}
                </select>
              </div>
              <textarea placeholder="Notes (optional)" value={newPage.notes} onChange={e => setNewPage({ ...newPage, notes: e.target.value })} className="w-full mt-3 px-3 py-2 border border-gray-200 rounded-lg text-sm" rows={2} />
              <button onClick={addTrackedPage} className="mt-3 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">Save</button>
            </div>
          )}

          {/* Competitor cards by category */}
          {CATEGORIES.filter(cat => trackedPages.some(p => p.category === cat)).map(category => (
            <div key={category}>
              <h3 className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold mb-2">{category}</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mb-4">
                {trackedPages.filter(p => p.category === category).map(page => (
                  <div key={page.id} className="bg-white rounded-xl border border-gray-200 p-4 group">
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-sm font-medium text-gray-900">{page.page_name}</p>
                      <button onClick={() => removeTrackedPage(page.id)} className="opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-500 transition">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-gray-400 mb-3">
                      <span>{page.country || '—'}</span>
                      <span>ID: {page.page_id}</span>
                      {page.last_checked_at && <span>Checked: {new Date(page.last_checked_at).toLocaleDateString()}</span>}
                    </div>
                    <button onClick={() => viewPageAds(page)} className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700 font-medium">
                      <Eye className="w-3.5 h-3.5" /> View Ads
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}

          {trackedPages.length === 0 && !showAddModal && (
            <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
              No competitors tracked yet. Click "Add Competitor" to start.
            </div>
          )}

          {/* Competitor Ads Viewer */}
          {viewingPage && (
            <div className="bg-white rounded-xl border border-gray-200 p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-900">Ads from {viewingPage.page_name}</h3>
                <button onClick={() => { setViewingPage(null); setCompetitorAds([]) }} className="text-gray-400 hover:text-gray-600"><X className="w-4 h-4" /></button>
              </div>
              {competitorAds.length === 0 ? (
                <p className="text-sm text-gray-400 py-4 text-center">Loading ads...</p>
              ) : (
                <div className="space-y-3">
                  {competitorAds.map(ad => (
                    <AdCard key={ad.ad_archive_id} ad={ad} savedIds={savedIds} onSave={handleSaveAd} onTrackPage={() => {}} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ═══ SAVED ADS TAB ═══ */}
      {activeTab === 'saved' && (
        <div className="flex gap-4">
          {/* Collections sidebar */}
          <div className="w-48 flex-shrink-0">
            <h3 className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold mb-2">Collections</h3>
            <div className="space-y-0.5">
              <button onClick={() => { setFilterCollection(''); loadSavedAds('') }}
                className={`w-full text-left px-3 py-1.5 rounded-lg text-sm ${!filterCollection ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-600 hover:bg-gray-100'}`}>
                All ({savedTotal})
              </button>
              {collections.map(c => (
                <button key={c.name} onClick={() => { setFilterCollection(c.name); loadSavedAds(c.name) }}
                  className={`w-full text-left px-3 py-1.5 rounded-lg text-sm ${filterCollection === c.name ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-600 hover:bg-gray-100'}`}>
                  {c.name} ({c.count})
                </button>
              ))}
            </div>

            {/* Sort */}
            <h3 className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold mt-4 mb-2">Sort By</h3>
            <div className="space-y-0.5">
              {[
                { key: 'created_at', label: 'Date Saved' },
                { key: 'ad_delivery_start_time', label: 'Start Date' },
              ].map(s => (
                <button key={s.key} onClick={() => { setSavedSortBy(s.key); loadSavedAds(filterCollection, s.key) }}
                  className={`w-full text-left px-3 py-1.5 rounded-lg text-sm ${savedSortBy === s.key ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-600 hover:bg-gray-100'}`}>
                  {s.label}
                </button>
              ))}
            </div>

            {/* Bulk actions */}
            {selectedSavedIds.size > 0 && (
              <div className="mt-4 space-y-1">
                <p className="text-[10px] text-gray-400">{selectedSavedIds.size} selected</p>
                <button onClick={() => { setActiveTab('analysis'); setShowAnalyzeModal(true) }}
                  className="w-full flex items-center gap-1 px-3 py-1.5 bg-purple-50 text-purple-700 rounded-lg text-xs font-medium hover:bg-purple-100">
                  <Brain className="w-3.5 h-3.5" /> Analyze
                </button>
              </div>
            )}
          </div>

          {/* Saved ads list */}
          <div className="flex-1 space-y-3">
            {savedAds.length === 0 ? (
              <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
                No saved ads yet. Search and save ads to build your collection.
              </div>
            ) : (
              savedAds.map(ad => (
                <div key={ad.id} className="bg-white rounded-xl border border-gray-200 p-4">
                  <div className="flex items-start gap-3">
                    <input type="checkbox" checked={selectedSavedIds.has(ad.id)} onChange={() => toggleSelectSaved(ad.id)} className="mt-1 w-4 h-4 rounded" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-sm text-gray-900">{ad.page_name || 'Unknown'}</span>
                        <DaysActiveBadge days={ad.days_active} isActive={ad.is_active_ad} />
                        {(ad.publisher_platforms || []).map(p => (
                          <span key={p} className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${PLATFORM_COLORS[p] || 'bg-gray-100'}`}>
                            {p === 'facebook' ? 'FB' : p === 'instagram' ? 'IG' : p}
                          </span>
                        ))}
                      </div>
                      <p className="text-sm text-gray-700 line-clamp-2">{(ad.ad_creative_bodies || []).join(' ') || 'No body text'}</p>
                      <div className="flex items-center gap-2 mt-2">
                        {(ad.tags || []).map(t => (
                          <span key={t} className="px-2 py-0.5 bg-gray-100 rounded-full text-[10px] text-gray-600">{t}</span>
                        ))}
                        {ad.collection && <span className="px-2 py-0.5 bg-blue-50 rounded-full text-[10px] text-blue-600">{ad.collection}</span>}
                        <span className="text-[10px] text-gray-400">Saved {new Date(ad.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      {ad.ad_snapshot_url && (
                        <a href={ad.ad_snapshot_url} target="_blank" rel="noopener noreferrer" className="p-1.5 rounded-lg text-gray-400 hover:text-purple-600 hover:bg-purple-50">
                          <ExternalLink className="w-4 h-4" />
                        </a>
                      )}
                      <button onClick={() => deleteSavedAd(ad.id)} className="p-1.5 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50">
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* ═══ ANALYSIS TAB ═══ */}
      {activeTab === 'analysis' && (
        <div className="flex gap-4">
          {/* Reports sidebar */}
          <div className="w-64 flex-shrink-0">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-[10px] uppercase tracking-wider text-gray-400 font-semibold">Reports</h3>
              <button onClick={() => setShowAnalyzeModal(true)} className="flex items-center gap-1 px-3 py-1.5 bg-purple-600 text-white rounded-lg text-xs font-medium hover:bg-purple-700">
                <Plus className="w-3.5 h-3.5" /> New
              </button>
            </div>
            <div className="space-y-1">
              {reports.map(r => (
                <button key={r.id} onClick={() => viewReport(r.id)}
                  className={`w-full text-left px-3 py-2 rounded-lg transition ${selectedReport?.id === r.id ? 'bg-purple-50 text-purple-700' : 'hover:bg-gray-100 text-gray-600'}`}>
                  <p className="text-sm font-medium truncate">{r.title}</p>
                  <p className="text-[10px] text-gray-400">{new Date(r.created_at).toLocaleDateString()} - {r.input_ad_ids.length} ads</p>
                </button>
              ))}
              {reports.length === 0 && <p className="text-xs text-gray-400 px-3 py-2">No reports yet.</p>}
            </div>
          </div>

          {/* Report content */}
          <div className="flex-1">
            {/* New analysis modal */}
            {showAnalyzeModal && (
              <div className="bg-white rounded-xl border border-gray-200 p-6 mb-4">
                <h3 className="text-sm font-semibold text-gray-900 mb-3">New Analysis</h3>
                <p className="text-xs text-gray-500 mb-3">
                  {selectedSavedIds.size > 0
                    ? `${selectedSavedIds.size} ads selected from Saved tab.`
                    : 'Go to the Saved tab and select ads first, then come back here.'}
                </p>
                <div className="space-y-2 mb-4">
                  {[
                    { key: 'pattern_analysis', label: 'Pattern Analysis', desc: 'Find common patterns in hooks, CTAs, copy, and creative formats' },
                    { key: 'competitor_deep_dive', label: 'Competitor Deep Dive', desc: 'Analyze a competitor\'s full ad strategy and positioning' },
                    { key: 'creative_trends', label: 'Creative Trends', desc: 'Identify trending formats, styles, and messaging approaches' },
                  ].map(t => (
                    <label key={t.key} className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition ${analysisType === t.key ? 'border-purple-300 bg-purple-50' : 'border-gray-200 hover:bg-gray-50'}`}>
                      <input type="radio" name="analysisType" value={t.key} checked={analysisType === t.key} onChange={() => setAnalysisType(t.key)} className="mt-0.5" />
                      <div>
                        <p className="text-sm font-medium text-gray-900">{t.label}</p>
                        <p className="text-xs text-gray-500">{t.desc}</p>
                      </div>
                    </label>
                  ))}
                </div>
                <div className="flex gap-2">
                  <button onClick={runAnalysis} disabled={selectedSavedIds.size === 0 || isAnalyzing}
                    className="px-4 py-2 bg-purple-600 text-white rounded-lg text-sm font-medium hover:bg-purple-700 disabled:opacity-50">
                    {isAnalyzing ? 'Analyzing...' : 'Run Analysis'}
                  </button>
                  <button onClick={() => setShowAnalyzeModal(false)} className="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Streaming output */}
            {(isAnalyzing || streamingText) && (
              <div ref={streamRef} className="bg-white rounded-xl border border-gray-200 p-6 max-h-[600px] overflow-auto">
                {isAnalyzing && <p className="text-xs text-purple-500 mb-3 animate-pulse">AI is analyzing...</p>}
                <div className="prose prose-sm max-w-none text-gray-800 whitespace-pre-wrap">{streamingText}</div>
              </div>
            )}

            {/* Selected report */}
            {selectedReport && !isAnalyzing && !streamingText && (
              <div className="bg-white rounded-xl border border-gray-200 p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-1">{selectedReport.title}</h2>
                <p className="text-xs text-gray-400 mb-4">
                  {new Date(selectedReport.created_at).toLocaleString()} - {selectedReport.input_ad_ids.length} ads - {selectedReport.model_used}
                </p>
                <div className="prose prose-sm max-w-none text-gray-800 whitespace-pre-wrap">
                  {selectedReport.result_markdown || 'No content.'}
                </div>
              </div>
            )}

            {!selectedReport && !isAnalyzing && !streamingText && !showAnalyzeModal && (
              <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
                <Brain className="w-8 h-8 mx-auto mb-2 text-gray-300" />
                <p>Select a report or create a new analysis.</p>
                <p className="text-xs mt-1">Save ads first, then select them to analyze patterns.</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
