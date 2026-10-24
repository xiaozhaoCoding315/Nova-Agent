import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import { streamChat } from '../lib/sse'
import type {
  DeliveryReport, EditRef, Evidence, FileAttachment, Message, PermissionMode, RetrievalHit,
  Session, StreamToolCard, StreamUsage, ToolCall, ToolResult,
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
  selectedRepoIds: string[]
  historyRepoId: string | null
  attachments: FileAttachment[]
  uploading: boolean
  refs: RetrievalHit[]
  evidence: Evidence | null
  report: DeliveryReport | null
  streamUsage: StreamUsage | null
  error: string | null
  setPermissionMode: (mode: PermissionMode) => void
  setModel: (model: string | null) => void
  setSelectedRepoIds: (ids: string[]) => void
  toggleRepo: (id: string) => void
  setHistoryRepoId: (id: string | null) => Promise<void>
  uploadAttachment: (file: File) => Promise<void>
  removeAttachment: (id: string) => Promise<void>
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
  selectedRepoIds: [],
  historyRepoId: null,
  attachments: [],
  uploading: false,
  refs: [],
  evidence: null,
  report: null,
  streamUsage: null,
  error: null,

  setPermissionMode: (mode) => set({ permissionMode: mode }),
  setModel: (model) => set({ model }),
  setSelectedRepoIds: (ids) => set({ selectedRepoIds: Array.from(new Set(ids)).slice(0, 5) }),
  toggleRepo: (id) => set((state) => ({
    selectedRepoIds: state.selectedRepoIds.includes(id)
      ? state.selectedRepoIds.filter((item) => item !== id)
      : [...state.selectedRepoIds, id].slice(0, 5),
  })),
  setHistoryRepoId: async (id) => {
    set({ historyRepoId: id })
    await get().loadSessions()
  },

  uploadAttachment: async (file) => {
    set({ uploading: true, error: null })
    try {
      const attachment = await api.files.upload(file, {
        repoId: get().selectedRepoIds[0],
      })
      set((state) => ({ attachments: [...state.attachments, attachment].slice(0, 5) }))
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '上传附件失败' })
    } finally {
      set({ uploading: false })
    }
  },

  removeAttachment: async (id) => {
    set((state) => ({ attachments: state.attachments.filter((item) => item.id !== id) }))
    try {
      await api.files.remove(id)
    } catch {
      /* the file library may already be cleaned */
    }
  },

  loadSessions: async () => {
    try {
      set({ sessions: await api.sessions.list(get().historyRepoId ?? undefined) })
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
        selectedRepoIds: session?.repo_ids ?? [],
        attachments: [],
        ...(session?.permission_mode ? { permissionMode: session.permission_mode } : {}),
      })
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '加载会话失败' })
    }
  },

  newSession: () => {
    if (get().streaming) return
    const inherited = get().historyRepoId
    set({
      sessionId: null, messages: [], refs: [], model: null, error: null,
      selectedRepoIds: inherited ? [inherited] : [], attachments: [],
    })
  },

  deleteSession: async (id) => {
    try {
      await api.sessions.remove(id)
      set((s) => ({
        sessions: s.sessions.filter((x) => x.id !== id),
        ...(s.sessionId === id
          ? { sessionId: null, messages: [], refs: [], selectedRepoIds: [], attachments: [] }
          : {}),
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
      toolCards: [], streamEdits: [], permissionMode: 'ask', model: null,
      selectedRepoIds: [], historyRepoId: null, attachments: [], uploading: false, refs: [],
      evidence: null, report: null, streamUsage: null, error: null,
    })
  },

  send: async (content, repoIds) => {
    if (get().streaming || get().uploading || !content.trim()) return
    const pendingAttachments = get().attachments

    set((s) => ({
      streaming: true,
      streamText: '',
      toolCards: [],
      streamEdits: [],
      refs: [],
      report: null,
      streamUsage: null,
      error: null,
      attachments: [],
      messages: [
        ...s.messages,
        { id: Date.now(), role: 'user', content, attachments: pendingAttachments },
      ],
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
          file_ids: pendingAttachments.map((item) => item.id),
        },
        (event, data) => {
          switch (event) {
            case 'meta':
              set((s) => ({
                sessionId: s.sessionId ?? data.session_id,
                ...(data.model ? { model: data.model as string } : {}),
                ...(Array.isArray(data.repo_ids) ? { selectedRepoIds: data.repo_ids as string[] } : {}),
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
            case 'usage':
              set({
                streamUsage: {
                  model: data.model as string | undefined,
                  prompt_tokens: Number(data.prompt_tokens ?? 0),
                  completion_tokens: Number(data.completion_tokens ?? 0),
                },
              })
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
      const finishedEvents = toolCards.filter((card) => card.result)
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
                ...(finishedEvents.length
                  ? {
                      tool_events: finishedEvents.map((card) => ({
                        name: card.call.name,
                        ok: Boolean(card.result!.ok),
                        ms: card.result!.ms,
                        round: card.call.round,
                        args: card.call.args,
                        error: card.result!.ok ? null : card.result!.preview,
                        preview: card.result!.preview,
                      })),
                    }
                  : {}),
                ...(evidence ? { evidence } : {}),
                ...(streamEdits.length ? { edits: streamEdits } : {}),
                ...(report ? { report } : {}),
              },
            },
          ],
        })
      }
      set({ streaming: false, streamText: '', toolCards: [], streamEdits: [], evidence: null, report: null, streamUsage: null })
      abortController = null
      void get().loadSessions()
    }
  },
}))