'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

export default function ChangePasswordPage() {
  const { user, loading, refresh, logout } = useAuth()
  const router = useRouter()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  const mustChange = !!user?.must_change_password

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (newPassword.length < 8) {
      setError('New password must be at least 8 characters')
      return
    }
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match')
      return
    }
    if (newPassword === currentPassword) {
      setError('New password must be different from the current one')
      return
    }

    setSubmitting(true)
    try {
      const res = await fetch(`${API_BASE}/api/auth/me/password`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      })
      const data = await res.json()
      if (data.success) {
        setSuccess(true)
        await refresh()
        setTimeout(() => router.push('/'), 1200)
      } else {
        setError(data.error || 'Failed to change password')
      }
    } catch {
      setError('Network error')
    }
    setSubmitting(false)
  }

  if (loading) {
    return <p className="text-gray-500">Loading...</p>
  }

  if (!user) {
    return (
      <div className="max-w-md mx-auto mt-10">
        <p className="text-red-600">You must be logged in to change your password.</p>
      </div>
    )
  }

  return (
    <div className="max-w-md mx-auto mt-6">
      <h1 className="text-2xl font-bold text-gray-900 mb-4">Change Password</h1>

      {mustChange && !success && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 px-4 py-3 rounded-lg text-sm mb-4">
          An administrator has reset your password. You must choose a new password before you can use the platform.
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 p-6">
        {success ? (
          <div className="bg-green-50 text-green-700 px-4 py-3 rounded-lg text-sm">
            Password updated. Redirecting...
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="bg-red-50 text-red-700 px-4 py-3 rounded-lg text-sm">
                {error}
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Current password
              </label>
              <input
                type="password"
                value={currentPassword}
                onChange={e => setCurrentPassword(e.target.value)}
                required
                autoFocus
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder={mustChange ? 'Temporary password from admin' : ''}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                New password
              </label>
              <input
                type="password"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                required
                minLength={8}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <p className="text-xs text-gray-500 mt-1">At least 8 characters.</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Confirm new password
              </label>
              <input
                type="password"
                value={confirmPassword}
                onChange={e => setConfirmPassword(e.target.value)}
                required
                minLength={8}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div className="flex items-center gap-3 pt-2">
              <button
                type="submit"
                disabled={submitting}
                className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {submitting ? 'Updating...' : 'Update password'}
              </button>
              {mustChange && (
                <button
                  type="button"
                  onClick={async () => {
                    await logout()
                    router.push('/login')
                  }}
                  className="text-sm text-gray-500 hover:text-gray-700"
                >
                  Sign out
                </button>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
