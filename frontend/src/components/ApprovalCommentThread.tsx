'use client'

import { useEffect, useState, useCallback } from 'react'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'

interface Comment {
  id: string
  user_id: string
  user_name: string
  body: string
  parent_id: string | null
  created_at: string | null
  replies: Comment[]
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function initials(name: string): string {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join('')
}

interface CommentItemProps {
  comment: Comment
  onReply: (parentId: string) => void
  replyingTo: string | null
  replyBody: string
  setReplyBody: (v: string) => void
  submitReply: (parentId: string) => void
  submitting: boolean
}

function CommentItem({ comment, onReply, replyingTo, replyBody, setReplyBody, submitReply, submitting }: CommentItemProps) {
  return (
    <div className="flex gap-3">
      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-100 text-blue-700 flex items-center justify-center text-xs font-semibold">
        {initials(comment.user_name)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className="text-sm font-medium text-gray-900">{comment.user_name}</span>
          {comment.created_at && (
            <span className="text-xs text-gray-400">{timeAgo(comment.created_at)}</span>
          )}
        </div>
        <p className="text-sm text-gray-700 whitespace-pre-line">{comment.body}</p>
        <button
          onClick={() => onReply(comment.id)}
          className="mt-1 text-xs text-gray-400 hover:text-blue-600"
        >
          Reply
        </button>

        {replyingTo === comment.id && (
          <div className="mt-2">
            <textarea
              value={replyBody}
              onChange={e => setReplyBody(e.target.value)}
              placeholder="Write a reply…"
              rows={2}
              className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
            <div className="flex gap-2 mt-1">
              <button
                onClick={() => submitReply(comment.id)}
                disabled={submitting || !replyBody.trim()}
                className="bg-blue-600 text-white px-3 py-1 rounded-lg text-xs font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {submitting ? 'Posting…' : 'Post reply'}
              </button>
              <button
                onClick={() => onReply('')}
                className="text-xs text-gray-400 hover:text-gray-600"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {comment.replies.length > 0 && (
          <div className="mt-3 space-y-3 border-l-2 border-gray-100 pl-4">
            {comment.replies.map(r => (
              <CommentItem
                key={r.id}
                comment={r}
                onReply={onReply}
                replyingTo={replyingTo}
                replyBody={replyBody}
                setReplyBody={setReplyBody}
                submitReply={submitReply}
                submitting={submitting}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

interface Props {
  approvalId?: string
  batchId?: string
}

export default function ApprovalCommentThread({ approvalId, batchId }: Props) {
  const [comments, setComments] = useState<Comment[]>([])
  const [newBody, setNewBody] = useState('')
  const [replyingTo, setReplyingTo] = useState<string | null>(null)
  const [replyBody, setReplyBody] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const endpoint = approvalId
    ? `${API_BASE}/api/approvals/${approvalId}/comments`
    : `${API_BASE}/api/approvals/batch/${batchId}/comments`

  const fetchComments = useCallback(() => {
    fetch(endpoint, { credentials: 'include' })
      .then(r => r.json())
      .then(d => { if (d.success) setComments(d.data || []) })
      .catch(() => {})
  }, [endpoint])

  useEffect(() => {
    fetchComments()
    const timer = setInterval(fetchComments, 30000)
    return () => clearInterval(timer)
  }, [fetchComments])

  const postComment = async (body: string, parentId?: string) => {
    if (!body.trim()) return
    setSubmitting(true)
    setError('')
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ body: body.trim(), parent_id: parentId || null }),
      })
      const d = await res.json()
      if (d.success) {
        setComments(d.data || [])
        if (parentId) {
          setReplyingTo(null)
          setReplyBody('')
        } else {
          setNewBody('')
        }
      } else {
        setError(d.error || 'Failed to post comment')
      }
    } catch {
      setError('Network error')
    }
    setSubmitting(false)
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-4">Comments</h3>

      {comments.length === 0 && (
        <p className="text-sm text-gray-400 italic mb-4">No comments yet. Be the first to add one.</p>
      )}

      {comments.length > 0 && (
        <div className="space-y-4 mb-4">
          {comments.map(c => (
            <CommentItem
              key={c.id}
              comment={c}
              onReply={id => {
                setReplyingTo(id || null)
                setReplyBody('')
              }}
              replyingTo={replyingTo}
              replyBody={replyBody}
              setReplyBody={setReplyBody}
              submitReply={id => postComment(replyBody, id)}
              submitting={submitting}
            />
          ))}
        </div>
      )}

      <div className="border-t border-gray-100 pt-4">
        <textarea
          value={newBody}
          onChange={e => setNewBody(e.target.value)}
          placeholder="Add a comment…"
          rows={3}
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
        />
        {error && (
          <p className="text-xs text-red-600 mt-1">{error}</p>
        )}
        <div className="flex justify-end mt-2">
          <button
            onClick={() => postComment(newBody)}
            disabled={submitting || !newBody.trim()}
            className="bg-blue-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          >
            {submitting ? 'Posting…' : 'Post comment'}
          </button>
        </div>
      </div>
    </div>
  )
}
