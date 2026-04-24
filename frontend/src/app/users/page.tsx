'use client'

import { useEffect, useState } from 'react'
import { useAuth } from '@/components/AuthContext'
import PermissionMatrix from '@/components/PermissionMatrix'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface UserItem {
  id: string
  email: string
  full_name: string
  roles: string[]
  is_active: boolean
  must_change_password?: boolean
  created_at: string | null
}

const ROLE_OPTIONS = ['admin', 'creator', 'reviewer']

export default function UsersPage() {
  const { user } = useAuth()
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ email: '', full_name: '', password: '', roles: ['creator'] })
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [permsTarget, setPermsTarget] = useState<UserItem | null>(null)
  const [resetTarget, setResetTarget] = useState<UserItem | null>(null)

  const isAdmin = user?.is_admin || user?.roles?.includes('admin')

  const fetchUsers = () => {
    fetch(`${API_BASE}/api/users`, { credentials: 'include' })
      .then(r => r.json())
      .then(data => { if (data.success) setUsers(data.data.items || []) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchUsers() }, [])

  const handleCreate = async () => {
    setCreating(true)
    setError('')
    try {
      const res = await fetch(`${API_BASE}/api/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(form),
      })
      const data = await res.json()
      if (data.success) {
        setShowCreate(false)
        setForm({ email: '', full_name: '', password: '', roles: ['creator'] })
        fetchUsers()
      } else {
        setError(data.error || 'Failed to create user')
      }
    } catch {
      setError('Network error')
    }
    setCreating(false)
  }

  const toggleRole = (userId: string, role: string) => {
    const u = users.find(u => u.id === userId)
    if (!u) return
    const newRoles = u.roles.includes(role)
      ? u.roles.filter(r => r !== role)
      : [...u.roles, role]

    fetch(`${API_BASE}/api/users/${userId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ roles: newRoles }),
    })
      .then(r => r.json())
      .then(data => { if (data.success) fetchUsers() })
      .catch(() => {})
  }

  const toggleActive = (userId: string, isActive: boolean) => {
    fetch(`${API_BASE}/api/users/${userId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ is_active: !isActive }),
    })
      .then(r => r.json())
      .then(data => { if (data.success) fetchUsers() })
      .catch(() => {})
  }

  if (!isAdmin) return <p className="text-red-500">Admin access required</p>

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">User Management</h1>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          {showCreate ? 'Cancel' : 'Create User'}
        </button>
      </div>

      {showCreate && (
        <div className="bg-white rounded-xl border border-gray-200 p-4 mb-6">
          {error && <div className="bg-red-50 text-red-700 px-3 py-2 rounded-lg text-sm mb-3">{error}</div>}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Email</label>
              <input
                type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="user@meander.com"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Full Name</label>
              <input
                type="text" value={form.full_name} onChange={e => setForm({ ...form, full_name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Password</label>
              <input
                type="password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Roles</label>
              <div className="flex gap-2 mt-1">
                {ROLE_OPTIONS.map(role => (
                  <label key={role} className="flex items-center gap-1 text-sm">
                    <input
                      type="checkbox"
                      checked={form.roles.includes(role)}
                      onChange={() => setForm({
                        ...form,
                        roles: form.roles.includes(role)
                          ? form.roles.filter(r => r !== role)
                          : [...form.roles, role],
                      })}
                    />
                    {role}
                  </label>
                ))}
              </div>
            </div>
          </div>
          <button
            onClick={handleCreate} disabled={creating || !form.email || !form.full_name || !form.password}
            className="mt-4 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {creating ? 'Creating...' : 'Create User'}
          </button>
        </div>
      )}

      {loading ? (
        <p className="text-gray-500">Loading...</p>
      ) : (
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Name</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Email</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Roles</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Status</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-900">{u.full_name}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{u.email}</td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {ROLE_OPTIONS.map(role => (
                        <button
                          key={role}
                          onClick={() => toggleRole(u.id, role)}
                          className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                            u.roles.includes(role)
                              ? 'bg-blue-100 text-blue-700'
                              : 'bg-gray-100 text-gray-400'
                          }`}
                        >
                          {role}
                        </button>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-medium ${u.is_active ? 'text-green-600' : 'text-red-500'}`}>
                      {u.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2 items-center">
                      <button
                        onClick={() => setPermsTarget(u)}
                        className="text-xs px-2 py-1 rounded-md bg-indigo-50 text-indigo-700 hover:bg-indigo-100 font-medium"
                      >
                        Permissions
                      </button>
                      <button
                        onClick={() => setResetTarget(u)}
                        className="text-xs px-2 py-1 rounded-md bg-amber-50 text-amber-700 hover:bg-amber-100 font-medium"
                      >
                        Reset Password
                      </button>
                      <button
                        onClick={() => toggleActive(u.id, u.is_active)}
                        className="text-xs text-gray-500 hover:text-gray-700"
                      >
                        {u.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {permsTarget && (
        <PermissionMatrix
          userId={permsTarget.id}
          userEmail={permsTarget.email}
          onClose={() => setPermsTarget(null)}
        />
      )}

      {resetTarget && (
        <ResetPasswordModal
          user={resetTarget}
          onClose={() => setResetTarget(null)}
          onSuccess={fetchUsers}
        />
      )}
    </div>
  )
}

function ResetPasswordModal({
  user,
  onClose,
  onSuccess,
}: {
  user: UserItem
  onClose: () => void
  onSuccess: () => void
}) {
  const [mode, setMode] = useState<'auto' | 'manual'>('auto')
  const [manualPassword, setManualPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [tempPassword, setTempPassword] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const submit = async () => {
    setError('')
    if (mode === 'manual' && manualPassword.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    setSubmitting(true)
    try {
      const res = await fetch(`${API_BASE}/api/users/${user.id}/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          new_password: mode === 'manual' ? manualPassword : null,
        }),
      })
      const data = await res.json()
      if (data.success) {
        setTempPassword(data.data?.temporary_password || null)
        onSuccess()
      } else {
        setError(data.error || 'Failed to reset password')
      }
    } catch {
      setError('Network error')
    }
    setSubmitting(false)
  }

  const copyToClipboard = async () => {
    if (!tempPassword) return
    try {
      await navigator.clipboard.writeText(tempPassword)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // noop — clipboard may be unavailable
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">Reset Password</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="p-6">
          {tempPassword ? (
            <div>
              <p className="text-sm text-gray-700 mb-3">
                Password reset for <strong>{user.email}</strong>. Share this
                temporary password with the user — they'll be required to change
                it on next login.
              </p>
              <div className="bg-gray-50 border border-gray-200 rounded-lg px-3 py-2 font-mono text-sm break-all mb-3">
                {tempPassword}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={copyToClipboard}
                  className="bg-blue-600 text-white px-3 py-1.5 rounded-lg text-sm font-medium hover:bg-blue-700"
                >
                  {copied ? 'Copied!' : 'Copy'}
                </button>
                <button
                  onClick={onClose}
                  className="text-sm text-gray-500 hover:text-gray-700"
                >
                  Done
                </button>
              </div>
              <p className="text-xs text-gray-500 mt-3">
                This password will not be shown again.
              </p>
            </div>
          ) : (
            <div>
              <p className="text-sm text-gray-600 mb-4">
                Reset password for <strong>{user.email}</strong>. The user will
                be forced to set a new password at next login.
              </p>

              {error && (
                <div className="bg-red-50 text-red-700 px-3 py-2 rounded-lg text-sm mb-3">
                  {error}
                </div>
              )}

              <div className="space-y-3">
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="radio"
                    checked={mode === 'auto'}
                    onChange={() => setMode('auto')}
                    className="mt-0.5"
                  />
                  <span>
                    <span className="font-medium text-gray-800">Generate random password</span>
                    <span className="block text-xs text-gray-500">
                      A 12-character temporary password will be generated.
                    </span>
                  </span>
                </label>

                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="radio"
                    checked={mode === 'manual'}
                    onChange={() => setMode('manual')}
                    className="mt-0.5"
                  />
                  <span className="flex-1">
                    <span className="font-medium text-gray-800">Choose password</span>
                    <input
                      type="text"
                      value={manualPassword}
                      onChange={e => setManualPassword(e.target.value)}
                      onFocus={() => setMode('manual')}
                      placeholder="At least 8 characters"
                      className="mt-1 w-full px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono"
                    />
                  </span>
                </label>
              </div>

              <div className="flex items-center gap-2 mt-5">
                <button
                  onClick={submit}
                  disabled={submitting}
                  className="bg-amber-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-amber-700 disabled:opacity-50"
                >
                  {submitting ? 'Resetting...' : 'Reset Password'}
                </button>
                <button
                  onClick={onClose}
                  className="text-sm text-gray-500 hover:text-gray-700"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
