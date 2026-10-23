import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import { streamChat } from '../lib/sse'
import type {
  DeliveryReport, EditRef, Evidence, Message, PermissionMode, RetrievalHit, Session, StreamToolCard,
  ToolCall, ToolResult,
} from '../lib/types'

type ChatState = {
  sessions: Session[]
  sessionId: string | null
  messages: Message[]
  streaming: boolean
  streamText: string
  toolCards: StreamToolCard[]
  streamEdits: EditRef[]
  permissionMode: PermissionMode
  model: string | null
  refs: RetrievalHit[]
  evidence: Evidence | null
  report: DeliveryReport | null
  error: string | null
  setPermissionMode: (mode: PermissionMode) => void
  setModel: (model: string | null) => void
  loadSessions: () => Promise<void>
  selectSession: (id: string) => Promise<void>
  newSession: () => void
  deleteSession: (id: string) => Promise<void>
  renameSession: (id: string, title: string) => Promise<void>
  send: (content: string, repoIds: string[]) => Promise<void>
  stop: () => void
  reset: () => void
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
  streamEdits: [],
  permissionMode: 'ask',
  model: null,
  refs: [],
  evidence: null,
  report: null,
  error: null,

  setPermissionMode: (mode) => set({ permissionMode: mode }),
  setModel: (model) => set({ model }),

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
      const session = get().sessions.find((s) => s.id === id)
      set({
        sessionId: id,
        messages,
        refs: [],
        error: null,
        model: session?.model ?? null,
        ...(session?.permission_mode ? { permissionMode: session.permission_mode } : {}),
      })
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '加载会话失败' })
    }
  },

  newSession: () => {
    if (get().streaming) return
    set({ sessionId: null, messages: [], refs: [], model: null, error: null })
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

  renameSession: async (id, title) => {
    const trimmed = title.trim()
    if (!trimmed) return
    try {
      const updated = await api.sessions.rename(id, trimmed)
      set((s) => ({
        sessions: s.sessions.map((item) => (item.id === id ? { ...item, ...updated } : item)),
      }))
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '重命名失败' })
    }
  },

  clearError: () => set({ error: null }),

  stop: () => {
    abortController?.abort()
  },

  reset: () => {
    abortController?.abort()
    abortController = null
    set({
      sessions: [], sessionId: null, messages: [], streaming: false, streamText: '',
      toolCards: [], streamEdits: [], permissionMode: 'ask', model: null, refs: [],
      evidence: null, report: null, error: null,
    })
  },

  send: async (content, repoIds) => {
    if (get().streaming || !content.trim()) return

    set((s) => ({
      streaming: true,
      streamText: '',
      toolCards: [],
      streamEdits: [],
      refs: [],
      report: null,
      error: null,
      messages: [...s.messages, { id: Date.now(), role: 'user', content }],
    }))

    const controller = new AbortController()
    abortController = controller

    try {
      await streamChat(
        {
          session_id: get().sessionId ?? undefined,
          content,
          repo_ids: repoIds,
          permission_mode: get().permissionMode,
          model: get().model ?? undefined,
        },
        (event, data) => {
          switch (event) {
            case 'meta':
              set((s) => ({
                sessionId: s.sessionId ?? data.session_id,
                ...(data.model ? { model: data.model as string } : {}),
                sessions: data.title
                  ? s.sessions.some((x) => x.id === data.session_id)
                    ? s.sessions.map((x) =>
                        x.id === data.session_id
                          ? { ...x, title: data.title, repo_ids: data.repo_ids ?? x.repo_ids }
                          : x,
                      )
                    : [
                        {
                          id: data.session_id,
                          title: data.title,
                          message_count: 1,
                          repo_ids: data.repo_ids ?? [],
                        },
                        ...s.sessions,
                      ]
                  : s.sessions,
              }))
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
            case 'evidence':
              set({ evidence: data as unknown as Evidence })
              break
            case 'done':
              set({ report: (data.report ?? null) as DeliveryReport | null })
              break
            case 'edit_proposal':
              set((s) => ({
                streamEdits: [
                  ...s.streamEdits,
                  {
                    id: data.id,
                    files: data.files ?? [],
                    staged: Boolean(data.staged),
                    status: data.status ?? 'pending',
                    diff: data.diff ?? '',
                  },
                ],
              }))
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
      const { streamText, toolCards, messages, evidence, streamEdits, report } = get()
      if (streamText || toolCards.length > 0 || streamEdits.length > 0) {
        set({
          messages: [
            ...messages,
            {
              id: Date.now() + 1,
              role: 'assistant',
              content: streamText,
              tool_json: {
                ...(toolCards.length ? { tools_used: toolCards.map((c) => c.call.name) } : {}),
                ...(evidence ? { evidence } : {}),
                ...(streamEdits.length ? { edits: streamEdits } : {}),
                ...(report ? { report } : {}),
              },
            },
          ],
        })
      }
      set({ streaming: false, streamText: '', toolCards: [], streamEdits: [], evidence: null, report: null })
      abortController = null
      void get().loadSessions()
    }
  },
}))