'use client'

interface Reviewer {
  id: string
  reviewer_id: string
  reviewer_name: string
  status: string
  decided_at: string | null
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

const STATUS_ICON: Record<string, string> = {
  APPROVED: '\u2705',
  REJECTED: '\u274C',
  PENDING: '\u23F3',
}

export default function ReviewerStatusList({ reviewers }: { reviewers: Reviewer[] }) {
  const approved = reviewers.filter(r => r.status === 'APPROVED').length

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3">Reviewers</h3>
      <div className="space-y-2">
        {reviewers.map(r => (
          <div key={r.id} className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span>{STATUS_ICON[r.status] || '\u23F3'}</span>
              <span className="text-gray-900">{r.reviewer_name}</span>
            </div>
            <div className="flex items-center gap-2 text-gray-500 text-xs">
              <span className={
                r.status === 'APPROVED' ? 'text-green-600' :
                r.status === 'REJECTED' ? 'text-red-600' :
                'text-amber-600'
              }>
                {r.status === 'PENDING' ? 'Pending' : r.status.charAt(0) + r.status.slice(1).toLowerCase()}
              </span>
              {r.decided_at && <span>{timeAgo(r.decided_at)}</span>}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 pt-3 border-t border-gray-100 text-xs text-gray-500">
        {approved} of {reviewers.length} approved
        {reviewers.some(r => r.status === 'PENDING') && ' \u2014 waiting for decision'}
      </div>
    </div>
  )
}
