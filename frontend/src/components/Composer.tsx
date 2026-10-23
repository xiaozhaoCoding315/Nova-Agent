import { ArrowUp, ChevronDown, Cpu, Square } from 'lucide-react'
import { useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { PermissionMode } from '../lib/types'

const PERMISSION_LABEL: Record<PermissionMode, string> = {
  readonly: '只读',
  ask: '确认写入',
  auto: '自动执行',
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
  onConfigureModel: () => void
  onSend: (content: string) => void
  onStop: () => void
}) {
  const [value, setValue] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  const submit = () => {
    const content = value.trim()
    if (!content || disabled || streaming) return
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

  return (
    <div className="shrink-0 border-t border-edge/80 bg-base/70 px-4 py-3">
      <div className="mx-auto max-w-4xl">
        <div className="rounded-2xl border border-edge bg-panel shadow-[0_12px_40px_rgba(0,0,0,0.28)] transition-all focus-within:border-accent/45 focus-within:ring-4 focus-within:ring-accent/5">
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
                title="权限模式：只读 / 确认写入 / 自动执行"
              >
                {(Object.keys(PERMISSION_LABEL) as PermissionMode[]).map((mode) => (
                  <option key={mode} value={mode} className="bg-panel text-ink">
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
                  disabled={disabled || !value.trim()}
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
