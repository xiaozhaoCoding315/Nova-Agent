import { Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'

export type PaletteAction = {
  id: string
  label: string
  hint?: string
  run: () => void
}

export function CommandPalette({
  open,
  onClose,
  actions,
}: {
  open: boolean
  onClose: () => void
  actions: PaletteAction[]
}) {
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return actions
    return actions.filter(
      (a) => a.label.toLowerCase().includes(q) || (a.hint ?? '').toLowerCase().includes(q),
    )
  }, [actions, query])

  useEffect(() => {
    if (open) {
      setQuery('')
      setIndex(0)
      setTimeout(() => inputRef.current?.focus(), 20)
    }
  }, [open])

  useEffect(() => {
    setIndex(0)
  }, [query])

  if (!open) return null

  const run = (action: PaletteAction | undefined) => {
    if (!action) return
    action.run()
    onClose()
  }

  const onKeyDown = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setIndex((i) => Math.min(i + 1, Math.max(filtered.length - 1, 0)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setIndex((i) => Math.max(i - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      run(filtered[index])
    } else if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-[12vh]" onClick={onClose}>
      <div
        className="w-full max-w-lg overflow-hidden rounded-xl border border-edge bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-edge px-3 py-2.5">
          <Search size={14} className="text-dim" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="搜索命令：切换视图 / 新建对话 / 权限模式…"
            className="flex-1 bg-transparent text-[13px] outline-none placeholder:text-dim/60"
          />
          <kbd className="rounded border border-edge px-1.5 py-0.5 text-[10px] text-dim">Esc</kbd>
        </div>
        <ul className="max-h-72 overflow-y-auto py-1">
          {filtered.length === 0 && <li className="px-3 py-3 text-[12.5px] text-dim">没有匹配的命令</li>}
          {filtered.map((action, i) => (
            <li key={action.id}>
              <button
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] ${
                  i === index ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:bg-raised hover:text-ink'
                }`}
                onMouseEnter={() => setIndex(i)}
                onClick={() => run(action)}
              >
                <span className="flex-1">{action.label}</span>
                {action.hint && <span className="text-[10.5px] text-dim">{action.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
        <div className="border-t border-edge px-3 py-1.5 text-[10.5px] text-dim">
          ↑↓ 选择 · Enter 执行 · Esc 关闭
        </div>
      </div>
    </div>
  )
}