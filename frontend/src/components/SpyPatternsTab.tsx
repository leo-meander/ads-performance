'use client'

import { useCallback, useEffect, useState } from 'react'
import { Brain, Sparkles } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Pattern {
  angle: string
  label: string
  ad_count: number
  share: number
  competitor_count: number
  competitors: string[]
  avg_days_running: number
  max_days_running: number
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
}

interface Tally {
  total_ads: number
  min_days_running: number
  patterns: Pattern[]
  formats: { name: string; count: number }[]
  ctas: { name: string; count: number }[]
  competitors: { name: string; count: number }[]
  sample_hooks: { hook: string; advertiser: string; days_running: number; angle: string }[]
}

const CONFIDENCE_TONE: Record<string, string> = {
  HIGH: 'bg-emerald-100 text-emerald-800',
  MEDIUM: 'bg-amber-100 text-amber-800',
  LOW: 'bg-gray-100 text-gray-600',
}

function PatternBar({ pattern, max }: { pattern: Pattern; max: number }) {
  // Bars are scaled against the top pattern, not against the total, so the
  // shape of the distribution stays readable when one angle dominates.
  const width = max > 0 ? Math.max(4, Math.round((pattern.ad_count / max) * 100)) : 0
  return (
    <div className="py-2.5 border-b border-gray-100 last:border-0">
      <div className="flex items-center justify-between gap-3 mb-1.5">
        <span className="text-sm font-medium text-gray-900">{pattern.label}</span>
        <div className="flex items-center gap-2 shrink-0">
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${CONFIDENCE_TONE[pattern.confidence]}`}>
            {pattern.confidence}
          </span>
          <span className="text-xs text-gray-500 tabular-nums w-12 text-right">
            {Math.round(pattern.share * 100)}%
          </span>
        </div>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className="h-full bg-blue-500 rounded-full" style={{ width: `${width}%` }} />
      </div>
      <p className="text-[10px] text-gray-400 mt-1.5">
        {pattern.ad_count} ad{pattern.ad_count === 1 ? '' : 's'} across {pattern.competitor_count}{' '}
        competitor{pattern.competitor_count === 1 ? '' : 's'} · avg {pattern.avg_days_running}d running ·
        longest {pattern.max_days_running}d
      </p>
    </div>
  )
}

export default function SpyPatternsTab({ longRunningDays }: { longRunningDays: number }) {
  const [tally, setTally] = useState<Tally | null>(null)
  const [minDays, setMinDays] = useState(longRunningDays)
  const [digest, setDigest] = useState<string | null>(null)
  const [building, setBuilding] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    fetch(`${API_BASE}/api/spy-ads/patterns?min_days=${minDays}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) setTally(d.data)
        else setError(d.error)
      })
      .catch(() => setError('Could not reach the server.'))
  }, [minDays])

  useEffect(() => { load() }, [load])

  const buildDigest = () => {
    setBuilding(true)
    setError(null)
    fetch(`${API_BASE}/api/spy-ads/patterns/digest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ min_days_running: minDays }),
    })
      .then(r => r.json())
      .then(d => {
        if (d.success) setDigest(d.data.markdown)
        else setError(d.error || 'Could not build the digest.')
      })
      .catch(() => setError('Could not reach the server.'))
      .finally(() => setBuilding(false))
  }

  const maxCount = tally?.patterns[0]?.ad_count ?? 0

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-wrap items-center gap-3">
        <div>
          <p className="text-sm font-semibold text-gray-900">What competitors keep running</p>
          <p className="text-xs text-gray-500 mt-0.5">
            Counted from ads that survived {minDays}+ days and have an AI breakdown.
          </p>
        </div>
        <div className="flex-1" />
        <select
          value={minDays}
          onChange={e => setMinDays(Number(e.target.value))}
          className="px-3 py-1.5 border border-gray-200 rounded-lg text-xs"
        >
          {[7, 14, 30, 45, 60, 90].map(d => <option key={d} value={d}>{d}+ days</option>)}
        </select>
        <button
          onClick={buildDigest}
          disabled={building || !tally?.total_ads}
          className="inline-flex items-center gap-1.5 px-4 py-2 bg-purple-600 text-white rounded-lg text-sm font-medium hover:bg-purple-700 transition disabled:opacity-50"
        >
          <Sparkles className="w-3.5 h-3.5" />
          {building ? 'Thinking...' : 'Build recommendation'}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">{error}</div>
      )}

      {tally && tally.total_ads === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">
          <Brain className="w-8 h-8 mx-auto mb-2 text-gray-300" />
          <p>No ads have been broken down at this duration yet.</p>
          <p className="text-xs mt-1">
            Run a crawl, then &quot;Break down&quot; on the Radar tab. Patterns are counted from
            structured breakdowns, not guessed from raw copy.
          </p>
        </div>
      ) : tally ? (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-5">
              <div className="flex items-baseline justify-between mb-2">
                <h3 className="text-sm font-semibold text-gray-900">Angles</h3>
                <span className="text-xs text-gray-400">{tally.total_ads} ads analyzed</span>
              </div>
              {tally.patterns.map(p => <PatternBar key={p.angle} pattern={p} max={maxCount} />)}
            </div>

            <div className="space-y-4">
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="text-sm font-semibold text-gray-900 mb-2">Formats</h3>
                {tally.formats.map(f => (
                  <div key={f.name} className="flex justify-between text-xs py-1 text-gray-600">
                    <span className="capitalize">{f.name}</span>
                    <span className="tabular-nums">{f.count}</span>
                  </div>
                ))}
              </div>
              <div className="bg-white rounded-xl border border-gray-200 p-5">
                <h3 className="text-sm font-semibold text-gray-900 mb-2">CTAs</h3>
                {tally.ctas.map(c => (
                  <div key={c.name} className="flex justify-between text-xs py-1 text-gray-600">
                    <span className="truncate pr-2">{c.name}</span>
                    <span className="tabular-nums shrink-0">{c.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {tally.sample_hooks.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-gray-900 mb-3">Longest-surviving hooks</h3>
              <div className="space-y-2">
                {tally.sample_hooks.map((h, i) => (
                  <div key={i} className="flex items-start gap-3 text-sm">
                    <span className="shrink-0 px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 text-xs font-semibold tabular-nums">
                      {h.days_running}d
                    </span>
                    <div className="min-w-0">
                      <p className="text-gray-800">{h.hook}</p>
                      <p className="text-[10px] text-gray-400">
                        {h.advertiser}{h.angle ? ` · ${h.angle}` : ''}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {digest && (
            <div className="bg-white rounded-xl border border-purple-200 p-6">
              <h3 className="text-sm font-semibold text-purple-900 mb-3 flex items-center gap-1.5">
                <Sparkles className="w-4 h-4" /> Recommendation for MEANDER
              </h3>
              <div className="prose prose-sm max-w-none text-gray-800 whitespace-pre-wrap">{digest}</div>
            </div>
          )}
        </>
      ) : null}
    </div>
  )
}
