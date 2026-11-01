import clsx from 'clsx'
import {
  ArrowUp, Check, ChevronDown, Cpu, FileText, Loader2, Paperclip, Square, X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { DragEvent, KeyboardEvent } from 'react'
import { ModelPicker, useModelPicker } from '../composer/ModelPicker'
import { SlashMenu } from '../composer/SlashMenu'
import { ContextMeterChip } from './ContextMeterChip'
import { api } from '../lib/api'
import { filterCommands, parseCommand, type CommandName } from '../lib/commands'
import type { ContextMeter, FileAttachment, FileNode, PermissionMode } from '../lib/types'

const PERMISSION_LABEL: Record<PermissionMode, string> = {
  readonly: '计划模式',
  ask: '每步问我',
  auto: '自动执行',
  full: '完全访问',
}

const PERMISSION_HINT: Record<PermissionMode, string> = {
  readonly: '只读研究与分析：可读码/检索/影响分析/只读命令（如 git diff），所有写入与改动被拒绝，产出建议与计划（命令面板可切换）',
  ask: '改动先给你确认，批准后才写入；会改动仓库的 shell 命令会被拦截，只读命令可直接执行',
  auto: '改动直接写入（保留快照可撤销）；密钥与危险命令仍被拦截',
  full: '自动执行 + 解锁联网装依赖等受限工具（需服务端开启联网）；安全底线不变（命令面板可切换）',
}

const PERMISSION_ORDER: PermissionMode[] = ['readonly', 'ask', 'auto', 'full']

export function Composer({
  disabled,
  streaming,
  model,
  modelLabel,
  permissionMode,
  onPermissionChange,
  contextCount,
  contextMeter,
  attachments,
  uploading,
  onAttach,
  onRemoveAttachment,
  onConfigureModel,
  onSend,
  onCommand,
  onStop,
  mentionRepoId,
}: {
  disabled: boolean
  streaming: boolean
  model: string | null
  models: string[]
  modelLabel: string
  onModelChange: (model: string) => void
  permissionMode: PermissionMode
  onPermissionChange: (mode: PermissionMode) => void
  contextCount: number
  contextMeter: ContextMeter | null
  attachments: FileAttachment[]
  uploading: boolean
  onAttach: (file: File) => void
  onRemoveAttachment: (id: string) => void
  onConfigureModel: () => void
  onSend: (content: string) => void
  /** 执行斜杠命令；返回 false 表示保留草稿（例如缺少项目或 API 失败）。 */
  onCommand: (name: CommandName | 'unknown', args: string) => boolean | void | Promise<boolean | void>
  onStop: () => void
  mentionRepoId?: string | null
}) {
  const [value, setValue] = useState('')
  const [mentionOpen, setMentionOpen] = useState(false)
  const [mentionQuery, setMentionQuery] = useState('')
  const [mentionIndex, setMentionIndex] = useState(0)
  const [mentionLoading, setMentionLoading] = useState(false)
  const [slashOpen, setSlashOpen] = useState(false)
  const [slashQuery, setSlashQuery] = useState('')
  const [slashIndex, setSlashIndex] = useState(0)
  const [commandBusy, setCommandBusy] = useState(false)
  const [modelOpen, setModelOpen] = useState(false)
  const [permissionOpen, setPermissionOpen] = useState(false)
  const mentionCache = useRef<Record<string, string[]>>({})
  const ref = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const picker = useModelPicker()

  useEffect(() => {
    if (!modelOpen && !permissionOpen) return
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      setModelOpen(false)
      setPermissionOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [modelOpen, permissionOpen])

  const flattenFiles = (nodes: FileNode[]): string[] =>
    nodes.flatMap((node) => (node.type === 'file' ? [node.path] : flattenFiles(node.children)))

  const loadMentionFiles = async (repoId: string): Promise<string[]> => {
    const cached = mentionCache.current[repoId]
    if (cached) return cached
    setMentionLoading(true)
    try {
      const files = flattenFiles(await api.repos.tree(repoId))
      mentionCache.current[repoId] = files
      return files
    } catch {
      return []
    } finally {
      setMentionLoading(false)
    }
  }

  const mentionFiles = mentionRepoId ? mentionCache.current[mentionRepoId] ?? [] : []
  const mentionMatches = mentionOpen
    ? mentionFiles
        .filter((path) => path.toLowerCase().includes(mentionQuery.toLowerCase()))
        .slice(0, 8)
    : []

  const detectMention = (text: string) => {
    const match = /(?:^|\s)@([^\s@]*)$/.exec(text)
    if (!match || !mentionRepoId) {
      setMentionOpen(false)
      return
    }
    setMentionQuery(match[1] ?? '')
    setMentionIndex(0)
    setMentionOpen(true)
    if (!mentionCache.current[mentionRepoId]) {
      void loadMentionFiles(mentionRepoId)
    }
  }

  const applyMention = (path: string) => {
    setValue((current) => current.replace(/@([^\s@]*)$/, `@${path} `))
    setMentionOpen(false)
    requestAnimationFrame(() => ref.current?.focus())
  }

  const slashMatches = slashOpen ? filterCommands(slashQuery) : []

  /** 只在「/命令名」阶段展开菜单；空格表示开始写参数，交给命令解析处理。 */
  const detectSlash = (text: string) => {
    const typingName = text.startsWith('/') && !text.includes('\n') && !/\s/.test(text.slice(1))
    if (!typingName) {
      setSlashOpen(false)
      return
    }
    setSlashQuery(text.slice(1))
    setSlashIndex(0)
    setSlashOpen(true)
  }

  const applySlash = (name: CommandName) => {
    setValue(`/${name} `)
    setSlashOpen(false)
    setSlashIndex(0)
    requestAnimationFrame(() => ref.current?.focus())
  }

  const runCommand = async (name: CommandName | 'unknown', args: string) => {
    if (commandBusy || disabled || streaming || uploading) return
    setSlashOpen(false)
    setCommandBusy(true)
    let accepted = true
    try {
      accepted = (await onCommand(name, args)) !== false
    } finally {
      setCommandBusy(false)
    }
    if (accepted) setValue('')
    requestAnimationFrame(() => ref.current?.focus())
  }

  const submit = () => {
    const content = value.trim()
    if (!content || disabled || streaming || uploading || commandBusy) return
    const parsed = parseCommand(content)
    if (parsed) {
      void runCommand(
        parsed.name === 'unknown' ? 'unknown' : parsed.name,
        parsed.name === 'unknown' ? parsed.raw : parsed.args,
      )
      return
    }
    setValue('')
    onSend(content)
    requestAnimationFrame(() => ref.current?.focus())
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (slashOpen && !mentionOpen) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        if (slashMatches.length > 0) setSlashIndex((index) => (index + 1) % slashMatches.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        if (slashMatches.length > 0) setSlashIndex((index) => (index - 1 + slashMatches.length) % slashMatches.length)
        return
      }
      if (e.key === 'Tab') {
        const command = slashMatches[slashIndex] ?? slashMatches[0]
        if (command) {
          e.preventDefault()
          applySlash(command.name)
        }
        // 无匹配时不拦截 Tab，让键盘焦点可以正常离开输入框。
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setSlashOpen(false)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        const command = slashMatches[slashIndex] ?? slashMatches[0]
        if (command) void runCommand(command.name, '')
        else submit()
        return
      }
    }
    if (mentionOpen && mentionMatches.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMentionIndex((index) => (index + 1) % mentionMatches.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMentionIndex((index) => (index - 1 + mentionMatches.length) % mentionMatches.length)
        return
      }
      if (e.key === 'Escape') {
        setMentionOpen(false)
        return
      }
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        applyMention(mentionMatches[mentionIndex] ?? mentionMatches[0])
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    const file = event.dataTransfer.files?.[0]
    if (file) onAttach(file)
  }

  const chipLabel = picker.value.provider && model ? `${picker.value.provider}/${model}` : modelLabel

  return (
    <div className="shrink-0 border-t border-edge/80 bg-base/70 px-4 py-3">
      <div className="mx-auto max-w-5xl">
        <div
          className="relative rounded-2xl border border-edge bg-panel shadow-[0_12px_40px_rgba(0,0,0,0.28)] transition-all focus-within:border-accent/45 focus-within:ring-4 focus-within:ring-accent/5"
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
        >
          <input
            ref={fileRef}
            type="file"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) onAttach(file)
              event.target.value = ''
            }}
          />
          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-3 pt-2.5">
              {attachments.map((file) => (
                <span
                  key={file.id}
                  className="flex max-w-[220px] items-center gap-1 rounded-lg border border-edge/80 bg-raised/70 px-2 py-1 text-[10.5px] text-dim"
                  title={file.filename}
                >
                  <FileText size={11} className="shrink-0 text-accent/80" />
                  <span className="truncate">{file.filename}</span>
                  <span className="shrink-0 text-dim/60">{(file.size / 1024).toFixed(0)}K</span>
                  <button
                    type="button"
                    onClick={() => onRemoveAttachment(file.id)}
                    className="shrink-0 text-dim/60 hover:text-err"
                    aria-label="移除附件"
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <SlashMenu
            open={slashOpen}
            query={slashQuery}
            activeIndex={slashIndex}
            onPick={applySlash}
            onClose={() => setSlashOpen(false)}
          />
          {mentionOpen && mentionRepoId && (
            <div className="absolute bottom-full left-3 z-20 mb-1.5 w-[min(440px,92%)] overflow-hidden rounded-xl border border-edge bg-panel shadow-xl">
              <p className="border-b border-edge/60 px-3 py-1.5 text-[10.5px] uppercase tracking-wide text-dim">
                {mentionLoading ? '加载文件…' : '插入仓库文件'}
              </p>
              {mentionMatches.length === 0 && !mentionLoading ? (
                <p className="px-3 py-2 text-[11.5px] text-dim">没有匹配文件</p>
              ) : (
                mentionMatches.map((path, index) => (
                  <button
                    key={path}
                    type="button"
                    onMouseDown={(event) => {
                      event.preventDefault()
                      applyMention(path)
                    }}
                    className={clsx(
                      'block w-full truncate px-3 py-1.5 text-left font-mono text-[11px]',
                      index === mentionIndex ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:bg-raised',
                    )}
                    title={path}
                  >
                    {path}
                  </button>
                ))
              )}
            </div>
          )}
          <textarea
            ref={ref}
            rows={Math.min(7, value.split('\n').length)}
            value={value}
            onChange={(e) => {
              setValue(e.target.value)
              detectMention(e.target.value)
              detectSlash(e.target.value)
            }}
            onKeyDown={onKeyDown}
            disabled={disabled}
            placeholder="问代码、贴报错，或让 Nova 修改并真实运行验证…"
            className="max-h-48 w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-[13.5px] leading-relaxed outline-none placeholder:text-dim/60 disabled:opacity-60"
          />

          <div className="flex items-center gap-2 px-3 pb-2.5 pt-0.5">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={uploading || attachments.length >= 5}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-edge/80 bg-raised/70 text-dim transition-colors hover:text-ink disabled:opacity-40"
              title="上传附件（最多 5 个，可拖拽）"
              aria-label="上传附件"
            >
              {uploading ? <Loader2 size={12} className="animate-spin" /> : <Paperclip size={12} />}
            </button>
            <button
              type="button"
              onClick={() => {
                setPermissionOpen(false)
                setModelOpen((open) => !open)
              }}
              aria-haspopup="dialog"
              aria-expanded={modelOpen}
              aria-label={`模型：${chipLabel}，打开模型选择`}
              title={`本会话模型：${chipLabel}`}
              className="flex min-w-0 items-center gap-1.5 rounded-lg border border-edge/80 bg-raised/70 py-1 pl-2 pr-1.5 text-xs text-dim transition-colors hover:border-accentSoft hover:text-ink"
            >
              <Cpu size={12} className="shrink-0 text-accent/80" />
              <span className="max-w-[100px] truncate font-mono sm:max-w-[180px]">{chipLabel}</span>
              <ChevronDown size={11} className="shrink-0 text-dim/70" />
            </button>

            <div className="relative shrink-0">
              <button
                type="button"
                onClick={() => {
                  setModelOpen(false)
                  setPermissionOpen((open) => !open)
                }}
                aria-haspopup="menu"
                aria-expanded={permissionOpen}
                aria-label={`权限：${PERMISSION_LABEL[permissionMode]}`}
                title={PERMISSION_HINT[permissionMode]}
                className={clsx(
                  'flex items-center gap-1.5 rounded-lg border border-edge/80 bg-raised/70 py-1 pl-2 pr-1.5 text-xs text-dim transition-colors hover:text-ink',
                  permissionMode === 'full' && 'border-err/40 text-err',
                )}
              >
                <span className="whitespace-nowrap">{PERMISSION_LABEL[permissionMode]}</span>
                <ChevronDown size={11} className="text-dim/70" />
              </button>
              {permissionOpen && (
                <>
                  <div
                    className="fixed inset-0 z-20"
                    onClick={() => setPermissionOpen(false)}
                    aria-hidden="true"
                  />
                  <div
                    role="menu"
                    aria-label="权限模式"
                    className="absolute bottom-full right-0 z-30 mb-2 w-72 rounded-lg border border-edge bg-panel p-1 shadow-pop sm:left-0 sm:right-auto"
                  >
                    {PERMISSION_ORDER.map((mode) => {
                      const active = mode === permissionMode
                      return (
                        <button
                          key={mode}
                          type="button"
                          role="menuitemradio"
                          aria-checked={active}
                          onClick={() => {
                            onPermissionChange(mode)
                            setPermissionOpen(false)
                          }}
                          className={clsx(
                            'flex w-full items-start gap-2 rounded-sm px-2 py-1.5 text-left transition-colors',
                            active
                              ? 'bg-accentSoft/40 text-ink'
                              : 'text-dim hover:bg-raised hover:text-ink',
                          )}
                        >
                          <span className="mt-0.5 w-3 shrink-0 text-accent">
                            {active && <Check size={11} />}
                          </span>
                          <span className="min-w-0">
                            <span className="block text-sm">{PERMISSION_LABEL[mode]}</span>
                            <span className="block text-2xs leading-relaxed text-faint">
                              {PERMISSION_HINT[mode]}
                            </span>
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </>
              )}
            </div>

            <ContextMeterChip meter={contextMeter} />

            <span className="hidden text-[10.5px] text-dim/60 sm:inline">
              {contextCount > 0 ? `${contextCount} 个仓库` : '未关联仓库'}
            </span>

            <div className="ml-auto flex shrink-0 items-center gap-2">
              <span className="hidden text-[10px] text-dim/50 md:inline">Enter 发送 · Shift+Enter 换行</span>
              {streaming ? (
                <button
                  onClick={onStop}
                  className="flex h-8 items-center gap-1.5 rounded-xl border border-err/40 px-3 text-[12px] text-err transition-colors hover:bg-err/10"
                  title="停止生成"
                >
                  <Square size={11} /> 停止
                </button>
              ) : (
                <button
                  onClick={() => void submit()}
                  disabled={disabled || uploading || commandBusy || !value.trim()}
                  className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent text-white transition-all hover:bg-accent/85 disabled:cursor-not-allowed disabled:opacity-30"
                  title="发送"
                  aria-label="发送"
                >
                  {commandBusy ? <Loader2 size={14} className="animate-spin" /> : <ArrowUp size={15} />}
                </button>
              )}
            </div>
          </div>

          <ModelPicker
            open={modelOpen}
            onClose={() => setModelOpen(false)}
            settings={picker.settings}
            value={picker.value}
            onChange={picker.onChange}
            onSetDefault={picker.onSetDefault}
            reasoningCleared={picker.reasoningCleared}
            onConfigure={() => {
              setModelOpen(false)
              onConfigureModel()
            }}
          />
        </div>
      </div>
    </div>
  )
}
