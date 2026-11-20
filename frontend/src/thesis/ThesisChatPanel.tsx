import clsx from 'clsx'
import {
  ArrowUp, History, MessageSquarePlus, Settings2, Square, ShieldCheck, Wrench,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Markdown } from '../components/Markdown'
import { Spinner } from '../components/common'
import type { PermissionMode, ThesisProjectDetail } from '../lib/types'
import { useChat } from '../stores/chat'
import { useThesis } from '../stores/thesis'

const PERMISSIONS: { value: PermissionMode; label: string; hint: string }[] = [
  { value: 'readonly', label: '只读', hint: '只读代码与论文，不写文件' },
  { value: 'ask', label: '询问', hint: '每次写文件或执行命令前确认' },
  { value: 'auto', label: '自动', hint: '自动应用安全的本地修改' },
  { value: 'full', label: '完全', hint: '不逐条确认（谨慎使用）' },
]

const QUICK_PROMPTS = [
  '先读一遍关联工程项目的结构和关键文件，用一段话说明这个项目做了什么、技术栈和主要模块。',
  '根据项目实现给出论文提纲（到二级标题），每章标注对应的项目模块或证据。',
  '检查论文与项目是否一致：哪些实现没写进论文，哪些论文描述在代码里找不到依据。',
]

function clip(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}…`
}

export function ThesisChatPanel({
  project,
  onOpenSettings,
}: {
  project: ThesisProjectDetail
  onOpenSettings: () => void
}) {
  const sessions = useChat((state) => state.sessions)
  const sessionId = useChat((state) => state.sessionId)
  const messages = useChat((state) => state.messages)
  const streaming = useChat((state) => state.streaming)
  const streamText = useChat((state) => state.streamText)
  const toolCards = useChat((state) => state.toolCards)
  const approvals = useChat((state) => state.approvals)
  const permissionMode = useChat((state) => state.permissionMode)
  const error = useChat((state) => state.error)
  const setScope = useChat((state) => state.setScope)
  const loadSessions = useChat((state) => state.loadSessions)
  const newSession = useChat((state) => state.newSession)
  const selectSession = useChat((state) => state.selectSession)
  const setPermissionMode = useChat((state) => state.setPermissionMode)
  const setSelectedRepoIds = useChat((state) => state.setSelectedRepoIds)
  const send = useChat((state) => state.send)
  const stop = useChat((state) => state.stop)
  const resolveApproval = useChat((state) => state.resolveApproval)
  const clearError = useChat((state) => state.clearError)

  const chatSeed = useThesis((state) => state.chatSeed)
  const setChatSeed = useThesis((state) => state.setChatSeed)

  const [input, setInput] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const repoIds = project.source_repo_id ? [project.source_repo_id] : []

  // 每个论文项目有自己的对话范围；进入时清空内存态，历史按项目从服务端取。
  useEffect(() => {
    setScope('thesis', project.id)
    newSession()
    setSelectedRepoIds(project.source_repo_id ? [project.source_repo_id] : [])
    void loadSessions()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id])

  useEffect(() => {
    if (!chatSeed) return
    setInput(chatSeed)
    setChatSeed('')
    inputRef.current?.focus()
  }, [chatSeed, setChatSeed])

  useEffect(() => {
    const node = listRef.current
    if (node) node.scrollTop = node.scrollHeight
  }, [messages, streamText, toolCards, approvals])

  const submit = () => {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')
    void send(text, repoIds)
  }

  const startNewChat = () => {
    newSession()
    setSelectedRepoIds(repoIds)
    setInput('')
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-panel/30">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-edge px-3 py-2.5">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <ShieldCheck size={14} className="shrink-0 text-accent" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-ink">AI 写作助手</p>
            <p className="truncate font-mono text-2xs text-faint">
              {project.source_repo_id ? '已关联工程项目 · 可读写本地文件' : '未关联项目 · 只基于论文与引用'}
            </p>
          </div>
        </div>
        <button
          onClick={startNewChat}
          className="flex items-center gap-1 rounded-md border border-edge px-2 py-1 text-2xs text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink"
          title="新对话"
        >
          <MessageSquarePlus size={12} /> 新对话
        </button>
        <button
          onClick={onOpenSettings}
          className="flex items-center gap-1 rounded-md border border-edge px-2 py-1 text-2xs text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink"
          title="模型与密钥"
        >
          <Settings2 size={12} />
        </button>
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-edge px-3 py-2">
        <label className="flex min-w-0 flex-1 items-center gap-1.5 text-2xs text-faint">
          <History size={12} className="shrink-0" />
          <select
            value={sessionId ?? ''}
            onChange={(event) => {
              const value = event.target.value
              if (value) void selectSession(value)
              else startNewChat()
            }}
            className="min-w-0 flex-1 rounded-sm border border-edge bg-base px-1.5 py-1 text-2xs text-dim outline-none focus:border-accent"
          >
            <option value="">当前对话</option>
            {sessions.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}（{item.message_count}）
              </option>
            ))}
          </select>
        </label>
        <select
          value={permissionMode}
          onChange={(event) => setPermissionMode(event.target.value as PermissionMode)}
          title={PERMISSIONS.find((item) => item.value === permissionMode)?.hint}
          className="rounded-sm border border-edge bg-base px-1.5 py-1 text-2xs text-dim outline-none focus:border-accent"
        >
          {PERMISSIONS.map((item) => (
            <option key={item.value} value={item.value}>{item.label}</option>
          ))}
        </select>
      </div>

      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {messages.length === 0 && !streaming && (
          <div className="rounded-md border border-dashed border-edge bg-base/40 px-3 py-4">
            <p className="text-xs leading-relaxed text-dim">
              先读项目，再动笔。AI 会引用仓库里的文件与行号，只用你已导入的参考文献；
              生成的正文是草稿，需要你核对、改写并记入 AI 使用声明。
            </p>
            <div className="mt-2 flex flex-col items-stretch gap-1.5">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => setInput(prompt)}
                  className="rounded-sm border border-edge bg-panel/60 px-2 py-1.5 text-left text-2xs leading-relaxed text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.filter((item) => item.role === 'user' || item.role === 'assistant').map((item) => (
          <div key={item.id} className={clsx('flex', item.role === 'user' ? 'justify-end' : 'justify-start')}>
            <div
              className={clsx(
                'max-w-[92%] rounded-lg px-2.5 py-2 text-xs leading-relaxed',
                item.role === 'user'
                  ? 'bg-accentSoft/40 text-ink'
                  : 'border border-edge bg-base/60 text-dim',
              )}
            >
              {item.role === 'assistant'
                ? <Markdown content={item.content} />
                : <p className="whitespace-pre-wrap">{item.content}</p>}
            </div>
          </div>
        ))}

        {streaming && (
          <div className="flex justify-start">
            <div className="max-w-[92%] rounded-lg border border-edge bg-base/60 px-2.5 py-2 text-xs leading-relaxed text-dim">
              {toolCards.length > 0 && (
                <div className="mb-2 space-y-1 border-b border-edge/60 pb-2">
                  {toolCards.map((card) => (
                    <div key={card.call.id} className="flex items-center gap-1.5 font-mono text-2xs text-faint">
                      <Wrench size={10} className="shrink-0" />
                      <span className="truncate">{card.call.name}</span>
                      <span className={clsx(card.result?.ok === false ? 'text-err' : 'text-dim')}>
                        {card.result ? (card.result.ok ? '完成' : '失败') : '运行中…'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {streamText
                ? <Markdown content={streamText} />
                : (
                  <span className="flex items-center gap-2 text-faint">
                    <Spinner /> 正在阅读与思考…
                  </span>
                )}
            </div>
          </div>
        )}

        {approvals.map((approval) => (
          <div key={approval.id} className="rounded-md border border-warn/40 bg-warn/10 px-2.5 py-2">
            <p className="text-xs font-medium text-ink">需要确认：{approval.name}</p>
            <p className="mt-1 max-h-24 overflow-y-auto whitespace-pre-wrap break-all font-mono text-2xs text-dim">
              {clip(JSON.stringify(approval.args, null, 2), 800)}
            </p>
            {approval.reason && <p className="mt-1 text-2xs text-faint">{approval.reason}</p>}
            <div className="mt-2 flex gap-2">
              <button
                onClick={() => void resolveApproval(approval.id, true)}
                className="rounded-sm bg-accent px-2 py-1 text-2xs text-base transition-opacity hover:opacity-90"
              >
                允许
              </button>
              <button
                onClick={() => void resolveApproval(approval.id, false)}
                className="rounded-sm border border-edge px-2 py-1 text-2xs text-dim transition-colors hover:text-ink"
              >
                拒绝
              </button>
            </div>
          </div>
        ))}

        {error && (
          <div className="rounded-md border border-err/30 bg-err/10 px-2.5 py-2 text-2xs leading-relaxed text-err">
            {error}
            <div className="mt-1 flex gap-2">
              <button onClick={clearError} className="text-2xs text-dim underline">关闭</button>
              <button onClick={onOpenSettings} className="text-2xs text-accent underline">模型与密钥</button>
            </div>
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-edge px-3 py-2.5">
        <div className="rounded-md border border-edge bg-base/70 focus-within:border-accent">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                submit()
              }
            }}
            rows={3}
            placeholder="让 AI 理解项目、搭提纲、写章节草稿…（Enter 发送，Shift+Enter 换行）"
            className="w-full resize-none bg-transparent px-2.5 py-2 text-xs leading-relaxed text-ink outline-none placeholder:text-faint"
          />
          <div className="flex items-center justify-between px-2 pb-2">
            <span className="text-2xs text-faint">AI 草稿需本人核对 · 引用只用已导入条目</span>
            {streaming ? (
              <button
                onClick={stop}
                className="flex items-center gap-1 rounded-sm border border-edge px-2 py-1 text-2xs text-dim hover:text-ink"
              >
                <Square size={10} /> 停止
              </button>
            ) : (
              <button
                onClick={submit}
                disabled={!input.trim()}
                className="flex items-center gap-1 rounded-sm bg-accent px-2 py-1 text-2xs text-base transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                <ArrowUp size={11} /> 发送
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
