import clsx from 'clsx'
import { ChevronDown, ChevronRight, ClipboardCheck, Terminal } from 'lucide-react'
import { useState } from 'react'
import type { DeliveryReport as Report } from '../lib/types'
import { Badge } from './common'

const STATUS: Record<
  Report['status'],
  { label: string; tone: 'ok' | 'warn' | 'dim' | 'err' }
> = {
  verified: { label: '已验证', tone: 'ok' },
  partial: { label: '部分验证', tone: 'warn' },
  unverified: { label: '未验证', tone: 'dim' },
  failed: { label: '执行失败', tone: 'err' },
}

const FILE_STATUS: Record<string, string> = {
  pending: '待批准',
  applied: '已写入',
  rejected: '已拒绝',
  reverted: '已撤销',
}

export function DeliveryReport({ report }: { report: Report | null | undefined }) {
  const [open, setOpen] = useState(false)
  if (!report) return null
  const meta = STATUS[report.status] ?? STATUS.unverified

  return (
    <div className="my-2 rounded-lg border border-edge bg-panel/50">
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen(!open)}
      >
        <ClipboardCheck size={13} className="text-accent" />
        <span className="text-[12px] font-medium">交付报告</span>
        <Badge tone={meta.tone}>{meta.label}</Badge>
        <span className="min-w-0 flex-1 truncate text-[11px] text-dim">
          {report.stats.tools.length} 个工具 · {report.commands.length} 条命令 ·{' '}
          {report.stats.prompt_tokens + report.stats.completion_tokens} tokens ·{' '}
          {(report.stats.elapsed_ms / 1000).toFixed(1)}s
        </span>
        {open ? <ChevronDown size={13} className="text-dim" /> : <ChevronRight size={13} className="text-dim" />}
      </button>
      {open && (
        <div className="space-y-3 border-t border-edge px-3 py-2.5">
          <div>
            <p className="mb-1 text-[11px] uppercase tracking-wide text-dim">检查结果</p>
            <div className="grid gap-1.5 sm:grid-cols-3">
              {report.checks.map((check) => (
                <div key={check.name} className="rounded-md border border-edge bg-base/50 px-2 py-1.5">
                  <p className="flex items-center gap-1.5 text-[11.5px]">
                    <span
                      className={clsx(
                        'h-1.5 w-1.5 rounded-full',
                        check.status === 'passed' && 'bg-ok',
                        check.status === 'failed' && 'bg-err',
                        check.status === 'skipped' && 'bg-dim',
                      )}
                    />
                    {check.name}
                  </p>
                  <p className="mt-0.5 text-[10.5px] text-dim">{check.detail}</p>
                </div>
              ))}
            </div>
          </div>

          {report.commands.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-1 text-[11px] uppercase tracking-wide text-dim">
                <Terminal size={10} /> 执行命令
              </p>
              <ul className="space-y-1">
                {report.commands.map((cmd, i) => (
                  <li key={i} className="flex items-start gap-2 rounded bg-base/50 px-2 py-1 font-mono text-[10.5px]">
                    <span className={cmd.ok ? 'text-ok' : 'text-err'}>
                      {cmd.exit_code === null || cmd.exit_code === undefined ? '—' : cmd.exit_code}
                    </span>
                    <span className="min-w-0 flex-1 break-all text-dim">{cmd.command}</span>
                    <span className="shrink-0 text-dim/70">{cmd.ms}ms</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {report.files_changed.length > 0 && (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-dim">改动文件</p>
              <ul className="space-y-1 font-mono text-[11px] text-dim">
                {report.files_changed.map((file) => (
                  <li key={file.path} className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate">{file.path}</span>
                    <span>{FILE_STATUS[file.status] ?? file.status}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {report.unverified.length > 0 && (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-warn">未验证 / 注意事项</p>
              <ul className="list-disc space-y-0.5 pl-4 text-[11.5px] text-dim">
                {report.unverified.map((item, i) => <li key={i}>{item}</li>)}
              </ul>
            </div>
          )}

          <p className="text-[10.5px] text-dim/70">
            引用核对 {report.citations.verified} 处 · 异常{' '}
            {report.citations.missing + report.citations.out_of_range} 处 · 权限模式{' '}
            {report.permission_mode}
          </p>
        </div>
      )}
    </div>
  )
}
