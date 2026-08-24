// Client-side CSV export helpers.
//
// Rows are built in the browser from data already fetched through the normal
// cookie-authed API, so no separate download endpoint (and no API key) is
// needed. Everything here is UTF-8: guest names and room types are routinely
// CJK, so the blob is prefixed with a BOM — without it Excel on Windows opens
// the file as ANSI and mojibakes every non-Latin name.

export type CsvColumn<T> = {
  header: string
  value: (row: T) => string | number | null | undefined
}

// Quote every cell so embedded commas / quotes / newlines survive the round
// trip. Leading =, + or @ are neutralised with a single quote: spreadsheets
// treat those as formulas, and reservation/campaign text is untrusted input.
// A leading "-" is only risky when it isn't just a negative number.
function escapeCell(v: string | number | null | undefined): string {
  if (v === null || v === undefined) return '""'
  const s = String(v)
  const risky = /^[=+@]/.test(s) || (s.startsWith('-') && !/^-\d/.test(s))
  return `"${(risky ? `'${s}` : s).replace(/"/g, '""')}"`
}

export function toCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  const lines = [columns.map(c => escapeCell(c.header)).join(',')]
  for (const row of rows) {
    lines.push(columns.map(c => escapeCell(c.value(row))).join(','))
  }
  return lines.join('\r\n')
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
