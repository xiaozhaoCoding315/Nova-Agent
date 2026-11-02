import {
  AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, FileCode2, XCircle,
} from 'lucide-react'
import { useState } from 'react'
import { Markdown } from '../components/Markdown'
import { Spinner } from '../components/common'
import type { SubagentRun } from '../lib/types'

const STATUS_LABEL: Record<SubagentRun['status'], string> = {
  running: '进行中',
  ok: '完成',
  partial: '部分完成',
  failed: '失败',
  timeout: '超时',
}

function formatMs(ms?: number): string {
  if (!ms) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function StatusIcon({ status }: { status: SubagentRun['status'] }) {
  if (status === 'running') return <Spinner className="h-3 w-3" />
  if (status === 'ok') return <CheckCircle2 size={12} className="text-ok" />
  if (status === 'partial') return <AlertTriangle size={12} className="text-warn" />
  return <XCircle size={12} className="text-err" />
}

function SubagentRow({
  run,
  onOpenFile,
}: {
  run: SubagentRun
  onOpenFile?: (path: string) => void
}) {
  const [open, setOpen] = useState(run.status === 'running')
  const findings = run.findings ?? []

  return (
    <div className="overflow-hidden rounded-md border border-edge bg-panel/60">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex h-8 w-full items-center gap-2 px-2.5 text-left"
      >
        {open
          ? <ChevronDown size={12} className="shrink-0 text-faint" />
          : <ChevronRight size={12} className="shrink-0 text-faint" />}
        <StatusIcon status={run.status} />
        <span className="min-w-0 flex-1 truncate text-sm text-ink">{run.title}</span>
        <span className="shrink-0 font-mono text-2xs text-faint">
          {STATUS_LABEL[run.status]}
        </span>
        {typeof run.rounds === 'number' && run.rounds > 0 && (
          <span className="hidden shrink-0 font-mono text-2xs text-faint sm:inline">
            第 {run.rounds} 轮
          </span>
        )}
        {run.tools && run.tools.length > 0 && (
          <span className="hidden shrink-0 font-mono text-2xs text-faint sm:inline">
            {run.tools.length} 个工具
          </span>
        )}
        {run.ms ? (
          <span className="shrink-0 font-mono text-2xs text-faint">{formatMs(run.ms)}</span>
        ) : null}
      </button>

      {open && (
        <div className="space-y-2 border-t border-edge/60 px-2.5 py-2">
          {run.error && (
            <p className="rounded-sm border border-err/30 bg-err/5 px-2 py-1.5 text-xs leading-relaxed text-err">
              {run.error}
            </p>
          )}
          {run.summary ? (
            <Markdown content={run.summary} />
          ) : (
            <p className="flex items-center gap-2 text-xs text-dim">
              {run.status === 'running' ? <><Spinner className="h-3 w-3" /> 正在调研…</> : '没有总结。'}
            </p>
          )}
          {findings.length > 0 && (
            <div>
              <p className="mb-1 font-mono text-2xs uppercase tracking-[0.12em] text-faint">
                关键发现
              </p>
              <div className="space-y-1">
                {findings.map((finding, index) => {
                  const location = finding.file
                    ? `${finding.file}${finding.line ? `:${finding.line}` : ''}`
                    : null
                  return (
                    <button
                      key={`${run.id}-finding-${index}`}
                      type="button"
                      disabled={!finding.file || !onOpenFile}
                      onClick={() => finding.file && onOpenFile?.(finding.file)}
                      className="flex w-full items-start gap-1.5 rounded-sm px-1.5 py-1 text-left transition-colors duration-150 hover:bg-raised disabled:cursor-default"
                    >
                      <FileCode2 size={11} className="mt-0.5 shrink-0 text-faint" />
                      <span className="min-w-0 flex-1">
                        {location && (
                          <code className="mr-1.5 font-mono text-2xs text-accent">{location}</code>
                        )}
                        <span className="text-xs leading-relaxed text-dim">{finding.detail}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          )}
          {run.citations && (
            <p className="font-mono text-2xs text-faint">
              引用校验 {run.citations.verified} 通过
              {run.citations.missing > 0 ? ` · ${run.citations.missing} 缺失` : ''}
              {run.citations.out_of_range > 0 ? ` · ${run.citations.out_of_range} 越界` : ''}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export function SubagentPanel({
  runs,
  onOpenFile,
}: {
  runs: SubagentRun[]
  onOpenFile?: (path: string) => void
}) {
  if (runs.length === 0) return null
  return (
    <div className="space-y-1.5" aria-label="子代理">
      {runs.map((run) => (
        <SubagentRow key={run.id} run={run} onOpenFile={onOpenFile} />
      ))}
    </div>
  )
}
