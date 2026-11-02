import clsx from 'clsx'
import {
  ArrowUp, Check, ChevronDown, Cpu, FileText, Loader2, Paperclip, ShieldCheck, Slash, Square, X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ClipboardEvent, DragEvent, KeyboardEvent } from 'react'
import { ModelPicker, useModelPicker } from './ModelPicker'
import { SlashMenu } from './SlashMenu'
import { ContextMeterChip } from '../components/ContextMeterChip'
import { api } from '../lib/api'
import { isVisionImage } from '../lib/attachments'
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

/** 终端输入框：`›` 前缀、无边框 textarea、底部工具行（附件 / 命令 / 模型 / 权限 / 上下文 / 发送）。 */
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
  onAttachFiles,
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
  modelLabel: string
  permissionMode: PermissionMode
  onPermissionChange: (mode: PermissionMode) => void
  contextCount: number
  contextMeter: ContextMeter | null
  attachments: FileAttachment[]
  uploading: boolean
  onAttachFiles: (files: File[]) => void
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
  const activeProviderId = picker.value.provider
    ?? picker.settings?.credentials.find((item) => item.is_default)?.provider
    ?? picker.settings?.provider
    ?? null
  const activeProvider = picker.settings?.providers.find(
    (item) => item.id === activeProviderId,
  ) ?? null
  const visionCapable = activeProvider?.supports_vision ?? false

  useEffect(() => {
    if (!modelOpen && !permissionOpen) return
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
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

  /**
   * `/` 工具按钮：在光标处插入斜杠并把焦点交回 textarea。
   * 插入点不一定在行首，`detectSlash` 的「整段以 / 开头」规则在这里不适用，
   * 所以直接以空查询展开菜单，保证草稿非空时按钮也能打开命令列表。
   */
  const insertSlash = () => {
    const el = ref.current
    const start = el?.selectionStart ?? value.length
    const end = el?.selectionEnd ?? value.length
    const next = `${value.slice(0, start)}/${value.slice(end)}`
    setValue(next)
    setMentionOpen(false)
    setSlashQuery('')
    setSlashIndex(0)
    setSlashOpen(true)
    requestAnimationFrame(() => {
      const node = ref.current
      if (!node) return
      node.focus()
      node.setSelectionRange(start + 1, start + 1)
    })
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
        if (e.defaultPrevented) return
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
        if (e.defaultPrevented) return
        e.preventDefault()
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
    const files = Array.from(event.dataTransfer.files ?? [])
    if (files.length > 0) onAttachFiles(files)
  }

  const chipLabel = picker.value.provider && model ? `${picker.value.provider}/${model}` : modelLabel

  return (
    <div className="shrink-0 border-t border-edge bg-base/95 px-4 py-3">
      <div className="mx-auto max-w-4xl">
        <div
          className="relative rounded-md border border-edge bg-panel transition-colors duration-150 focus-within:border-accent/40"
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
        >
          <input
            ref={fileRef}
            type="file"
            multiple
            accept="image/png,image/jpeg,.txt,.md,.py,.js,.ts,.tsx,.jsx,.json,.yaml,.yml,.toml,.ini,.cfg,.html,.css,.sql,.sh,.java,.go,.rs,.c,.cpp,.h,.xml,.csv,.log"
            className="hidden"
            onChange={(event) => {
              const files = Array.from(event.target.files ?? [])
              if (files.length > 0) onAttachFiles(files)
              event.target.value = ''
            }}
          />

          {attachments.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-3 pt-2.5">
              {attachments.map((file) => {
                const image = isVisionImage(file)
                return (
                  <span
                    key={file.id}
                    className="flex max-w-[240px] items-center gap-1.5 rounded-sm border border-edge bg-diffAdd/70 p-1 font-mono text-2xs text-ink"
                    title={file.filename}
                  >
                    {image ? (
                      <a
                        href={api.files.downloadUrl(file.id)}
                        target="_blank"
                        rel="noreferrer"
                        className="relative block shrink-0"
                        title={`查看 ${file.filename}`}
                      >
                        <img
                          src={api.files.downloadUrl(file.id)}
                          alt={file.filename}
                          className="h-10 w-10 rounded-sm object-cover"
                          loading="lazy"
                        />
                        {!visionCapable && (
                          <span className="absolute inset-x-0 bottom-0 rounded-b-sm bg-err/85 text-center text-[9px] leading-3 text-graphite">
                            不可看图
                          </span>
                        )}
                      </a>
                    ) : (
                      <FileText size={11} className="shrink-0 text-accent" />
                    )}
                    <span className="min-w-0">
                      <span className="block truncate">{file.filename}</span>
                      <span className="block text-faint">{(file.size / 1024).toFixed(0)}K</span>
                    </span>
                    <button
                      type="button"
                      onClick={() => onRemoveAttachment(file.id)}
                      className="shrink-0 text-faint transition-colors duration-150 hover:text-err"
                      aria-label={`移除附件 ${file.filename}`}
                    >
                      <X size={11} />
                    </button>
                  </span>
                )
              })}
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
            <div className="absolute bottom-full left-3 z-20 mb-1.5 w-[min(440px,92%)] overflow-hidden rounded-md border border-edge bg-panel shadow-pop">
              <p className="border-b border-edge/60 px-3 py-1.5 font-mono text-2xs uppercase tracking-[0.12em] text-faint">
                {mentionLoading ? '加载文件…' : '插入仓库文件'}
              </p>
              {mentionMatches.length === 0 && !mentionLoading ? (
                <p className="px-3 py-2 text-xs text-dim">没有匹配文件</p>
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
                      'block w-full truncate px-3 py-1.5 text-left font-mono text-xs transition-colors duration-150',
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

          <div className="flex items-start gap-2 px-3 pt-2.5">
            <span aria-hidden="true" className="select-none pt-0.5 font-mono text-md leading-relaxed text-accent">›</span>
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
              onPaste={(event: ClipboardEvent<HTMLTextAreaElement>) => {
                const files = Array.from(event.clipboardData.files ?? [])
                if (files.length === 0) return
                event.preventDefault()
                onAttachFiles(files)
              }}
              disabled={disabled}
              placeholder="问代码、贴报错，或让 Nova 修改并真实运行验证…"
              className="max-h-48 min-h-[2.25rem] w-full resize-none bg-transparent pb-1 text-base leading-relaxed text-ink outline-none placeholder:text-faint disabled:opacity-60"
            />
          </div>

          <div className="flex flex-wrap items-center gap-1.5 px-2.5 pb-2 pt-1">
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={uploading || attachments.length >= 5}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm border border-edge bg-raised/60 text-dim transition-colors duration-150 hover:text-ink disabled:opacity-40"
              title="上传附件（最多 5 个，可拖拽）"
              aria-label="上传附件"
            >
              {uploading ? <Loader2 size={12} className="animate-spin" /> : <Paperclip size={12} />}
            </button>

            <button
              type="button"
              onClick={insertSlash}
              disabled={disabled || streaming}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-sm border border-edge bg-raised/60 text-dim transition-colors duration-150 hover:text-ink disabled:opacity-40"
              title="插入斜杠命令"
              aria-label="插入斜杠命令"
            >
              <Slash size={12} />
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
              className="flex h-7 min-w-0 items-center gap-1.5 rounded-sm border border-edge bg-raised/60 py-0 pl-2 pr-1.5 text-xs text-dim transition-colors duration-150 hover:border-faint hover:text-ink"
            >
              <Cpu size={12} className="shrink-0 text-accent/80" />
              <span className="max-w-[90px] truncate font-mono sm:max-w-[180px]">{chipLabel}</span>
              <ChevronDown size={11} className="shrink-0 text-faint" />
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
                  'flex h-7 items-center gap-1.5 rounded-sm border border-edge bg-raised/60 px-2 text-xs text-dim transition-colors duration-150 hover:text-ink',
                  permissionMode === 'full' && 'border-err/40 text-err',
                )}
              >
                <ShieldCheck size={12} className="shrink-0" />
                <span className="hidden whitespace-nowrap sm:inline">{PERMISSION_LABEL[permissionMode]}</span>
                <ChevronDown size={11} className="hidden text-faint sm:inline" />
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
                    className="absolute bottom-full right-0 z-30 mb-2 w-72 rounded-md border border-edge bg-panel p-1 shadow-pop sm:left-0 sm:right-auto"
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
                            'flex w-full items-start gap-2 rounded-sm px-2 py-1.5 text-left transition-colors duration-150',
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

            <span className="hidden text-2xs text-faint lg:inline">
              {contextCount > 0 ? `${contextCount} 个仓库` : '未关联仓库'}
            </span>

            <div className="ml-auto flex shrink-0 items-center gap-2">
              <span className="hidden text-2xs text-faint lg:inline">Enter 发送 · Shift+Enter 换行</span>
              {streaming ? (
                <button
                  type="button"
                  onClick={onStop}
                  className="flex h-8 items-center gap-1.5 rounded-sm border border-err/40 px-2.5 text-sm text-err transition-colors duration-150 hover:bg-err/10"
                  title="停止生成"
                >
                  <Square size={11} /> 停止
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void submit()}
                  disabled={disabled || uploading || commandBusy || !value.trim()}
                  className="flex h-8 w-8 items-center justify-center rounded-sm bg-accent text-graphite transition-colors duration-150 hover:bg-accent/85 disabled:cursor-not-allowed disabled:opacity-30"
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
