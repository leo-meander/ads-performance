const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export { API_BASE }

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<{
  success: boolean
  data: T | null
  error: string | null
}> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    ...options,
  })
  return res.json()
}
