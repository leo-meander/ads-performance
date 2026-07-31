'use client'

import { useMemo, useState } from 'react'

// Shared table primitive for the GA4 analytics page: click a header to sort,
// type to filter, click a row to pin it as a cross-filter. Extracted from the
// page so the sorting/filtering behaviour can be exercised on its own.

export const TH = 'py-2 px-3 text-gray-500 font-medium text-xs'
export const TD = 'py-2 px-3 text-xs text-gray-700'

// ── sortable + filterable table ──────────────────────────────────────────

export type Col<T> = {
  key: string
  label: string
  align?: 'left' | 'right'
  /** Raw comparable value — sorting uses this, never the formatted string. */
  value: (row: T) => number | string | null | undefined
  render?: (row: T) => React.ReactNode
  sortable?: boolean
  className?: string
}

export type SortState = { key: string; dir: 'asc' | 'desc' }

export function DataTable<T extends Record<string, any>>({
  rows, cols, initialSort, filterPlaceholder, filterOn, maxHeight, emptyText = 'No data',
  rowClassName, onRowClick, isRowActive,
}: {
  rows: T[]
  cols: Col<T>[]
  initialSort?: SortState
  /** Show a search box filtering on these columns' values. */
  filterOn?: string[]
  filterPlaceholder?: string
  maxHeight?: string
  emptyText?: string
  rowClassName?: (row: T) => string
  /** Clicking a row pins it as a cross-filter. */
  onRowClick?: (row: T) => void
  /** True when the row is the one currently pinned. */
  isRowActive?: (row: T) => boolean
}) {
  const [sort, setSort] = useState<SortState | null>(initialSort ?? null)
  const [query, setQuery] = useState('')

  const toggle = (col: Col<T>) => {
    if (col.sortable === false) return
    setSort(prev => {
      if (prev?.key !== col.key) {
        // First click: numbers are almost always most-interesting largest-first,
        // labels alphabetical.
        const sample = rows.find(r => col.value(r) !== null && col.value(r) !== undefined)
        const isNumeric = typeof (sample ? col.value(sample) : '') === 'number'
        return { key: col.key, dir: isNumeric ? 'desc' : 'asc' }
      }
      return { key: col.key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
    })
  }

  const visible = useMemo(() => {
    let out = rows
    if (query.trim() && filterOn?.length) {
      const q = query.trim().toLowerCase()
      out = out.filter(r =>
        filterOn.some(k => {
          const col = cols.find(c => c.key === k)
          const v = col ? col.value(r) : r[k]
          return String(v ?? '').toLowerCase().includes(q)
        }),
      )
    }
    if (sort) {
      const col = cols.find(c => c.key === sort.key)
      if (col) {
        const dir = sort.dir === 'asc' ? 1 : -1
        out = [...out].sort((a, b) => {
          const av = col.value(a)
          const bv = col.value(b)
          // Missing values always sink to the bottom, whichever way we sort —
          // a column of dashes floating to the top hides the real rows.
          if (av === null || av === undefined) return bv === null || bv === undefined ? 0 : 1
          if (bv === null || bv === undefined) return -1
          if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
          return String(av).localeCompare(String(bv)) * dir
        })
      }
    }
    return out
  }, [rows, cols, sort, query, filterOn])

  return (
    <div>
      {!!filterOn?.length && (
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder={filterPlaceholder || 'Filter…'}
          className="mb-2 w-full px-2.5 py-1.5 border border-gray-200 rounded-lg text-xs"
        />
      )}
      <div className={`overflow-x-auto ${maxHeight ? `${maxHeight} overflow-y-auto` : ''}`}>
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10">
            <tr className="bg-gray-50 border-b">
              {cols.map(c => {
                const active = sort?.key === c.key
                const sortable = c.sortable !== false
                return (
                  <th
                    key={c.key}
                    onClick={() => toggle(c)}
                    className={`${TH} ${c.align === 'right' ? 'text-right' : 'text-left'} ${
                      sortable ? 'cursor-pointer select-none hover:text-gray-700' : ''
                    } ${active ? 'text-gray-900' : ''}`}
                  >
                    <span className={`inline-flex items-center gap-1 ${c.align === 'right' ? 'flex-row-reverse' : ''}`}>
                      {c.label}
                      {sortable && (
                        <span className={`text-[9px] leading-none ${active ? 'text-blue-600' : 'text-gray-300'}`}>
                          {active ? (sort!.dir === 'asc' ? '▲' : '▼') : '⇅'}
                        </span>
                      )}
                    </span>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {visible.length === 0 && (
              <tr><td colSpan={cols.length} className="py-6 text-center text-gray-400 text-xs">
                {query ? `No rows match “${query}”` : emptyText}
              </td></tr>
            )}
            {visible.map((r, i) => {
              const active = isRowActive?.(r)
              return (
              <tr
                key={i}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                className={`border-b last:border-0 ${rowClassName ? rowClassName(r) : ''} ${
                  onRowClick ? 'cursor-pointer hover:bg-blue-50/60' : ''
                } ${active ? 'bg-blue-50 ring-1 ring-inset ring-blue-300' : ''}`}
              >
                {cols.map(c => (
                  <td key={c.key} className={`${TD} ${c.align === 'right' ? 'text-right' : ''} ${c.className || ''}`}>
                    {c.render ? c.render(r) : (c.value(r) ?? '—')}
                  </td>
                ))}
              </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {!!filterOn?.length && query && (
        <p className="text-[11px] text-gray-400 mt-1">{visible.length} of {rows.length} rows</p>
      )}
    </div>
  )
}
