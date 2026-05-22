'use client'

import { useEffect, useMemo, useState } from 'react'
import { ALL_BRANCHES, ALL_SECTIONS, Level, Permission } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

type CellValue = 'none' | Level

interface AvailablePage {
  page: string
  section: string
  label: string
}

const SECTION_LABELS: Record<string, string> = {
  analytics: 'Analytics',
  meta_ads: 'Meta Ads',
  google_ads: 'Google Ads',
  budget: 'Budget',
  automation: 'Automation',
  ai: 'AI',
  settings: 'Settings',
}

const LEVEL_CYCLE: Record<CellValue, CellValue> = {
  none: 'view',
  view: 'edit',
  edit: 'none',
}

const LEVEL_STYLES: Record<CellValue, string> = {
  none: 'bg-gray-50 text-gray-400 border-gray-200 hover:bg-gray-100',
  view: 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100',
  edit: 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100',
}

const LEVEL_SYMBOLS: Record<CellValue, string> = {
  none: '—',
  view: 'View',
  edit: 'Edit',
}

interface PermissionMatrixProps {
  userId: string
  userEmail: string
  onClose: () => void
  onSaved?: () => void
}

export default function PermissionMatrix({ userId, userEmail, onClose, onSaved }: PermissionMatrixProps) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)
  // Matrix: branch -> section -> level
  const [matrix, setMatrix] = useState<Record<string, Record<string, CellValue>>>(() =>
    buildEmptyMatrix(),
  )
  // Page access: list of {page, section, label} from the API + page -> level.
  // 'none' on a page means "inherit" (no restriction). Setting any page in a
  // section to view/edit restricts the user to only the set pages of it.
  const [availablePages, setAvailablePages] = useState<AvailablePage[]>([])
  const [pageMatrix, setPageMatrix] = useState<Record<string, CellValue>>({})

  useEffect(() => {
    ;(async () => {
      setLoading(true)
      setError('')
      try {
        const res = await fetch(`${API_BASE}/api/users/${userId}/permissions`, {
          credentials: 'include',
        })
        const data = await res.json()
        if (!data.success) {
          setError(data.error || 'Failed to load permissions')
          return
        }
        setIsAdmin(!!data.data.is_admin)
        const filled = buildEmptyMatrix()
        ;(data.data.permissions as Permission[]).forEach((p) => {
          if (filled[p.branch] && filled[p.branch][p.section] !== undefined) {
            filled[p.branch][p.section] = p.level as Level
          }
        })
        setMatrix(filled)

        const pages = (data.data.available_pages || []) as AvailablePage[]
        setAvailablePages(pages)
        const pm: Record<string, CellValue> = {}
        pages.forEach((pg) => {
          pm[pg.page] = 'none'
        })
        ;(data.data.page_permissions || []).forEach((pp: { page: string; level: Level }) => {
          if (pm[pp.page] !== undefined) pm[pp.page] = pp.level
        })
        setPageMatrix(pm)
      } catch {
        setError('Network error')
      } finally {
        setLoading(false)
      }
    })()
  }, [userId])

  const toggleCell = (branch: string, section: string) => {
    if (isAdmin) return
    setMatrix((prev) => {
      const current = prev[branch][section]
      const next = LEVEL_CYCLE[current]
      return {
        ...prev,
        [branch]: { ...prev[branch], [section]: next },
      }
    })
  }

  const setRow = (branch: string, value: CellValue) => {
    if (isAdmin) return
    setMatrix((prev) => ({
      ...prev,
      [branch]: Object.fromEntries(ALL_SECTIONS.map((s) => [s, value])),
    }))
  }

  const setColumn = (section: string, value: CellValue) => {
    if (isAdmin) return
    setMatrix((prev) => {
      const next: Record<string, Record<string, CellValue>> = {}
      for (const b of ALL_BRANCHES) {
        next[b] = { ...prev[b], [section]: value }
      }
      return next
    })
  }

  const togglePage = (page: string) => {
    if (isAdmin) return
    setPageMatrix((prev) => ({
      ...prev,
      [page]: LEVEL_CYCLE[prev[page] ?? 'none'],
    }))
  }

  const setPagesForSection = (section: string, value: CellValue) => {
    if (isAdmin) return
    setPageMatrix((prev) => {
      const next = { ...prev }
      for (const pg of availablePages) {
        if (pg.section === section) next[pg.page] = value
      }
      return next
    })
  }

  // Group available pages by section, preserving the section order from the matrix.
  const pagesBySection = useMemo(() => {
    const out: Array<{ section: string; pages: AvailablePage[] }> = []
    for (const s of ALL_SECTIONS) {
      const pages = availablePages.filter((p) => p.section === s)
      if (pages.length) out.push({ section: s, pages })
    }
    return out
  }, [availablePages])

  const pageItems = useMemo(
    () =>
      Object.entries(pageMatrix)
        .filter(([, v]) => v !== 'none')
        .map(([page, level]) => ({ page, level: level as Level })),
    [pageMatrix],
  )

  const items = useMemo(() => {
    const out: Permission[] = []
    for (const b of ALL_BRANCHES) {
      for (const s of ALL_SECTIONS) {
        const v = matrix[b][s]
        if (v !== 'none') {
          out.push({ branch: b, section: s, level: v })
        }
      }
    }
    return out
  }, [matrix])

  const handleSave = async () => {
    setSaving(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE}/api/users/${userId}/permissions`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ items, page_items: pageItems }),
      })
      const data = await res.json()
      if (data.success) {
        onSaved?.()
        onClose()
      } else {
        setError(data.error || 'Save failed')
      }
    } catch {
      setError('Network error')
    }
    setSaving(false)
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center overflow-auto p-6">
      <div className="bg-white rounded-xl shadow-xl max-w-5xl w-full p-6 my-8">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Phân quyền</h2>
            <p className="text-sm text-gray-500">{userEmail}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        {isAdmin && (
          <div className="bg-amber-50 border border-amber-200 text-amber-800 px-3 py-2 rounded-lg text-sm mb-4">
            User này có role <code>admin</code> — bypass toàn bộ permission. Bỏ role admin trước nếu
            muốn giới hạn.
          </div>
        )}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded-lg text-sm mb-4">
            {error}
          </div>
        )}

        {loading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : (
          <>
            <p className="text-xs text-gray-500 mb-3">
              Click vào ô để đổi giữa <span className="font-medium text-gray-400">—</span> (không có) →{' '}
              <span className="font-medium text-blue-700">View</span> →{' '}
              <span className="font-medium text-green-700">Edit</span>. Dùng nút ở đầu hàng/cột để áp
              nhanh cả dãy.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="text-left px-3 py-2 text-xs font-semibold text-gray-500 uppercase sticky left-0 bg-white">
                      Branch
                    </th>
                    {ALL_SECTIONS.map((s) => (
                      <th key={s} className="px-2 py-2 text-center">
                        <div className="text-xs font-semibold text-gray-700">{SECTION_LABELS[s]}</div>
                        <div className="flex gap-1 justify-center mt-1">
                          <button
                            onClick={() => setColumn(s, 'none')}
                            disabled={isAdmin}
                            className="text-[10px] text-gray-400 hover:text-gray-600 disabled:opacity-30"
                            title="Clear column"
                          >
                            —
                          </button>
                          <button
                            onClick={() => setColumn(s, 'view')}
                            disabled={isAdmin}
                            className="text-[10px] text-blue-500 hover:text-blue-700 disabled:opacity-30"
                            title="Set column = View"
                          >
                            V
                          </button>
                          <button
                            onClick={() => setColumn(s, 'edit')}
                            disabled={isAdmin}
                            className="text-[10px] text-green-600 hover:text-green-800 disabled:opacity-30"
                            title="Set column = Edit"
                          >
                            E
                          </button>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ALL_BRANCHES.map((b) => (
                    <tr key={b} className="border-t border-gray-100">
                      <td className="px-3 py-2 sticky left-0 bg-white">
                        <div className="text-sm font-medium text-gray-900">{b}</div>
                        <div className="flex gap-1 mt-1">
                          <button
                            onClick={() => setRow(b, 'none')}
                            disabled={isAdmin}
                            className="text-[10px] text-gray-400 hover:text-gray-600 disabled:opacity-30"
                            title="Clear row"
                          >
                            —
                          </button>
                          <button
                            onClick={() => setRow(b, 'view')}
                            disabled={isAdmin}
                            className="text-[10px] text-blue-500 hover:text-blue-700 disabled:opacity-30"
                          >
                            V
                          </button>
                          <button
                            onClick={() => setRow(b, 'edit')}
                            disabled={isAdmin}
                            className="text-[10px] text-green-600 hover:text-green-800 disabled:opacity-30"
                          >
                            E
                          </button>
                        </div>
                      </td>
                      {ALL_SECTIONS.map((s) => {
                        const v = matrix[b][s]
                        return (
                          <td key={s} className="px-2 py-2 text-center">
                            <button
                              onClick={() => toggleCell(b, s)}
                              disabled={isAdmin}
                              className={`w-full text-xs font-medium px-2 py-1.5 rounded-md border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${LEVEL_STYLES[v]}`}
                            >
                              {LEVEL_SYMBOLS[v]}
                            </button>
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {pagesBySection.length > 0 && (
              <div className="mt-8 border-t border-gray-100 pt-5">
                <h3 className="text-sm font-semibold text-gray-900">Phân quyền trang (tuỳ chọn)</h3>
                <p className="text-xs text-gray-500 mt-1 mb-4">
                  Để trống cả nhóm = user thấy <span className="font-medium">tất cả</span> trang của mục đó
                  (theo quyền branch ở trên). Bật{' '}
                  <span className="font-medium text-blue-700">View</span>/
                  <span className="font-medium text-green-700">Edit</span> cho vài trang = user{' '}
                  <span className="font-medium">chỉ</span> xem được đúng những trang đó trong mục.
                </p>
                <div className="space-y-4">
                  {pagesBySection.map(({ section, pages }) => (
                    <div key={section}>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs font-semibold text-gray-700">
                          {SECTION_LABELS[section] ?? section}
                        </span>
                        <button
                          onClick={() => setPagesForSection(section, 'none')}
                          disabled={isAdmin}
                          className="text-[10px] text-gray-400 hover:text-gray-600 disabled:opacity-30"
                          title="Bỏ giới hạn (thấy tất cả trang của mục)"
                        >
                          Bỏ giới hạn
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {pages.map((pg) => {
                          const v = pageMatrix[pg.page] ?? 'none'
                          return (
                            <button
                              key={pg.page}
                              onClick={() => togglePage(pg.page)}
                              disabled={isAdmin}
                              className={`text-xs font-medium px-3 py-1.5 rounded-md border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${LEVEL_STYLES[v]}`}
                            >
                              {pg.label} <span className="opacity-60">· {LEVEL_SYMBOLS[v]}</span>
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
          >
            Huỷ
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading || isAdmin}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? 'Đang lưu…' : 'Lưu thay đổi'}
          </button>
        </div>
      </div>
    </div>
  )
}

function buildEmptyMatrix(): Record<string, Record<string, CellValue>> {
  const out: Record<string, Record<string, CellValue>> = {}
  for (const b of ALL_BRANCHES) {
    out[b] = {}
    for (const s of ALL_SECTIONS) {
      out[b][s] = 'none'
    }
  }
  return out
}
