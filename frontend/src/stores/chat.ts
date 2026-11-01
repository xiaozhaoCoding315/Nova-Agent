import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import {
  compactOverrides, providerSupportsReasoning, sanitizeOverrides,
} from '../lib/overrides'
import { streamChat } from '../lib/sse'
import type {
  ContextMeter, DeliveryReport, EditRef, Evidence, FileAttachment, LlmOverrides, LlmProvider,
  Message, PermissionMode, PlanState, RetrievalHit, Session, StreamToolCard, StreamUsage,
  ToolApproval, ToolCall, ToolResult,
} from '../lib/types'
import { useLlm } from './llm'

type ChatState = {
  sessions: Session[]
  sessionId: string | null
  messages: Message[]
  streaming: boolean
  streamText: string
  toolCards: StreamToolCard[]
  streamEdits: EditRef[]
  plan: PlanState | null
  approvals: ToolApproval[]
  permissionMode: PermissionMode
  model: string | null
  provider: string | null
  reasoningEffort: '' | 'low' | 'medium' | 'high'
  /** 会话里持久化过 `reasoning_effort: ""` sentinel（后端视为“未设置”，不继承默认）。 */
  reasoningCleared: boolean
  contextWindow: number | null
  temperature: number | null
  overridesSaving: boolean
  selectedRepoIds: string[]
  historyRepoId: string | null
  attachments: FileAttachment[]
  uploading: boolean
  refs: RetrievalHit[]
  evidence: Evidence | null
  report: DeliveryReport | null
  streamUsage: StreamUsage | null
  contextMeter: ContextMeter | null
  turnNotice: { kind: string; message: string } | null
  error: string | null
  setPermissionMode: (mode: PermissionMode) => void
  setModel: (model: string | null) => void
  applyOverrides: (patch: LlmOverrides) => Promise<void>
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
  resolveApproval: (toolCallId: string, approved: boolean) => Promise<void>
  stop: () => void
  reset: () => void
  clearError: () => void
}

let abortController: AbortController | null = null
/** 丢弃乱序返回的会话参数响应，避免旧响应覆盖新状态。 */
let overridesSeq = 0
/** 串行化 PATCH：后一笔在本笔完成后才发出，保证服务器最后写入的是最新快照。 */
let overridesWriteChain: Promise<void> = Promise.resolve()

/**
 * 发送/加载时读取一次 LLM 配置（非订阅），解析当前生效厂商的 spec。
 * 未显式指定厂商时与后端一致：默认 credential 优先，其次 settings.provider。
 */
function activeProviderSpec(provider: string | null | undefined): LlmProvider | null {
  const settings = useLlm.getState().settings
  if (!settings) return null
  const resolved = provider
    ?? settings.credentials.find((item) => item.is_default)?.provider
    ?? settings.provider
    ?? null
  return settings.providers.find((item) => item.id === resolved) ?? null
}

export const useChat = create<ChatState>((set, get) => ({
  sessions: [],
  sessionId: null,
  messages: [],
  streaming: false,
  streamText: '',
  toolCards: [],
  streamEdits: [],
  plan: null,
  approvals: [],
  permissionMode: 'ask',
  model: null,
  provider: null,
  reasoningEffort: '',
  reasoningCleared: false,
  contextWindow: null,
  temperature: null,
  overridesSaving: false,
  selectedRepoIds: [],
  historyRepoId: null,
  attachments: [],
  uploading: false,
  refs: [],
  evidence: null,
  report: null,
  streamUsage: null,
  contextMeter: null,
  turnNotice: null,
  error: null,

  setPermissionMode: (mode) => set({ permissionMode: mode }),
  setModel: (model) => set({ model }),

  applyOverrides: async (patch) => {
    const current = get()
    const next = compactOverrides({
      provider: patch.provider !== undefined ? patch.provider : current.provider,
      model: patch.model !== undefined ? patch.model : current.model,
      reasoning_effort: patch.reasoning_effort !== undefined
        ? patch.reasoning_effort
        : current.reasoningEffort || undefined,
      context_window: patch.context_window !== undefined
        ? patch.context_window
        : current.contextWindow,
      temperature: patch.temperature !== undefined ? patch.temperature : current.temperature,
    })
    // 后端用 JSONB || 合并覆盖、无法删键：对不支持推理的厂商显式写空串，
    // 覆盖会话里残留的 reasoning_effort（factory 会把 "" 视为未设置）。
    // 仅在确实不支持时写，避免支持推理的厂商丢掉 credential 默认 effort。
    const spec = activeProviderSpec(next.provider ?? null)
    if (spec && !providerSupportsReasoning(spec)) {
      next.reasoning_effort = ''
    }
    // 空串 sentinel 只在已有会话（PATCH 会落盘）时才算「已关闭」；
    // 新会话切到非推理厂商不写库，不能提前声称默认已关闭。
    // 显式选择非空档位则清除 sentinel 状态；其余 patch 保持原值。
    const reasoningCleared = next.reasoning_effort === ''
      ? Boolean(current.sessionId)
      : patch.reasoning_effort
        ? false
        : current.reasoningCleared
    set({
      provider: next.provider ?? null,
      model: next.model ?? null,
      reasoningEffort: next.reasoning_effort ?? '',
      reasoningCleared,
      contextWindow: next.context_window ?? null,
      temperature: next.temperature ?? null,
    })

    const sessionId = current.sessionId
    if (!sessionId) return
    const seq = ++overridesSeq
    set({ overridesSaving: true })
    const write = overridesWriteChain.then(async () => {
      try {
        const updated = await api.sessions.update(sessionId, { llm_overrides: next })
        if (seq === overridesSeq) {
          set((state) => ({
            sessions: state.sessions.map((item) => (
              item.id === sessionId ? { ...item, ...updated } : item
            )),
          }))
        }
      } catch (err) {
        if (seq === overridesSeq) {
          set({ error: err instanceof ApiError ? err.message : '保存会话模型参数失败' })
        }
      } finally {
        if (seq === overridesSeq) set({ overridesSaving: false })
      }
    })
    overridesWriteChain = write
    await write
  },

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
      const rawOverrides = session?.llm_overrides
      // 载入时同样按厂商能力清洗，避免过期持久化参数在 UI 上显示为已选中。
      const spec = activeProviderSpec(rawOverrides?.provider ?? null)
      const overrides = sanitizeOverrides(rawOverrides ?? {}, spec)
      // 必须在 sanitize 之前检查原始 payload：sanitize 会为不支持推理的厂商删掉该键。
      // 只有显式持久化的空串 sentinel 才算「已关闭」，缺键是自动继承默认。
      const reasoningCleared = Boolean(
        rawOverrides
        && Object.prototype.hasOwnProperty.call(rawOverrides, 'reasoning_effort')
        && rawOverrides.reasoning_effort === '',
      )
      set({
        sessionId: id,
        messages,
        refs: [],
        error: null,
        model: overrides.model ?? session?.model ?? null,
        provider: overrides.provider ?? null,
        reasoningEffort: overrides.reasoning_effort ?? '',
        reasoningCleared,
        contextWindow: overrides.context_window ?? null,
        temperature: overrides.temperature ?? null,
        selectedRepoIds: session?.repo_ids ?? [],
        attachments: [],
        contextMeter: null,
        plan: null,
        approvals: [],
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
      sessionId: null, messages: [], refs: [], model: null, provider: null,
      reasoningEffort: '', reasoningCleared: false, contextWindow: null, temperature: null, error: null, plan: null,
      approvals: [], selectedRepoIds: inherited ? [inherited] : [], attachments: [],
      contextMeter: null,
    })
  },

  deleteSession: async (id) => {
    try {
      await api.sessions.remove(id)
      set((s) => ({
        sessions: s.sessions.filter((x) => x.id !== id),
        ...(s.sessionId === id
          ? {
              sessionId: null, messages: [], refs: [], model: null, selectedRepoIds: [],
              attachments: [], provider: null, reasoningEffort: '' as const, reasoningCleared: false,
              contextWindow: null, temperature: null,
            }
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

  resolveApproval: async (toolCallId, approved) => {
    const sessionId = get().sessionId
    if (!sessionId) return
    try {
      if (approved) await api.sessions.approveTool(sessionId, toolCallId)
      else await api.sessions.rejectTool(sessionId, toolCallId)
    } catch (err) {
      set({ error: err instanceof ApiError ? err.message : '审批失败，可能已超时' })
    }
    set((state) => ({ approvals: state.approvals.filter((item) => item.id !== toolCallId) }))
  },

  stop: () => {
    abortController?.abort()
  },

  reset: () => {
    abortController?.abort()
    abortController = null
    set({
      sessions: [], sessionId: null, messages: [], streaming: false, streamText: '',
      toolCards: [], streamEdits: [], plan: null, approvals: [], permissionMode: 'ask',
      model: null, provider: null, reasoningEffort: '', reasoningCleared: false,
      contextWindow: null, temperature: null,
      overridesSaving: false,
      selectedRepoIds: [], historyRepoId: null, attachments: [], uploading: false,
      refs: [],
      evidence: null, report: null, streamUsage: null, contextMeter: null, turnNotice: null, error: null,
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
      plan: null,
      approvals: [],
      refs: [],
      report: null,
      streamUsage: null,
      contextMeter: null,
      turnNotice: null,
      error: null,
      attachments: [],
      messages: [
        ...s.messages,
        { id: Date.now(), role: 'user', content, attachments: pendingAttachments },
      ],
    }))

    const controller = new AbortController()
    abortController = controller

    // 发送前按当前厂商能力兜底清洗，避免过期持久化参数发给不支持的厂商。
    const providerSpec = activeProviderSpec(get().provider)
    const overrides = compactOverrides(sanitizeOverrides({
      provider: get().provider,
      model: get().model,
      reasoning_effort: get().reasoningEffort || undefined,
      context_window: get().contextWindow,
      temperature: get().temperature,
    }, providerSpec))
    // 后端会先把请求覆盖并入会话持久化覆盖再读取；JSONB || 不能删键，必须显式
    // 用空串覆盖旧的 reasoning_effort。同 PATCH：仅对不支持推理的厂商这样做。
    const sentinelPersisted = Boolean(providerSpec && !providerSupportsReasoning(providerSpec))
    if (sentinelPersisted) {
      overrides.reasoning_effort = ''
    }

    try {
      await streamChat(
        {
          session_id: get().sessionId ?? undefined,
          content,
          repo_ids: repoIds,
          permission_mode: get().permissionMode,
          model: get().model ?? undefined,
          llm_overrides: overrides,
          file_ids: pendingAttachments.map((item) => item.id),
        },
        (event, data) => {
          switch (event) {
            case 'meta':
              set((s) => ({
                sessionId: s.sessionId ?? data.session_id,
                ...(data.model ? { model: data.model as string } : {}),
                provider: data.provider ?? s.provider,
                reasoningEffort: data.reasoning_effort ?? s.reasoningEffort,
                // meta 到达时后端已把请求覆盖并入会话；此时 sentinel 才算落库。
                ...(sentinelPersisted ? { reasoningCleared: true } : {}),
                contextWindow: data.context_window ?? s.contextWindow,
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
            case 'context':
              set({
                contextMeter: {
                  window: Number(data.window ?? 0),
                  sections: (data.sections ?? {}) as Record<string, number>,
                  total: Number(data.total ?? 0),
                  actualPromptTokens: data.actual_prompt_tokens != null
                    ? Number(data.actual_prompt_tokens)
                    : null,
                },
              })
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
            case 'tool_approval':
              set((s) => ({
                approvals: [
                  ...s.approvals.filter((item) => item.id !== data.id),
                  {
                    id: String(data.id ?? ''),
                    name: String(data.name ?? ''),
                    args: (data.args ?? {}) as Record<string, unknown>,
                    reason: String(data.reason ?? ''),
                  },
                ],
              }))
              break
            case 'tool_output':
              set((s) => ({
                toolCards: s.toolCards.map((card) =>
                  card.call.id === data.id
                    ? { ...card, output: `${card.output ?? ''}${data.text ?? ''}`.slice(-60_000) }
                    : card,
                ),
              }))
              break
            case 'notice':
              set({ turnNotice: { kind: String(data.kind ?? ''), message: String(data.message ?? '') } })
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
            case 'plan':
              set({
                plan: {
                  steps: Array.isArray(data.steps) ? data.steps : [],
                  explanation: (data.explanation as string | undefined) ?? null,
                },
              })
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
      const { streamText, toolCards, messages, evidence, streamEdits, report, contextMeter, plan } = get()
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
                ...(contextMeter ? { context: contextMeter } : {}),
                ...(plan ? { plan } : {}),
              },
            },
          ],
        })
      }
      set((s) => ({
        streaming: false, streamText: '', toolCards: [], streamEdits: [], plan: null,
        approvals: [], evidence: null, report: null, streamUsage: null,
        // 只有「未完成」通知要留给用户继续按钮；retry/continued 是过程性提示
        turnNotice: s.turnNotice?.kind === 'incomplete' ? s.turnNotice : null,
      }))
      abortController = null
      void get().loadSessions()
    }
  },
}))