import { ArrowUp, ChevronDown, Cpu, FileText, Loader2, Paperclip, Square, X } from 'lucide-react'
import { useRef, useState } from 'react'
import type { DragEvent, KeyboardEvent } from 'react'
import type { FileAttachment, PermissionMode } from '../lib/types'

const PERMISSION_LABEL: Record<PermissionMode, string> = {
  readonly: '计划模式',
  ask: '变更前确认',
  auto: '自主模式',
  full: '完全访问',
}

const PERMISSION_HINT: Record<PermissionMode, string> = {
  readonly: '只读研究与分析：可读码/检索/影响分析，所有写入与执行被拒绝，产出建议与计划',
  ask: '改动先出 diff 提案，你批准后才写入；执行沙箱代码',
  auto: '改动直接写入仓库（保留快照可撤销），执行沙箱代码；密钥与危险命令仍被拦截',
  full: '自主模式 + 解锁联网装依赖等受限工具（需服务端开启联网）；安全底线（密钥、沙箱边界）不变',
}

export function Composer({
  disabled,
  streaming,
  model,
  models,
  modelLabel,
  onModelChange,
  permissionMode,
  onPermissionChange,
  contextCount,
  attachments,
  uploading,
  onAttach,
  onRemoveAttachment,
  onConfigureModel,
  onSend,
  onStop,
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
  attachments: FileAttachment[]
  uploading: boolean
  onAttach: (file: File) => void
  onRemoveAttachment: (id: string) => void
  onConfigureModel: () => void
  onSend: (content: string) => void
  onStop: () => void
}) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const submit = () => {
    const content = value.trim()
    if (!content || disabled || streaming || uploading) return
    setValue('')
    onSend(content)
    requestAnimationFrame(() => ref.current?.focus())
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
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

  return (
    <div className="shrink-0 border-t border-edge/80 bg-base/70 px-4 py-3">
      <div className="mx-auto max-w-4xl">
        <div
          className="rounded-2xl border border-edge bg-panel shadow-[0_12px_40px_rgba(0,0,0,0.28)] transition-all focus-within:border-accent/45 focus-within:ring-4 focus-within:ring-accent/5"
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
          <textarea
            ref={ref}
            rows={Math.min(7, value.split('\n').length)}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={disabled}
            placeholder="问代码、贴报错，或让 Nova 修改并真实运行验证…"
            className="max-h-48 w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-[13.5px] leading-relaxed outline-none placeholder:text-dim/60 disabled:opacity-60"
          />

          <div className="flex items-center gap-1.5 px-2.5 pb-2 pt-0.5">
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
            {models.length > 0 ? (
              <label className="relative flex items-center gap-1.5 rounded-lg border border-edge/80 bg-raised/70 py-1 pl-2 pr-1.5 text-[11px] text-dim transition-colors hover:text-ink">
                <Cpu size={12} className="text-accent/80" />
                <select
                  value={model ?? models[0]}
                  onChange={(event) => onModelChange(event.target.value)}
                  className="max-w-[170px] cursor-pointer appearance-none truncate bg-transparent pr-4 text-[11px] text-inherit outline-none"
                  title="本会话使用的模型"
                >
                  {models.map((item) => (
                    <option key={item} value={item} className="bg-panel text-ink">
                      {item}
                    </option>
                  ))}
                </select>
                <ChevronDown size={11} className="pointer-events-none absolute right-1.5 text-dim/70" />
              </label>
            ) : (
              <button
                type="button"
                onClick={onConfigureModel}
                className="flex items-center gap-1.5 rounded-lg border border-edge/80 bg-raised/70 px-2 py-1 text-[11px] text-dim transition-colors hover:border-accentSoft hover:text-ink"
                title="配置个人 API Key 后可选择模型"
              >
                <Cpu size={12} className="text-dim/80" />
                <span className="max-w-[180px] truncate">{modelLabel}</span>
              </button>
            )}

            <label className="relative flex items-center rounded-lg border border-edge/80 bg-raised/70 py-1 pl-2 pr-1.5 text-[11px] text-dim transition-colors hover:text-ink">
              <select
                value={permissionMode}
                onChange={(event) => onPermissionChange(event.target.value as PermissionMode)}
                className="cursor-pointer appearance-none bg-transparent pr-4 text-[11px] text-inherit outline-none"
                title={PERMISSION_HINT[permissionMode]}
              >
                {(Object.keys(PERMISSION_LABEL) as PermissionMode[]).map((mode) => (
                  <option key={mode} value={mode} className="bg-panel text-ink" title={PERMISSION_HINT[mode]}>
                    {PERMISSION_LABEL[mode]}
                  </option>
                ))}
              </select>
              <ChevronDown size={11} className="pointer-events-none absolute right-1.5 text-dim/70" />
            </label>

            <span className="hidden text-[10.5px] text-dim/60 sm:inline">
              {contextCount > 0 ? `${contextCount} 个仓库` : '未关联仓库'}
            </span>

            <div className="ml-auto flex items-center gap-2">
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
                  onClick={submit}
                  disabled={disabled || uploading || !value.trim()}
                  className="flex h-8 w-8 items-center justify-center rounded-xl bg-accent text-white transition-all hover:bg-accent/85 disabled:cursor-not-allowed disabled:opacity-30"
                  title="发送"
                  aria-label="发送"
                >
                  <ArrowUp size={15} />
                </button>
              )}
            </div>
          </div>
        </div>
        <p className="mt-1.5 px-1 text-[10px] text-dim/50">
          回答会附带文件行号与执行证据；写入类操作受权限模式约束。
        </p>
      </div>
    </div>
  )
}
