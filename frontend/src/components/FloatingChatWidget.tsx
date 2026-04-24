'use client'

import { useEffect, useRef, useState } from 'react'
import { Send, Plus, Trash2, MessageSquare, X, Sparkles, Maximize2, Minimize2 } from 'lucide-react'
import { useAuth } from '@/components/AuthContext'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Message { role: 'user' | 'assistant'; content: string; error?: boolean }
interface Session { session_id: string; preview: string; message_count: number; started_at: string | null }

const SUGGESTIONS = [
  'Which branch has the best ROAS this week?',
  'Suggest ad angles for Osaka Solo travelers',
  'Why did Saigon spend increase?',
  'Which combos should we scale?',
]

export default function FloatingChatWidget() {
  const { user, canAccessSection } = useAuth()
  const [open, setOpen] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [showSessions, setShowSessions] = useState(false)
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeSession, setActiveSession] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const canUse = !!user && canAccessSection('ai')

  const fetchSessions = () => {
    fetch(`${API_BASE}/api/ai/sessions`, { credentials: 'include' }).then(r => r.json())
      .then(d => { if (d.success) setSessions(d.data) }).catch(() => {})
  }

  const loadSession = (sid: string) => {
    setActiveSession(sid)
    setShowSessions(false)
    fetch(`${API_BASE}/api/ai/sessions/${sid}`, { credentials: 'include' }).then(r => r.json())
      .then(d => { if (d.success) setMessages(d.data.map((m: any) => ({ role: m.role, content: m.content }))) })
      .catch(() => {})
  }

  const newChat = () => {
    setActiveSession(null)
    setMessages([])
    setShowSessions(false)
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  const deleteSession = (sid: string, e: React.MouseEvent) => {
    e.stopPropagation()
    fetch(`${API_BASE}/api/ai/sessions/${sid}`, { method: 'DELETE', credentials: 'include' })
      .then(() => { fetchSessions(); if (activeSession === sid) newChat() })
  }

  useEffect(() => {
    if (open && canUse) fetchSessions()
  }, [open, canUse])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async (override?: string) => {
    const text = (override ?? input).trim()
    if (!text || streaming) return
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: text }])
    setStreaming(true)

    try {
      const res = await fetch(`${API_BASE}/api/ai/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ session_id: activeSession, message: text }),
      })

      if (!res.ok) {
        const errText = await res.text().catch(() => '')
        throw new Error(`HTTP ${res.status}: ${errText.slice(0, 200) || res.statusText}`)
      }

      const sid = res.headers.get('X-Session-Id')
      if (sid && !activeSession) setActiveSession(sid)

      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      let assistantContent = ''
      let sawError = false
      let buffer = ''

      setMessages(prev => [...prev, { role: 'assistant', content: '' }])

      while (reader) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE frames are separated by blank lines
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''

        for (const frame of frames) {
          const lines = frame.split('\n')
          let eventName = 'message'
          let dataParts: string[] = []
          for (const line of lines) {
            if (line.startsWith('event: ')) eventName = line.slice(7).trim()
            else if (line.startsWith('data: ')) dataParts.push(line.slice(6))
          }
          if (dataParts.length === 0) continue
          const raw = dataParts.join('\n')
          if (raw === '[DONE]') continue

          let chunk: string
          try { chunk = JSON.parse(raw) } catch { chunk = raw }

          if (eventName === 'error') sawError = true
          assistantContent += chunk

          setMessages(prev => {
            const updated = [...prev]
            updated[updated.length - 1] = {
              role: 'assistant',
              content: assistantContent,
              error: sawError,
            }
            return updated
          })
        }
      }

      fetchSessions()
    } catch (err: any) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `⚠️ Could not reach AI service: ${err?.message || 'network error'}`,
        error: true,
      }])
    } finally {
      setStreaming(false)
    }
  }

  if (!canUse) return null

  return (
    <>
      {/* Floating launcher */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          aria-label="Open AI chat"
          className="fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full bg-gradient-to-br from-blue-600 to-indigo-600 text-white shadow-lg hover:shadow-xl hover:scale-105 transition-all flex items-center justify-center group"
        >
          <Sparkles className="w-6 h-6" />
          <span className="absolute right-full mr-3 px-2 py-1 rounded bg-gray-900 text-white text-xs whitespace-nowrap opacity-0 group-hover:opacity-100 transition pointer-events-none">
            Ask AI Analyst
          </span>
        </button>
      )}

      {/* Chat panel */}
      {open && (
        <div
          className={`fixed z-50 bg-white border border-gray-200 rounded-2xl shadow-2xl flex overflow-hidden transition-all ${
            expanded
              ? 'inset-6'
              : 'bottom-6 right-6 w-[420px] h-[620px] max-h-[calc(100vh-3rem)] max-w-[calc(100vw-3rem)]'
          }`}
        >
          {/* Session sidebar (collapsible in widget) */}
          {showSessions && (
            <div className="w-56 bg-gray-50 border-r border-gray-200 flex flex-col">
              <div className="p-3 border-b border-gray-200">
                <button
                  onClick={newChat}
                  className="w-full flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
                >
                  <Plus className="w-4 h-4" /> New Chat
                </button>
              </div>
              <div className="flex-1 overflow-auto p-2 space-y-1">
                {sessions.map(s => (
                  <div
                    key={s.session_id}
                    onClick={() => loadSession(s.session_id)}
                    className={`group flex items-center gap-2 px-2 py-2 rounded-lg text-xs cursor-pointer transition ${
                      activeSession === s.session_id ? 'bg-blue-100 text-blue-700' : 'text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    <MessageSquare className="w-3 h-3 shrink-0" />
                    <span className="truncate flex-1">{s.preview || 'New chat'}</span>
                    <button
                      onClick={e => deleteSession(s.session_id, e)}
                      className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                ))}
                {sessions.length === 0 && (
                  <p className="text-xs text-gray-400 text-center py-4">No conversations yet</p>
                )}
              </div>
            </div>
          )}

          {/* Main chat column */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gradient-to-r from-blue-600 to-indigo-600 text-white">
              <div className="flex items-center gap-2 min-w-0">
                <button
                  onClick={() => setShowSessions(v => !v)}
                  className="p-1 hover:bg-white/20 rounded transition"
                  aria-label="Toggle sessions"
                  title="Conversations"
                >
                  <MessageSquare className="w-4 h-4" />
                </button>
                <Sparkles className="w-4 h-4" />
                <div className="min-w-0">
                  <div className="text-sm font-semibold leading-tight truncate">AI Hotel Analyst</div>
                  <div className="text-[10px] text-blue-100 leading-tight">MEANDER Group</div>
                </div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                <button
                  onClick={newChat}
                  className="p-1.5 hover:bg-white/20 rounded transition"
                  title="New chat"
                  aria-label="New chat"
                >
                  <Plus className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setExpanded(v => !v)}
                  className="p-1.5 hover:bg-white/20 rounded transition"
                  title={expanded ? 'Shrink' : 'Expand'}
                  aria-label={expanded ? 'Shrink' : 'Expand'}
                >
                  {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                </button>
                <button
                  onClick={() => setOpen(false)}
                  className="p-1.5 hover:bg-white/20 rounded transition"
                  title="Close"
                  aria-label="Close"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-auto px-4 py-4 space-y-3 bg-gray-50">
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-center px-2">
                  <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-600 to-indigo-600 flex items-center justify-center mb-3">
                    <Sparkles className="w-6 h-6 text-white" />
                  </div>
                  <h2 className="text-sm font-semibold text-gray-800">How can I help today?</h2>
                  <p className="text-xs text-gray-500 mb-4 mt-1">
                    Ask about ROAS, angles, branches, combos...
                  </p>
                  <div className="grid grid-cols-1 gap-2 w-full max-w-sm">
                    {SUGGESTIONS.map(q => (
                      <button
                        key={q}
                        onClick={() => sendMessage(q)}
                        className="text-left px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs text-gray-700 hover:bg-blue-50 hover:border-blue-300 transition"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap break-words ${
                      msg.role === 'user'
                        ? 'bg-blue-600 text-white rounded-br-sm'
                        : msg.error
                          ? 'bg-red-50 border border-red-200 text-red-700 rounded-bl-sm'
                          : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm'
                    }`}
                  >
                    {msg.content || (
                      streaming && i === messages.length - 1
                        ? <span className="text-gray-400 animate-pulse">Thinking...</span>
                        : ''
                    )}
                  </div>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="p-3 border-t border-gray-200 bg-white">
              <form
                onSubmit={e => { e.preventDefault(); sendMessage() }}
                className="flex gap-2 items-end"
              >
                <input
                  ref={inputRef}
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  placeholder="Ask about your hotel ads performance..."
                  disabled={streaming}
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
                />
                <button
                  type="submit"
                  disabled={!input.trim() || streaming}
                  className="p-2.5 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-50 transition shrink-0"
                  aria-label="Send"
                >
                  <Send className="w-4 h-4" />
                </button>
              </form>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
