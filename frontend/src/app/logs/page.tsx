'use client'

import React, { useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import { CheckCircle, XCircle, ChevronDown, ChevronUp, ArrowLeft, X } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface LogEntry {
  id: string
  rule_id: string | null
  rule_name: string
  campaign_id: string | null
  campaign_name: string
  ad_set_id: string | null
  ad_id: string | null
  platform: string
  action: string
  action_params: Record<string, any> | null
  triggered_by: string
  metrics_snapshot: Record<string, any> | null
  success: boolean
  error_message: string | null
  executed_at: string | null
}

const ACTION_COLORS: Record<string, string> = {
  pause_campaign: 'bg-yellow-100 text-yellow-700',
  enable_campaign: 'bg-green-100 text-green-700',
  adjust_budget: 'bg-blue-100 text-blue-700',
  send_alert: 'bg-purple-100 text-purple-700',
  pause_ad: 'bg-yellow-100 text-yellow-700',
  enable_ad: 'bg-green-100 text-green-700',
  pause_adset: 'bg-yellow-100 text-yellow-700',
  enable_adset: 'bg-green-100 text-green-700',
  evaluation_summary: 'bg-gray-100 text-gray-600',
  reenable_ad: 'bg-emerald-100 text-emerald-700',
}

const ACTION_LABELS: Record<string, string> = {
  evaluation_summary: 'Evaluated',
  reenable_ad: 'Re-enable Ad',
  pause_ad: 'Pause Ad',
  enable_ad: 'Enable Ad',
  pause_adset: 'Pause Ad Set',
  enable_adset: 'Enable Ad Set',
  pause_campaign: 'Pause Campaign',
  enable_campaign: 'Enable Campaign',
  adjust_budget: 'Adjust Budget',
  send_alert: 'Alert',
}

export default function LogsPage() {
  const searchParams = useSearchParams()
  const router = useRouter()

  const ruleIdFromUrl = searchParams.get('rule_id')
  const ruleNameFromUrl = searchParams.get('rule_name')

  const [logs, setLogs] = useState<LogEntry[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  // Filters
  const [filterRuleId, setFilterRuleId] = useState(ruleIdFromUrl || '')
  const [filterRuleName, setFilterRuleName] = useState(ruleNameFromUrl || '')
  const [filterSuccess, setFilterSuccess] = useState<string>('')
  const [filterPlatform, setFilterPlatform] = useState('')
  const [offset, setOffset] = useState(0)
  const limit = 50

  // Sync URL params to state
  useEffect(() => {
    if (ruleIdFromUrl) {
      setFilterRuleId(ruleIdFromUrl)
      setFilterRuleName(ruleNameFromUrl || '')
    }
  }, [ruleIdFromUrl, ruleNameFromUrl])

  const fetchLogs = () => {
    setLoading(true)
    const params = new URLSearchParams()
    params.set('limit', String(limit))
    params.set('offset', String(offset))
    if (filterRuleId) params.set('rule_id', filterRuleId)
    if (filterSuccess !== '') params.set('success', filterSuccess)
    if (filterPlatform) params.set('platform', filterPlatform)

    fetch(`${API_BASE}/api/logs?${params}`)
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          setLogs(data.data.items)
          setTotal(data.data.total)
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchLogs() }, [filterRuleId, filterSuccess, filterPlatform, offset])

  const clearRuleFilter = () => {
    setFilterRuleId('')
    setFilterRuleName('')
    setOffset(0)
    router.replace('/logs')
  }

  const totalPages = Math.ceil(total / limit)
  const currentPage = Math.floor(offset / limit) + 1

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          {filterRuleId && (
            <button onClick={() => router.push('/rules')} className="p-1.5 rounded hover:bg-gray-100 text-gray-500">
              <ArrowLeft className="w-5 h-5" />
            </button>
          )}
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Action Logs</h1>
            {filterRuleId && filterRuleName && (
              <p className="text-sm text-gray-500 mt-0.5">
                Filtered by rule: <span className="font-medium text-gray-700">{filterRuleName}</span>
              </p>
            )}
          </div>
        </div>
        <span className="text-sm text-gray-500">{total} entries</span>
      </div>

      {/* Active rule filter banner */}
      {filterRuleId && (
        <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 mb-4 flex items-center justify-between">
          <span className="text-sm text-purple-700">
            Showing logs for rule: <span className="font-semibold">{filterRuleName || filterRuleId}</span>
          </span>
          <button onClick={clearRuleFilter} className="text-purple-500 hover:text-purple-700 flex items-center gap-1 text-sm">
            <X className="w-4 h-4" /> Clear filter
          </button>
        </div>
      )}

      {/* Filters */}
      <div className="bg-white rounded-xl border border-gray-200 p-4 mb-4">
        <div className="flex flex-wrap gap-3 items-center">
          <select value={filterSuccess} onChange={(e) => { setFilterSuccess(e.target.value); setOffset(0) }} className="px-3 py-2 border border-gray-200 rounded-lg text-sm">
            <option value="">All Results</option>
            <option value="true">Success</option>
            <option value="false">Failed</option>
          </select>
          <select value={filterPlatform} onChange={(e) => { setFilterPlatform(e.target.value); setOffset(0) }} className="px-3 py-2 border border-gray-200 rounded-lg text-sm">
            <option value="">All Platforms</option>
            <option value="meta">Meta</option>
          </select>
        </div>
      </div>

      {/* Logs Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-gray-500">Loading logs...</div>
        ) : logs.length === 0 ? (
          <div className="p-8 text-center text-gray-400">
            {filterRuleId
              ? 'No logs yet for this rule. Logs will appear after the rule is evaluated.'
              : 'No action logs yet. Logs will appear when rules are evaluated.'}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-100">
                    <th className="text-left py-3 px-4 text-gray-500 font-medium">Time</th>
                    {!filterRuleId && <th className="text-left py-3 px-4 text-gray-500 font-medium">Rule</th>}
                    <th className="text-left py-3 px-4 text-gray-500 font-medium">Target</th>
                    <th className="text-left py-3 px-4 text-gray-500 font-medium">Action</th>
                    <th className="text-center py-3 px-4 text-gray-500 font-medium">Result</th>
                    <th className="text-left py-3 px-4 text-gray-500 font-medium">Triggered By</th>
                    <th className="w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => (
                    <React.Fragment key={log.id}>
                      <tr className="border-b border-gray-50 hover:bg-gray-50 cursor-pointer" onClick={() => setExpandedId(expandedId === log.id ? null : log.id)}>
                        <td className="py-3 px-4 text-xs text-gray-600 whitespace-nowrap">
                          {log.executed_at ? new Date(log.executed_at).toLocaleString() : '--'}
                        </td>
                        {!filterRuleId && <td className="py-3 px-4 text-gray-700">{log.rule_name}</td>}
                        <td className="py-3 px-4 text-gray-700 max-w-xs truncate">
                          {log.campaign_name}
                          {log.ad_id && <span className="text-xs text-purple-500 ml-1">(ad)</span>}
                          {log.ad_set_id && !log.ad_id && <span className="text-xs text-indigo-500 ml-1">(ad set)</span>}
                        </td>
                        <td className="py-3 px-4">
                          <span className={`text-xs px-2 py-1 rounded font-medium ${ACTION_COLORS[log.action] || 'bg-gray-100 text-gray-600'}`}>
                            {ACTION_LABELS[log.action] || log.action}
                          </span>
                        </td>
                        <td className="py-3 px-4 text-center">
                          {log.action === 'evaluation_summary' ? (
                            log.metrics_snapshot?.actions_taken > 0 ? (
                              <span className="inline-flex items-center gap-1 text-xs text-green-600">
                                <CheckCircle className="w-4 h-4" /> {log.metrics_snapshot.actions_taken} acted
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-xs text-gray-500">
                                0/{log.metrics_snapshot?.entities_checked || 0} matched
                              </span>
                            )
                          ) : log.success ? (
                            <span className="inline-flex items-center gap-1 text-xs text-green-600">
                              <CheckCircle className="w-4 h-4" /> Success
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 text-xs text-red-600">
                              <XCircle className="w-4 h-4" /> Failed
                            </span>
                          )}
                        </td>
                        <td className="py-3 px-4">
                          <span className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600">{log.triggered_by}</span>
                        </td>
                        <td className="py-3 px-4">
                          {expandedId === log.id ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
                        </td>
                      </tr>
                      {expandedId === log.id && (
                        <tr className="bg-gray-50">
                          <td colSpan={filterRuleId ? 6 : 7} className="px-4 py-3">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                              {log.error_message && (
                                <div className="md:col-span-2">
                                  <p className="font-medium text-amber-600 mb-1">{log.action === 'evaluation_summary' ? 'Result' : 'Error'}</p>
                                  <p className={`${log.action === 'evaluation_summary' ? 'text-amber-600 bg-amber-50' : 'text-red-500 bg-red-50'} rounded p-2`}>{log.error_message}</p>
                                </div>
                              )}
                              {log.action === 'evaluation_summary' && log.metrics_snapshot?.fail_breakdown && (
                                <div className="md:col-span-2">
                                  <p className="font-medium text-gray-600 mb-1">Why conditions didn't match</p>
                                  <div className="bg-white rounded p-3 space-y-2">
                                    {Object.entries(log.metrics_snapshot.fail_breakdown as Record<string, number>).map(([condition, count]) => (
                                      <div key={condition} className="flex items-center gap-2">
                                        <div className="flex-1">
                                          <div className="flex justify-between mb-1">
                                            <span className="text-gray-700 font-medium">{condition}</span>
                                            <span className="text-gray-500">{count as number} / {log.metrics_snapshot?.entities_checked || 0} failed here</span>
                                          </div>
                                          <div className="w-full bg-gray-100 rounded-full h-1.5">
                                            <div className="bg-red-400 h-1.5 rounded-full" style={{ width: `${((count as number) / (log.metrics_snapshot?.entities_checked || 1)) * 100}%` }}></div>
                                          </div>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                              {log.action !== 'evaluation_summary' && log.action_params && Object.keys(log.action_params).length > 0 && (
                                <div>
                                  <p className="font-medium text-gray-600 mb-1">Action Params</p>
                                  <pre className="bg-white rounded p-2 text-gray-600 overflow-x-auto">
                                    {JSON.stringify(log.action_params, null, 2)}
                                  </pre>
                                </div>
                              )}
                              {log.action !== 'evaluation_summary' && log.metrics_snapshot && (
                                <div>
                                  <p className="font-medium text-gray-600 mb-1">Metrics Snapshot</p>
                                  <div className="bg-white rounded p-2 grid grid-cols-2 gap-1">
                                    {Object.entries(log.metrics_snapshot).map(([k, v]) => (
                                      <div key={k} className="flex justify-between">
                                        <span className="text-gray-500">{k}:</span>
                                        <span className="text-gray-800 font-medium">{typeof v === 'number' ? v.toLocaleString() : String(v)}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                              <div>
                                <p className="font-medium text-gray-600 mb-1">Details</p>
                                <div className="bg-white rounded p-2 space-y-1">
                                  <div className="flex justify-between"><span className="text-gray-500">Log ID:</span><span className="text-gray-800 font-mono text-[10px]">{log.id}</span></div>
                                  <div className="flex justify-between"><span className="text-gray-500">Campaign ID:</span><span className="text-gray-800 font-mono text-[10px]">{log.campaign_id || '—'}</span></div>
                                  {log.ad_set_id && <div className="flex justify-between"><span className="text-gray-500">Ad Set ID:</span><span className="text-gray-800 font-mono text-[10px]">{log.ad_set_id}</span></div>}
                                  {log.ad_id && <div className="flex justify-between"><span className="text-gray-500">Ad ID:</span><span className="text-gray-800 font-mono text-[10px]">{log.ad_id}</span></div>}
                                  <div className="flex justify-between"><span className="text-gray-500">Platform:</span><span className="text-gray-800">{log.platform}</span></div>
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
                <span className="text-sm text-gray-500">Page {currentPage} of {totalPages}</span>
                <div className="flex gap-2">
                  <button onClick={() => setOffset(Math.max(0, offset - limit))} disabled={offset === 0} className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-50 hover:bg-gray-50">Previous</button>
                  <button onClick={() => setOffset(offset + limit)} disabled={currentPage >= totalPages} className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-50 hover:bg-gray-50">Next</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
