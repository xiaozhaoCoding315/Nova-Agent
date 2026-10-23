import clsx from 'clsx'
import { Activity, ChevronDown, ChevronRight, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { TraceEvent } from '../lib/types'
import { Badge, Spinner } from './common'

const KIND_TONE: Record<string, 'dim' | 'accent' | 'ok' | 'warn' | 'err' | undefined> = {
  user: 'accent',
  turn_start: 'dim',
  retrieval: 'dim',
  llm_round: 'accent',
  tool_call: 'warn',
  tool_result: 'ok',
  edit_proposal: 'warn',
  edit_applied: 'ok',
  edit_rejected: 'dim',
  edit_reverted: 'dim',
  error: 'err',
  done: 'ok',
}

const KIND_LABEL: Record<string, string> = {
  user: '用户消息',
  turn_start: '回合开始',
  retrieval: '检索',
  llm_round: '模型轮次',
  tool_call: '工具调用',
  tool_result: '工具结果',
  edit_proposal: '修改提案',
  edit_applied: '修改已应用',
  edit_rejected: '修改被拒绝',
  edit_reverted: '修改已撤销',
  error: '错误',
  done: '完成',
}

function summarize(event: TraceEvent): string {
  const p = event.payload ?? {}
  switch (event.kind) {
    case 'user':
    case 'turn_start':
      return String(p.content ?? p.user ?? '').slice(0, 160)
    case 'retrieval':
      return `${(p.hits ?? []).length} 条命中 · ${(p.hits ?? []).slice(0, 3).map((h: any) => h.path).join('，')}`
    case 'llm_round':
      return `第 ${p.round} 轮 · ${p.chars} 字符 · ${p.usage?.prompt_tokens ?? 0}+${p.usage?.completion_tokens ?? 0} tokens`
    case 'tool_call':
      return `${p.name} ${String(p.args ?? '').slice(0, 100)}`
    case 'tool_result':
      return `${p.name} · ${p.ok ? '成功' : '失败'} · ${p.ms}ms`
    case 'edit_proposal':
      return `${(p.files ?? []).join('，')}${p.staged ? '（待批准）' : '（已应用）'}`
    case 'edit_applied':
    case 'edit_reverted':
    case 'edit_rejected':
      return `${(p.files ?? p.restored ?? []).join('，') || p.edit_id || ''}`
    case 'error':
      return `${p.code ?? ''} ${p.message ?? ''}`.trim()
    case 'done':
      return `${p.rounds} 轮 · ${(p.tools_used ?? []).join('、') || '无工具'} · ${p.elapsed_ms}ms`
    default:
      return JSON.stringify(p).slice(0, 160)
  }
}

export function TrajectoryDrawer({
  sessionId,
  open,
  onClose,
}: {
  sessionId: string | null
  open: boolean
  onClose: () => void
}) {
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)

  useEffect(() => {
    if (!open || !sessionId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .trajectory(sessionId)
      .then((data) => {
        if (!cancelled) setEvents(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : '加载轨迹失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, sessionId])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-md flex-col border-l border-edge bg-panel shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex h-11 shrink-0 items-center gap-2 border-b border-edge px-3">
          <Activity size={14} className="text-accent" />
          <span className="text-[13px] font-medium">会话轨迹</span>
          <span className="text-[11px] text-dim">{events.length} 个事件</span>
          <button className="ml-auto text-dim hover:text-ink" onClick={onClose} aria-label="关闭">
            <X size={15} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {loading && (
            <p className="flex items-center gap-2 text-[12.5px] text-dim">
              <Spinner /> 加载中…
            </p>
          )}
          {error && <p className="text-[12.5px] text-err">{error}</p>}
          {!loading && !error && events.length === 0 && (
            <p className="text-[12.5px] leading-relaxed text-dim">
              当前会话还没有轨迹。发送一条消息后，这里会记录用户输入、检索、模型轮次、工具调用、审批与结果，可用于回放和排障。
            </p>
          )}

          <ul className="space-y-1.5">
            {events.map((event) => {
              const isOpen = expanded === event.id
              return (
                <li key={event.id} className="rounded-lg border border-edge bg-panel/50">
                  <button
                    className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
                    onClick={() => setExpanded(isOpen ? null : event.id)}
                  >
                    {isOpen ? (
                      <ChevronDown size={12} className="text-dim" />
                    ) : (
                      <ChevronRight size={12} className="text-dim" />
                    )}
                    <Badge tone={KIND_TONE[event.kind] ?? 'dim'}>
                      {KIND_LABEL[event.kind] ?? event.kind}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate text-[11.5px] text-dim">
                      {summarize(event)}
                    </span>
                    <span className="shrink-0 text-[10px] text-dim/60">
                      {event.created_at ? new Date(event.created_at).toLocaleTimeString() : ''}
                    </span>
                  </button>
                  {isOpen && (
                    <pre
                      className={clsx(
                        'max-h-60 overflow-auto border-t border-edge bg-base p-2.5',
                        'font-mono text-[10.5px] leading-relaxed text-dim',
                      )}
                    >
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      </aside>
    </div>
  )
}