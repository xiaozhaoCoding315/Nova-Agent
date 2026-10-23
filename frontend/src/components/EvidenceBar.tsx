import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, FlaskConical, HelpCircle } from 'lucide-react'
import { useState } from 'react'
import type { Evidence } from '../lib/types'

const STATUS_LABEL: Record<string, string> = {
  verified: '已核对',
  missing: '未找到',
  out_of_range: '行号越界',
  unchecked: '未校验',
}

export function EvidenceBar({ evidence }: { evidence: Evidence }) {
  const [open, setOpen] = useState(false)
  const issues = evidence.missing + evidence.out_of_range
  const total = evidence.citations.length

  if (total === 0 && !evidence.executed) return null

  return (
    <div className="mt-2 rounded-lg border border-edge bg-panel/50">
      <div className="flex flex-wrap items-center gap-2 px-2.5 py-1.5 text-[11.5px]">
        <span className="text-dim">证据</span>
        {evidence.verified > 0 && (
          <span className="flex items-center gap-1 text-ok">
            <CheckCircle2 size={11} /> {evidence.verified} 处引用已核对
          </span>
        )}
        {evidence.executed && (
          <span className="flex items-center gap-1 text-accent">
            <FlaskConical size={11} /> 沙箱实测
          </span>
        )}
        {issues > 0 && (
          <span className="flex items-center gap-1 text-err">
            <AlertTriangle size={11} /> {issues} 处引用可疑
          </span>
        )}
        {evidence.skipped > 0 && (
          <span className="flex items-center gap-1 text-dim">
            <HelpCircle size={11} /> {evidence.skipped} 处未校验（未关联仓库）
          </span>
        )}
        {total > 0 && (
          <button className="ml-auto text-[11px] text-dim hover:text-ink" onClick={() => setOpen(!open)}>
            {open ? '收起' : '查看引用'}
          </button>
        )}
      </div>
      {open && (
        <ul className="space-y-0.5 border-t border-edge px-2.5 py-1.5 font-mono text-[11px]">
          {evidence.citations.map((c, i) => (
            <li key={`${c.path}-${c.line}-${i}`} className="flex items-center gap-2">
              <span
                className={clsx(
                  'rounded px-1',
                  c.status === 'verified' && 'bg-ok/15 text-ok',
                  c.status === 'missing' && 'bg-err/15 text-err',
                  c.status === 'out_of_range' && 'bg-warn/15 text-warn',
                  c.status === 'unchecked' && 'bg-raised text-dim',
                )}
              >
                {STATUS_LABEL[c.status]}
              </span>
              <span className="truncate text-dim" title={c.resolved_path ?? c.path}>
                {c.path}:{c.line}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}