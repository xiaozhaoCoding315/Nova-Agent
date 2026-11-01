import clsx from 'clsx'
import { AlertTriangle, ChevronDown, ChevronRight, FlaskConical } from 'lucide-react'
import { useState } from 'react'
import type { Evidence } from '../lib/types'

const STATUS_LABEL: Record<string, string> = {
  verified: '已核对',
  missing: '未找到',
  out_of_range: '行号越界',
  unchecked: '未校验',
}

/** 证据条：一行计数，展开后是逐条引用。 */
export function EvidenceStrip({
  evidence,
  onOpenFile,
}: {
  evidence: Evidence
  onOpenFile?: (path: string) => void
}) {
  const [open, setOpen] = useState(false)
  const total = evidence.citations.length
  const issues = evidence.missing + evidence.out_of_range

  if (total === 0 && !evidence.executed) return null

  return (
    <div className="overflow-hidden rounded-md border border-edge bg-panel/60 transition-colors duration-150 hover:border-faint/70">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={`${open ? '收起' : '展开'}证据引用`}
        className="flex h-8 w-full items-center gap-2 px-2.5 text-left font-mono text-xs"
      >
        {open
          ? <ChevronDown size={12} className="shrink-0 text-faint" />
          : <ChevronRight size={12} className="shrink-0 text-faint" />}
        <span className="shrink-0 text-dim">证据 {total}</span>
        {evidence.verified > 0 && (
          <>
            <span className="shrink-0 text-faint/60">·</span>
            <span className="shrink-0 text-accent">已核对 {evidence.verified}</span>
          </>
        )}
        {issues > 0 && (
          <>
            <span className="shrink-0 text-faint/60">·</span>
            <span className="flex shrink-0 items-center gap-0.5 text-err">
              <AlertTriangle size={10} /> 可疑 {issues}
            </span>
          </>
        )}
        {evidence.executed && (
          <>
            <span className="shrink-0 text-faint/60">·</span>
            <span className="flex shrink-0 items-center gap-0.5 text-accent">
              <FlaskConical size={10} /> 实测
            </span>
          </>
        )}
        {evidence.skipped > 0 && (
          <>
            <span className="hidden shrink-0 text-faint/60 sm:inline">·</span>
            <span className="hidden shrink-0 text-faint sm:inline">未校验 {evidence.skipped}</span>
          </>
        )}
      </button>

      {open && (
        <ul className="space-y-0.5 border-t border-edge px-2.5 py-1.5 font-mono text-2xs">
          {evidence.citations.map((citation, index) => {
            const label = `${citation.path}:${citation.line}`
            return (
              <li key={`${label}-${index}`} className="flex items-center gap-2">
                <span
                  className={clsx(
                    'shrink-0 rounded-sm px-1',
                    citation.status === 'verified' && 'bg-accent/10 text-accent',
                    citation.status === 'missing' && 'bg-err/10 text-err',
                    citation.status === 'out_of_range' && 'bg-warn/10 text-warn',
                    citation.status === 'unchecked' && 'bg-raised text-faint',
                  )}
                >
                  {STATUS_LABEL[citation.status] ?? citation.status}
                </span>
                {onOpenFile ? (
                  <button
                    type="button"
                    onClick={() => onOpenFile(citation.resolved_path ?? citation.path)}
                    className="min-w-0 flex-1 truncate text-left text-dim transition-colors duration-150 hover:text-ink"
                    title={citation.resolved_path ?? citation.path}
                  >
                    {label}
                  </button>
                ) : (
                  <span className="min-w-0 flex-1 truncate text-dim" title={citation.path}>{label}</span>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
