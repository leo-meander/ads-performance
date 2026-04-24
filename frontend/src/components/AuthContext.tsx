'use client'

import { createContext, useContext, useEffect, useState, ReactNode } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export const ALL_BRANCHES = ['Saigon', 'Osaka', 'Taipei', '1948', 'Oani', 'Bread'] as const
export const ALL_SECTIONS = [
  'analytics',
  'meta_ads',
  'google_ads',
  'budget',
  'automation',
  'ai',
  'settings',
] as const

export type Branch = (typeof ALL_BRANCHES)[number]
export type Section = (typeof ALL_SECTIONS)[number]
export type Level = 'view' | 'edit'

export interface Permission {
  branch: string
  section: string
  level: Level
}

export interface User {
  id: string
  email: string
  full_name: string
  roles: string[]
  is_active: boolean
  notification_email: boolean
  must_change_password?: boolean
  is_admin?: boolean
  permissions?: Permission[]
  accessible_sections?: Record<string, string[]>
}

interface AuthContextType {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>
  logout: () => Promise<void>
  refresh: () => Promise<void>
  canAccessSection: (section: string) => boolean
  canEditSection: (section: string, branch?: string) => boolean
  branchesForSection: (section: string, minLevel?: Level) => string[]
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  loading: true,
  login: async () => ({ success: false }),
  logout: async () => {},
  refresh: async () => {},
  canAccessSection: () => false,
  canEditSection: () => false,
  branchesForSection: () => [],
})

function isAdmin(user: User | null): boolean {
  return !!user && (user.is_admin === true || (user.roles || []).includes('admin'))
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchMe = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' })
      const data = await res.json()
      if (data.success) setUser(data.data)
      else setUser(null)
    } catch {
      setUser(null)
    }
  }

  useEffect(() => {
    fetchMe().finally(() => setLoading(false))
  }, [])

  const login = async (email: string, password: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      })
      const data = await res.json()
      if (data.success) {
        // After login, pull the full /auth/me payload so we get permissions
        await fetchMe()
        return { success: true }
      }
      return { success: false, error: data.error || 'Login failed' }
    } catch {
      return { success: false, error: 'Network error' }
    }
  }

  const logout = async () => {
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: 'POST',
      credentials: 'include',
    }).catch(() => {})
    setUser(null)
  }

  const canAccessSection = (section: string): boolean => {
    if (!user) return false
    if (isAdmin(user)) return true
    const branches = user.accessible_sections?.[section]
    return !!branches && branches.length > 0
  }

  const canEditSection = (section: string, branch?: string): boolean => {
    if (!user) return false
    if (isAdmin(user)) return true
    const perms = user.permissions || []
    if (branch) {
      return perms.some(
        (p) => p.section === section && p.branch === branch && p.level === 'edit',
      )
    }
    return perms.some((p) => p.section === section && p.level === 'edit')
  }

  const branchesForSection = (section: string, minLevel: Level = 'view'): string[] => {
    if (!user) return []
    if (isAdmin(user)) return [...ALL_BRANCHES]
    const perms = user.permissions || []
    if (minLevel === 'edit') {
      return perms
        .filter((p) => p.section === section && p.level === 'edit')
        .map((p) => p.branch)
    }
    // view: edit implies view
    return perms.filter((p) => p.section === section).map((p) => p.branch)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        logout,
        refresh: fetchMe,
        canAccessSection,
        canEditSection,
        branchesForSection,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
