'use client'

interface Props {
  url: string | null
  label: string | null
}

export default function WorkingFileLinkCard({ url, label }: Props) {
  if (!url) return null

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-2">Working File</h3>
      <p className="text-sm text-gray-600 mb-1">{label || 'Design File'}</p>
      <p className="text-xs text-gray-400 truncate mb-3">{url}</p>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-block bg-gray-100 text-gray-800 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-200"
      >
        Open Working File &rarr;
      </a>
      <p className="text-xs text-gray-400 mt-2">
        If you have feedback, please make changes directly on this file.
      </p>
    </div>
  )
}
