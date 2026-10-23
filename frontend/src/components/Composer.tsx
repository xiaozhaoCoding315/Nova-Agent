import { CornerDownLeft, Square } from 'lucide-react'
import { useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'

export function Composer({
  disabled,
  streaming,
  onSend,
  onStop,
}: {
  disabled: boolean
  streaming: boolean
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
    <div className="border-t border-edge bg-panel px-4 py-3">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2 rounded-2xl border border-edge bg-raised px-3 py-2 shadow-[0_10px_40px_rgba(0,0,0,0.22)] transition-colors focus-within:border-accentSoft focus-within:ring-2 focus-within:ring-accentSoft/25">
          <textarea
            ref={ref}
            rows={Math.min(6, value.split('\n').length)}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={disabled}
            placeholder="问代码、贴报错、让它写代码并真实运行验证…"
            className="max-h-40 flex-1 resize-none bg-transparent py-1 text-[14px] outline-none placeholder:text-dim/70 disabled:opacity-60"
          />
          {streaming ? (
            <button
              onClick={onStop}
              className="flex items-center gap-1 rounded-lg border border-err/40 px-3 py-1.5 text-[12.5px] text-err hover:bg-err/10"
              title="停止生成"
            >
              <Square size={12} />
              停止
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={disabled || !value.trim()}
              className="flex items-center gap-1 rounded-lg bg-accent px-3 py-1.5 text-[12.5px] text-white transition-colors hover:bg-accent/85 disabled:opacity-40"
              title="发送"
            >
              <CornerDownLeft size={12} />
              发送
            </button>
          )}
        </div>
        <div className="mt-1.5 flex items-center px-1 text-[10.5px] text-dim/60">
          <span>Enter 发送 · Shift + Enter 换行</span>
          <span className="ml-auto hidden sm:inline">回答会附带文件行号与执行证据</span>
        </div>
      </div>
    </div>
  )
}