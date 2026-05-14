'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, ExternalLink, RefreshCw } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Job {
  id: string
  template_id: string
  source_combo_id: string | null
  request_payload: Record<string, string>
  status: string
  output_figma_url: string | null
  output_image_url: string | null
  error: string | null
  requested_at: string | null
  completed_at: string | null
}

interface Template { id: string; name: string }

const STATUS_LIST = ['PENDING', 'RUNNING', 'COMPLETED', 'FAILED']
const STATUS_COLORS: Record<string, string> = {
  PENDING: 'bg-yellow-100 text-yellow-700',
  RUNNING: 'bg-blue-100 text-blue-700',
  COMPLETED: 'bg-green-100 text-green-700',
  FAILED: 'bg-red-100 text-red-700',
}

export default function FigmaJobsPage() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [templates, setTemplates] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [fStatus, setFStatus] = useState('')

  const load = () => {
    setLoading(true)
    const params = new URLSearchParams({ limit: '100' })
    if (fStatus) params.set('status', fStatus)
    fetch(`${API_BASE}/api/figma/jobs?${params}`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setJobs(d.data.items || []) })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/figma/templates`, { credentials: 'include' })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          setTemplates(Object.fromEntries((d.data.items || []).map((t: Template) => [t.id, t.name])))
        }
      })
  }, [])

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [fStatus])

  return (
    <div className="p-6 max-w-5xl">
      <Link href="/winning-ads" className="inline-flex items-center gap-1 text-sm text-blue-600 hover:underline mb-4">
        <ArrowLeft className="w-4 h-4" /> Back to Figma
      </Link>

      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Figma Render Jobs</h1>
          <p className="text-sm text-gray-500 mt-1">
            Jobs queued for the MEANDER Figma plugin. A designer runs the plugin to generate the frames.
          </p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 px-3 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      <div className="flex gap-3 mb-4 bg-white p-4 rounded-lg border border-gray-200">
        <select className="border border-gray-300 rounded px-3 py-2 text-sm" value={fStatus} onChange={e => setFStatus(e.target.value)}>
          <option value="">All statuses</option>
          {STATUS_LIST.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <div className="ml-auto text-xs text-gray-500 self-center">
          {loading ? 'Loading…' : `${jobs.length} job${jobs.length === 1 ? '' : 's'}`}
        </div>
      </div>

      <div className="space-y-2">
        {jobs.map(job => (
          <div key={job.id} className="bg-white border border-gray-200 rounded-lg p-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`text-xs px-2 py-0.5 rounded font-medium ${STATUS_COLORS[job.status] || 'bg-gray-100 text-gray-700'}`}>
                    {job.status}
                  </span>
                  <span className="font-medium text-gray-900">
                    {templates[job.template_id] || job.template_id}
                  </span>
                  <span className="text-xs text-gray-400 font-mono">{job.id.slice(0, 8)}</span>
                </div>
                <div className="text-xs text-gray-500 mt-1 break-words">
                  {Object.entries(job.request_payload || {}).map(([k, v]) => (
                    <span key={k} className="mr-3">
                      <span className="font-mono text-gray-400">{k}:</span> {String(v).slice(0, 50)}
                    </span>
                  ))}
                </div>
                {job.error && <p className="text-xs text-red-600 mt-1">{job.error}</p>}
                <div className="text-xs text-gray-400 mt-1">
                  {job.requested_at && `Queued ${new Date(job.requested_at).toLocaleString()}`}
                  {job.completed_at && ` · Done ${new Date(job.completed_at).toLocaleString()}`}
                </div>
              </div>
              <div className="flex flex-col gap-1.5 shrink-0">
                {job.output_figma_url && (
                  <a href={job.output_figma_url} target="_blank" rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50">
                    Open in Figma <ExternalLink className="w-3 h-3" />
                  </a>
                )}
                {job.output_image_url && (
                  <a href={job.output_image_url} target="_blank" rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs border border-gray-300 rounded hover:bg-gray-50">
                    View PNG <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>
            </div>
          </div>
        ))}
        {!loading && jobs.length === 0 && (
          <div className="bg-white border border-gray-200 rounded-lg p-12 text-center text-gray-500">
            No jobs{fStatus ? ` with status ${fStatus}` : ''}. Queue one from an AI Brief.
          </div>
        )}
      </div>
    </div>
  )
}
