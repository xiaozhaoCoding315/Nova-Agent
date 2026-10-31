import { AlertTriangle, Check, X } from 'lucide-react'
import type { ToolApproval } from '../lib/types'
import { toolLabel } from './ToolCard'

export function ApprovalCard({
  approval,
  onResolve,
}: {
  approval: ToolApproval
  onResolve: (approved: boolean) => void
}) {
  const command = typeof approval.args.command === 'string' ? approval.args.command : null
  const payload = command ?? JSON.stringify(approval.args, null, 2)

  return (
    <div className="my-2 rounded-xl border border-warn/40 bg-warn/5 p-3">
      <div className="flex items-center gap-1.5 text-[12px] font-medium text-ink">
        <AlertTriangle size={13} className="text-warn" />
        <span>需要你批准：{toolLabel(approval.name)}</span>
      </div>
      <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11.5px] text-dim">
        {payload}
      </pre>
      <p className="mt-1.5 text-[11px] leading-relaxed text-dim">{approval.reason}</p>
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => onResolve(true)}
          className="flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1 text-[11.5px] text-white transition-colors hover:bg-accent/85"
        >
          <Check size={12} /> 批准执行
        </button>
        <button
          onClick={() => onResolve(false)}
          className="flex items-center gap-1 rounded-lg border border-edge px-2.5 py-1 text-[11.5px] text-dim transition-colors hover:border-err/50 hover:text-err"
        >
          <X size={12} /> 拒绝
        </button>
      </div>
    </div>
  )
}
