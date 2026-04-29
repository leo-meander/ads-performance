'use client'

const STATUS_CONFIG: Record<string, { color: string; bg: string; label: string }> = {
  DRAFT: { color: 'text-gray-700', bg: 'bg-gray-100', label: 'Draft' },
  PENDING_APPROVAL: { color: 'text-amber-700', bg: 'bg-amber-100', label: 'Pending Review' },
  APPROVED: { color: 'text-green-700', bg: 'bg-green-100', label: 'Approved' },
  NEEDS_REVISION: { color: 'text-orange-700', bg: 'bg-orange-100', label: 'Needs Revision' },
  REJECTED: { color: 'text-red-700', bg: 'bg-red-100', label: 'Rejected' },
  LAUNCHED: { color: 'text-blue-700', bg: 'bg-blue-100', label: 'Launched' },
  LAUNCH_FAILED: { color: 'text-red-800', bg: 'bg-red-200', label: 'Launch Failed' },
}

export default function ApprovalStatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] || { color: 'text-gray-700', bg: 'bg-gray-100', label: status }
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${config.color} ${config.bg}`}>
      {config.label}
    </span>
  )
}
