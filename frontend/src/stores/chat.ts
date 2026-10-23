import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import { streamChat } from '../lib/sse'
import type { Message, RetrievalHit, Session, StreamToolCard, ToolCall, ToolResult } from '../lib/types'

type ChatState = {
  sessions: Session[]
  sessionId: string | null
  messages: Message[]
  streaming: boolean
  streamText: string
  toolCards: StreamToolCard[]
  refs: RetrievalHit[]
  error: string | null
  loadSessions: () => Promise<void>
  selectSession: (id: string) => Promise<void>
  newSession: () => void
  deleteSession: (id: string) => Promise<void>
  send: (content: string, repoIds: string[]) => Promise<void>
  stop: () => void
  clearError: () => void
}

let abortController: AbortController | null = null

export const useChat = create<ChatState>((set, get) => ({
  sessions: [],
  sessionId: null,
  messages: [],
  streaming: false,
  streamText: '',
  toolCards: [],
  refs: [],
  error: null,

  loadSessions: async () => {
    try {
      set({ sessions: await api.sessions.list() })
    } catch {
      /* session list failures are non-fatal */
    }
  },

  selectSession: async (id) => {
    if (get().streaming) return
    try {
      const messages = await api.sessions.messages(id)
      set({ sessionId: id, messages, refs: [], error: null })
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '加载会话失败' })
    }
  },

  newSession: () => {
    if (get().streaming) return
    set({ sessionId: null, messages: [], refs: [], error: null })
  },

  deleteSession: async (id) => {
    try {
      await api.sessions.remove(id)
      set((s) => ({
        sessions: s.sessions.filter((x) => x.id !== id),
        ...(s.sessionId === id ? { sessionId: null, messages: [], refs: [] } : {}),
      }))
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '删除失败' })
    }
  },

  clearError: () => set({ error: null }),

  stop: () => {
    abortController?.abort()
  },

  send: async (content, repoIds) => {
    if (get().streaming || !content.trim()) return

    set((s) => ({
      streaming: true,
      streamText: '',
      toolCards: [],
      refs: [],
      error: null,
      messages: [...s.messages, { id: Date.now(), role: 'user', content }],
    }))

    const controller = new AbortController()
    abortController = controller

    try {
      await streamChat(
        { session_id: get().sessionId ?? undefined, content, repo_ids: repoIds },
        (event, data) => {
          switch (event) {
            case 'meta':
              if (!get().sessionId) set({ sessionId: data.session_id })
              if (data.title) {
                set((s) => ({
                  sessions: s.sessions.some((x) => x.id === data.session_id)
                    ? s.sessions.map((x) => (x.id === data.session_id ? { ...x, title: data.title } : x))
                    : [{ id: data.session_id, title: data.title, message_count: 1 }, ...s.sessions],
                }))
              }
              break
            case 'retrieval':
              set({ refs: data.hits ?? [] })
              break
            case 'token':
              set((s) => ({ streamText: s.streamText + data.text }))
              break
            case 'tool_call':
              set((s) => ({ toolCards: [...s.toolCards, { call: data as unknown as ToolCall }] }))
              break
            case 'tool_result':
              set((s) => ({
                toolCards: s.toolCards.map((card) =>
                  card.call.id === data.id
                    ? { ...card, result: data as unknown as ToolResult }
                    : card,
                ),
              }))
              break
            case 'error':
              set({ error: data.message ?? '生成失败' })
              break
            default:
              break
          }
        },
        controller.signal,
      )
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '请求失败，请重试' })
    } finally {
      const { streamText, toolCards, messages } = get()
      if (streamText || toolCards.length > 0) {
        set({
          messages: [
            ...messages,
            {
              id: Date.now() + 1,
              role: 'assistant',
              content: streamText,
              tool_json: toolCards.length
                ? { tools_used: toolCards.map((c) => c.call.name) }
                : null,
            },
          ],
        })
      }
      set({ streaming: false, streamText: '', toolCards: [] })
      abortController = null
      void get().loadSessions()
    }
  },
}))