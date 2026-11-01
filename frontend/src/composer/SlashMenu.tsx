import clsx from 'clsx'
import { X } from 'lucide-react'
import { filterCommands, type CommandName } from '../lib/commands'

/**
 * 输入框上的斜杠命令列表。键盘选择由 Composer 统一处理（与输入框共享焦点），
 * 这里只负责展示、过滤与鼠标点选。
 */
export function SlashMenu({
  open,
  query,
  activeIndex = 0,
  onPick,
  onClose,
}: {
  open: boolean
  query: string
  activeIndex?: number
  onPick: (name: CommandName) => void
  onClose: () => void
}) {
  if (!open) return null
  const items = filterCommands(query)

  return (
    <div
      role="listbox"
      aria-label="斜杠命令"
      className="absolute bottom-full left-3 z-20 mb-1.5 w-[min(440px,92%)] overflow-hidden rounded-xl border border-edge bg-panel shadow-xl"
    >
      <div className="flex items-center justify-between border-b border-edge/60 px-3 py-1.5">
        <span className="text-[10.5px] uppercase tracking-wide text-dim">斜杠命令</span>
        <button
          type="button"
          onClick={onClose}
          className="text-dim/70 transition-colors hover:text-ink"
          aria-label="关闭命令菜单"
        >
          <X size={11} />
        </button>
      </div>
      {items.length === 0 ? (
        <p className="px-3 py-2 text-[11.5px] leading-relaxed text-dim">
          没有匹配的命令。输入 <code className="font-mono">/help</code> 查看全部命令。
        </p>
      ) : (
        <div className="max-h-72 overflow-y-auto py-1">
          {items.map((item, index) => (
            <button
              key={item.name}
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              onMouseDown={(event) => {
                event.preventDefault()
                onPick(item.name)
              }}
              className={clsx(
                'flex w-full items-baseline gap-2 px-3 py-1.5 text-left transition-colors',
                index === activeIndex ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:bg-raised',
              )}
            >
              <code className="w-16 shrink-0 font-mono text-[11.5px] text-accent">/{item.name}</code>
              <span className="min-w-0 flex-1">
                <span className="block text-[12px] text-ink">{item.label}</span>
                <span className="block truncate text-[10.5px] text-dim">{item.hint}</span>
              </span>
              {index === activeIndex && <kbd className="shrink-0 text-[9.5px] text-dim/70">Tab</kbd>}
            </button>
          ))}
        </div>
      )}
      <p className="border-t border-edge/60 px-3 py-1 text-[10px] text-dim/70">
        ↑↓ 选择 · Tab 补全 · Enter 执行 · Esc 关闭
      </p>
    </div>
  )
}
