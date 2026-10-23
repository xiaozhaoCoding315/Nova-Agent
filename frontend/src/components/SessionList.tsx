import clsx from 'clsx'
import { MessageSquarePlus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import type { Session } from '../lib/types'

export function SessionList({
  sessions,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: {
  sessions: Session[]
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
}) {
  const [confirmId, setConfirmId] = useState<string | null>(null)

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between px-3 py-2.5">
        <span className="text-[12px] font-medium uppercase tracking-wide text-dim">会话</span>
        <button
          onClick={onNew}
          className="flex items-center gap-1 rounded-md border border-edge px-2 py-1 text-[12px] text-dim hover:border-accentSoft hover:text-ink"
        >
          <MessageSquarePlus size={12} />
          新对话
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {sessions.length === 0 && <p className="px-2 py-4 text-[12.5px] text-dim">还没有会话，直接开始提问即可。</p>}
        {sessions.map((s) => (
          <div
            key={s.id}
            className={clsx(
              'group mb-0.5 flex cursor-pointer items-center gap-1 rounded-lg px-2.5 py-2 text-[13px]',
              s.id === activeId ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
            )}
            onClick={() => onSelect(s.id)}
          >
            <span className="min-w-0 flex-1 truncate" title={s.title}>
              {s.title}
            </span>
            <span className="text-[10.5px] text-dim/70">{s.message_count}</span>
            {confirmId === s.id ? (
              <button
                className="text-[11px] text-err"
                onClick={(e) => {
                  e.stopPropagation()
                  onDelete(s.id)
                  setConfirmId(null)
                }}
              >
                确认
              </button>
            ) : (
              <button
                className="hidden text-dim/60 hover:text-err group-hover:block"
                onClick={(e) => {
                  e.stopPropagation()
                  setConfirmId(s.id)
                }}
                aria-label="删除会话"
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}