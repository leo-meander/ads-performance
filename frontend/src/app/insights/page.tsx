'use client'

import { useEffect, useRef, useState } from 'react'
import { Send, Plus, Trash2, MessageSquare } from 'lucide-react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Message { role: 'user' | 'assistant'; content: string }
interface Session { session_id: string; preview: string; message_count: number; started_at: string | null }

export default function InsightsPage() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeSession, setActiveSession] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  const fetchSessions = () => {
    fetch(`${API_BASE}/api/ai/sessions`, { credentials: 'include' }).then(r => r.json())
      .then(d => { if (d.success) setSessions(d.data) }).catch(() => {})
  }

  const loadSession = (sid: string) => {
    setActiveSession(sid)
    fetch(`${API_BASE}/api/ai/sessions/${sid}`, { credentials: 'include' }).then(r => r.json())
      .then(d => { if (d.success) setMessages(d.data.map((m: any) => ({ role: m.role, content: m.content }))) }).catch(() => {})
  }

  const newChat = () => {
    setActiveSession(null)
    setMessages([])
  }

  const deleteSession = (sid: string, e: React.MouseEvent) => {
    e.stopPropagation()
    fetch(`${API_BASE}/api/ai/sessions/${sid}`, { method: 'DELETE', credentials: 'include' })
      .then(() => { fetchSessions(); if (activeSession === sid) newChat() })
  }

  useEffect(() => { fetchSessions() }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const sendMessage = async () => {
    if (!input.trim() || streaming) return
    const userMsg = input.trim()
    setInput('')
    setMessages(prev => [...prev, { role: 'user', content: userMsg }])
    setStreaming(true)

    try {
      const res = await fetch(`${API_BASE}/api/ai/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ session_id: activeSession, message: userMsg }),
      })

      // Get session ID from header
      const sid = res.headers.get('X-Session-Id')
      if (sid && !activeSession) setActiveSession(sid)

      if (!res.ok) {
        const errText = await res.text().catch(() => '')
        throw new Error(`HTTP ${res.status}: ${errText.slice(0, 200) || res.statusText}`)
      }

      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      let assistantContent = ''
      let buffer = ''

      setMessages(prev => [...prev, { role: 'assistant', content: '' }])

      while (reader) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''
        for (const frame of frames) {
          const dataLines = frame.split('\n').filter(l => l.startsWith('data: ')).map(l => l.slice(6))
          if (dataLines.length === 0) continue
          const raw = dataLines.join('\n')
          if (raw === '[DONE]') continue
          let chunk: string
          try { chunk = JSON.parse(raw) } catch { chunk = raw }
          assistantContent += chunk
          setMessages(prev => {
            const updated = [...prev]
            updated[updated.length - 1] = { role: 'assistant', content: assistantContent }
            return updated
          })
        }
      }

      fetchSessions()
    } catch (err: any) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `⚠️ Could not reach AI service: ${err?.message || 'network error'}`,
      }])
    } finally {
      setStreaming(false)
    }
  }

  return (
    <div className="flex h-[calc(100vh-3rem)] -m-6">
      {/* Session Sidebar */}
      <div className="w-64 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-4 border-b border-gray-200">
          <button onClick={newChat} className="w-full flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700">
            <Plus className="w-4 h-4" /> New Chat
          </button>
        </div>
        <div className="flex-1 overflow-auto p-2 space-y-1">
          {sessions.map(s => (
            <div
              key={s.session_id}
              onClick={() => loadSession(s.session_id)}
              className={`group flex items-center gap-2 px-3 py-2 rounded-lg text-sm cursor-pointer transition ${
                activeSession === s.session_id ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:bg-gray-100'
              }`}
            >
              <MessageSquare className="w-4 h-4 shrink-0" />
              <span className="truncate flex-1">{s.preview || 'New chat'}</span>
              <button onClick={e => deleteSession(s.session_id, e)} className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500">
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          ))}
          {sessions.length === 0 && <p className="text-xs text-gray-400 text-center py-4">No conversations yet</p>}
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 flex flex-col bg-gray-50">
        {/* Messages */}
        <div className="flex-1 overflow-auto p-6 space-y-4">
          {messages.length === 0 && (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <h2 className="text-xl font-semibold text-gray-700 mb-2">AI Hotel Marketing Analyst</h2>
                <p className="text-sm text-gray-400 mb-6">Ask about ads performance, suggest angles, analyze branches...</p>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-w-lg mx-auto">
                  {[
                    'Which branch has the best ROAS this week?',
                    'Suggest ad angles for Osaka Solo travelers',
                    'Why did Saigon spend increase?',
                    'Which combos should we scale?',
                  ].map(q => (
                    <button
                      key={q}
                      onClick={() => { setInput(q); }}
                      className="text-left px-3 py-2 bg-white border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-blue-50 hover:border-blue-200 transition"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[75%] rounded-xl px-4 py-3 text-sm whitespace-pre-wrap ${
                msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-white border border-gray-200 text-gray-800'
              }`}>
                {msg.content || (streaming && i === messages.length - 1 ? <span className="text-gray-400 animate-pulse">Thinking...</span> : '')}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="p-4 border-t border-gray-200 bg-white">
          <form onSubmit={e => { e.preventDefault(); sendMessage() }} className="flex gap-2">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Ask about your hotel ads performance..."
              disabled={streaming}
              className="flex-1 px-4 py-3 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!input.trim() || streaming}
              className="px-4 py-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 disabled:opacity-50 transition"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
