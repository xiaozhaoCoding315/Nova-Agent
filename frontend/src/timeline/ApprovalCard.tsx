import { AlertTriangle, Check, ChevronDown, ChevronRight, X } from 'lucide-react'
import { useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { ToolApproval } from '../lib/types'
import { toolLabel } from './cards'

/**
 * 审批卡：卡片本身可聚焦；仅在卡片获得焦点时 Enter 批准、Escape 拒绝。
 * 子元素（按钮、参数折叠）获得焦点时交给它们自己的键盘行为。
 */
export function ApprovalCard({
  approval,
  onResolve,
}: {
  approval: ToolApproval
  onResolve: (approved: boolean) => void
}) {
  const [argsOpen, setArgsOpen] = useState(false)
  const hasArgs = Object.keys(approval.args ?? {}).length > 0

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return
    if (event.key === 'Enter') {
      event.preventDefault()
      onResolve(true)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      onResolve(false)
    }
  }

  return (
    <div
      tabIndex={0}
      role="group"
      aria-label={`需要你确认：${toolLabel(approval.name)}`}
      onKeyDown={onKeyDown}
      className="rounded-md border border-edge border-l-2 border-l-warn bg-panel/60 p-2.5 transition-colors duration-150 focus-visible:border-warn/70"
    >
      <div className="flex items-center gap-1.5">
        <AlertTriangle size={13} className="shrink-0 text-warn" />
        <span className="text-sm font-medium text-ink">需要你确认</span>
        <span className="truncate font-mono text-xs text-dim">{toolLabel(approval.name)}</span>
        <span className="ml-auto shrink-0 font-mono text-2xs text-faint">Enter 批准 · Esc 拒绝</span>
      </div>

      {approval.reason && (
        <p className="mt-1 text-sm leading-relaxed text-dim">{approval.reason}</p>
      )}

      {hasArgs && (
        <div className="mt-1.5">
          <button
            type="button"
            onClick={() => setArgsOpen((value) => !value)}
            aria-expanded={argsOpen}
            className="flex items-center gap-1 font-mono text-2xs text-faint transition-colors duration-150 hover:text-ink"
          >
            {argsOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            {argsOpen ? '收起参数' : '查看参数'}
          </button>
          {argsOpen && (
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
              {JSON.stringify(approval.args, null, 2)}
            </pre>
          )}
        </div>
      )}

      <div className="mt-2 flex items-center gap-2">
        <button
          type="button"
          onClick={() => onResolve(true)}
          className="flex h-7 items-center gap-1 rounded-sm bg-accent px-2.5 font-medium text-base transition-colors duration-150 hover:bg-accent/85"
        >
          <Check size={12} /> 批准
        </button>
        <button
          type="button"
          onClick={() => onResolve(false)}
          className="flex h-7 items-center gap-1 rounded-sm border border-err/40 px-2.5 text-sm text-err transition-colors duration-150 hover:bg-err/10"
        >
          <X size={12} /> 拒绝
        </button>
      </div>
    </div>
  )
}
