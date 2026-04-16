'use client'

import { useEffect, useState } from 'react'
import { Plus, X, Trash2 } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Keypoint { id: string; branch_id: string; category: string; title: string; combos: number; spend: number; revenue: number; roas: number; conversions: number; ctr: number }
interface Account { id: string; account_name: string }

const CATEGORIES = ['location', 'amenity', 'experience', 'value']
const CAT_COLORS: Record<string, string> = {
  location: 'bg-blue-50 text-blue-700',
  amenity: 'bg-green-50 text-green-700',
  experience: 'bg-purple-50 text-purple-700',
  value: 'bg-orange-50 text-orange-700',
}

export default function KeypointsPage() {
  const [keypoints, setKeypoints] = useState<Keypoint[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)

  const [formBranch, setFormBranch] = useState('')
  const [formCategory, setFormCategory] = useState('location')
  const [formTitle, setFormTitle] = useState('')
  const _formDescRemoved = null // description removed

  const fetch_kp = () => {
    setLoading(true)
    fetch(`${API_BASE}/api/keypoints`).then(r => r.json()).then(d => { if (d.success) setKeypoints(d.data) }).catch(() => {}).finally(() => setLoading(false))
  }

  useEffect(() => {
    fetch(`${API_BASE}/api/accounts`).then(r => r.json()).then(d => { if (d.success) setAccounts(d.data.filter((a: any) => a.platform === 'meta')) }).catch(() => {})
    fetch_kp()
  }, [])

  const handleCreate = () => {
    if (!formBranch || !formTitle) return
    fetch(`${API_BASE}/api/keypoints`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ branch_id: formBranch, category: formCategory, title: formTitle }),
    }).then(r => r.json()).then(d => { if (d.success) { setShowCreate(false); setFormTitle(''); fetch_kp() } })
  }

  const deleteKp = (id: string) => {
    fetch(`${API_BASE}/api/keypoints/${id}`, { method: 'DELETE' }).then(() => fetch_kp())
  }

  // Group by branch
  const grouped: Record<string, { name: string; items: Keypoint[] }> = {}
  for (const kp of keypoints) {
    const acc = accounts.find(a => a.id === kp.branch_id)
    const name = acc?.account_name || 'Unknown'
    if (!grouped[kp.branch_id]) grouped[kp.branch_id] = { name, items: [] }
    grouped[kp.branch_id].items.push(kp)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Branch Keypoints</h1>
        <button onClick={() => setShowCreate(true)} className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
          <Plus className="w-4 h-4" /> Add Keypoint
        </button>
      </div>

      {showCreate && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 mb-6">
          <div className="flex justify-between mb-4"><h2 className="text-lg font-semibold">New Keypoint</h2><button onClick={() => setShowCreate(false)}><X className="w-5 h-5 text-gray-400" /></button></div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            <div><label className="block text-xs text-gray-500 mb-1">Branch</label><select value={formBranch} onChange={e => setFormBranch(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">{!formBranch && <option value="">Select...</option>}{accounts.map(a => <option key={a.id} value={a.id}>{a.account_name}</option>)}</select></div>
            <div><label className="block text-xs text-gray-500 mb-1">Category</label><select value={formCategory} onChange={e => setFormCategory(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">{CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}</select></div>
          </div>
          <div className="mb-3"><label className="block text-xs text-gray-500 mb-1">Title</label><input value={formTitle} onChange={e => setFormTitle(e.target.value)} className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" placeholder="e.g., Rooftop pool with city view" /></div>
          <button onClick={handleCreate} disabled={!formBranch || !formTitle} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">Create</button>
        </div>
      )}

      {loading ? <div className="text-gray-500 text-center py-8">Loading...</div> : Object.keys(grouped).length === 0 ? (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">No keypoints yet. Add selling points for each branch.</div>
      ) : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([branchId, { name, items }]) => (
            <div key={branchId} className="bg-white rounded-xl border border-gray-200 p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">{name}</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {items.map(kp => (
                  <div key={kp.id} className="flex items-start gap-3 p-3 rounded-lg bg-gray-50">
                    <span className={`text-xs px-2 py-0.5 rounded font-medium shrink-0 ${CAT_COLORS[kp.category] || 'bg-gray-100 text-gray-600'}`}>{kp.category}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900">{kp.title}</p>
                      {kp.combos > 0 && (
                        <div className="flex gap-3 mt-1 text-[11px] text-gray-500">
                          <span>{kp.combos} ads</span>
                          <span>ROAS <strong className={kp.roas >= 1 ? 'text-green-600' : 'text-red-500'}>{kp.roas.toFixed(2)}x</strong></span>
                          <span>{kp.conversions} bookings</span>
                          <span>CTR {(kp.ctr * 100).toFixed(2)}%</span>
                        </div>
                      )}
                    </div>
                    <button onClick={() => deleteKp(kp.id)} className="text-gray-400 hover:text-red-500 shrink-0"><Trash2 className="w-4 h-4" /></button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
