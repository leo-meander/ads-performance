'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { API_BASE } from '@/lib/api'

type InboxItem = {
  approval_id: string
  page_id: string
  page_title: string
  page_url: string
  version_id: string
  status: string
  my_decision: string
  submitted_at: string
  deadline: string | null
}

export default function LandingPageApprovals() {
  const [inbox, setInbox] = useState<InboxItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [decidingId, setDecidingId] = useState<string | null>(null)
  const [comment, setComment] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/landing-page-approvals/inbox`, { credentials: 'include' })
      const j = await res.json()
      if (!j.success) setError(j.error)
      else setInbox(j.data || [])
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const decide = async (approvalId: string, decision: 'APPROVED' | 'REJECTED') => {
    if (decision === 'REJECTED' && !comment.trim()) {
      alert('Please add a rejection reason — helps the creator iterate.')
      return
    }
    const res = await fetch(`${API_BASE}/api/landing-page-approvals/${approvalId}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ decision, comment: comment || null }),
    })
    const j = await res.json()
    if (!j.success) alert(`Failed: ${j.error}`)
    else {
      setDecidingId(null)
      setComment('')
      load()
    }
  }

  const pending = inbox.filter((i) => i.my_decision === 'PENDING')
  const decided = inbox.filter((i) => i.my_decision !== 'PENDING')

  return (
    <div className="max-w-6xl mx-auto">
      <div className="mb-6">
        <Link href="/landing-pages" className="text-xs text-gray-500 hover:underline">&larr; All landing pages</Link>
        <h1 className="text-2xl font-bold text-gray-900 mt-1">Landing Page Approvals</h1>
        <p className="text-sm text-gray-500">Review and approve submissions assigned to you.</p>
      </div>

      {error && <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-2 rounded mb-4 text-sm">{error}</div>}
      {loading && <div className="text-gray-500">Loading…</div>}

      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Pending your review ({pending.length})</h2>
        {pending.length === 0 ? (
          <p className="text-sm text-gray-500 bg-white border border-gray-200 rounded p-4">Nothing to review. Nice.</p>
        ) : (
          <div className="space-y-2">
            {pending.map((item) => (
              <div key={item.approval_id} className="bg-white border border-gray-200 rounded-lg p-4">
                <div className="flex items-start justify-between">
                  <div>
                    <Link href={`/landing-pages/${item.page_id}`} className="font-semibold text-gray-900 hover:text-blue-700">{item.page_title}</Link>
                    <p className="text-xs text-gray-500 font-mono mt-0.5">{item.page_url}</p>
                    <p className="text-xs text-gray-500 mt-1">
                      Submitted {new Date(item.submitted_at).toLocaleString()}
                      {item.deadline && ` · deadline ${new Date(item.deadline).toLocaleString()}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Link href={`/landing-pages/${item.page_id}`} className="text-xs text-blue-600 hover:underline">Open editor</Link>
                  </div>
                </div>
                {decidingId === item.approval_id ? (
                  <div className="mt-3">
                    <textarea value={comment} onChange={(e) => setComment(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded text-sm" rows={2} placeholder="Comment (required for rejection)" />
                    <div className="flex gap-2 mt-2">
                      <button onClick={() => decide(item.approval_id, 'APPROVED')} className="px-3 py-1.5 bg-emerald-600 text-white text-sm rounded hover:bg-emerald-700">Approve</button>
                      <button onClick={() => decide(item.approval_id, 'REJECTED')} className="px-3 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700">Reject</button>
                      <button onClick={() => { setDecidingId(null); setComment('') }} className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded">Cancel</button>
                    </div>
                  </div>
                ) : (
                  <button onClick={() => setDecidingId(item.approval_id)} className="mt-3 px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">Review</button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {decided.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Already decided ({decided.length})</h2>
          <div className="bg-white border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-gray-700">Page</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-700">My decision</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-700">Approval status</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-700">Submitted</th>
                </tr>
              </thead>
              <tbody>
                {decided.map((item) => (
                  <tr key={item.approval_id} className="border-b border-gray-100 hover:bg-gray-50">
                    <td className="px-4 py-2">
                      <Link href={`/landing-pages/${item.page_id}`} className="font-medium text-gray-900 hover:text-blue-700">{item.page_title}</Link>
                      <p className="text-xs text-gray-500 font-mono">{item.page_url}</p>
                    </td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded ${item.my_decision === 'APPROVED' ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-700'}`}>{item.my_decision}</span>
                    </td>
                    <td className="px-4 py-2">
                      <span className={`text-xs px-2 py-0.5 rounded ${item.status === 'APPROVED' ? 'bg-emerald-100 text-emerald-800' : item.status === 'REJECTED' ? 'bg-red-100 text-red-700' : item.status === 'PENDING_APPROVAL' ? 'bg-amber-100 text-amber-800' : 'bg-gray-100 text-gray-600'}`}>{item.status}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-gray-500">{new Date(item.submitted_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}
