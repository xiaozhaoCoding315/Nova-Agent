import clsx from 'clsx'
import { ChevronDown, ChevronRight, ClipboardCheck, Terminal } from 'lucide-react'
import { useState } from 'react'
import type { DeliveryReport as Report } from '../lib/types'

const STATUS: Record<Report['status'], { label: string; tone: string }> = {
  verified: { label: '通过', tone: 'text-accent' },
  partial: { label: '部分通过', tone: 'text-warn' },
  unverified: { label: '未验证', tone: 'text-faint' },
  failed: { label: '未通过', tone: 'text-err' },
}

const FILE_STATUS: Record<string, string> = {
  pending: '待批准',
  applied: '已写入',
  rejected: '已拒绝',
  reverted: '已撤销',
}

/** 交付摘要：`交付 · 通过` + 指标网格 + 可折叠的报告正文。 */
export function RunSummary({ report }: { report: Report | null | undefined }) {
  const [open, setOpen] = useState(false)
  if (!report) return null
  const meta = STATUS[report.status] ?? STATUS.unverified
  const tokens = report.stats.prompt_tokens + report.stats.completion_tokens
  const elapsed = report.stats.elapsed_ms >= 1000
    ? `${(report.stats.elapsed_ms / 1000).toFixed(1)}s`
    : `${report.stats.elapsed_ms}ms`

  const metrics = [
    { label: 'tokens', value: tokens.toLocaleString() },
    { label: '工具', value: String(report.stats.tools.length) },
    { label: '耗时', value: elapsed },
  ]

  return (
    <div className="overflow-hidden rounded-md border border-edge bg-panel/60 transition-colors duration-150 hover:border-faint/70">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex h-8 w-full items-center gap-2 px-2.5 text-left"
      >
        {open
          ? <ChevronDown size={12} className="shrink-0 text-faint" />
          : <ChevronRight size={12} className="shrink-0 text-faint" />}
        <ClipboardCheck size={12} className="shrink-0 text-faint" />
        <span className="shrink-0 text-sm text-ink">交付</span>
        <span className={clsx('shrink-0 font-mono text-xs', meta.tone)}>· {meta.label}</span>
        <span className="ml-auto shrink-0 font-mono text-2xs text-faint">
          {report.files_changed.length} 文件 · {report.commands.length} 命令
        </span>
      </button>

      <div className="grid grid-cols-3 gap-1.5 border-t border-edge/60 px-2.5 py-2">
        {metrics.map((metric) => (
          <div key={metric.label} className="rounded-sm border border-edge bg-base/40 px-2 py-1.5">
            <p className="font-mono text-2xs text-faint">{metric.label}</p>
            <p className="mt-0.5 font-mono text-sm text-ink">{metric.value}</p>
          </div>
        ))}
      </div>

      {open && (
        <div className="space-y-3 border-t border-edge/60 px-2.5 py-2.5">
          {report.checks.length > 0 && (
            <div>
              <p className="mb-1 font-mono text-2xs uppercase tracking-[0.12em] text-faint">检查结果</p>
              <div className="grid gap-1 sm:grid-cols-3">
                {report.checks.map((check) => (
                  <div key={check.name} className="rounded-sm border border-edge bg-base/40 px-2 py-1.5">
                    <p className="flex items-center gap-1.5 text-xs text-ink">
                      <span
                        className={clsx(
                          'h-1.5 w-1.5 shrink-0 rounded-full',
                          check.status === 'passed' && 'bg-ok',
                          check.status === 'failed' && 'bg-err',
                          check.status === 'skipped' && 'bg-faint',
                        )}
                      />
                      {check.name}
                    </p>
                    {check.detail && <p className="mt-0.5 text-2xs text-faint">{check.detail}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}

          {report.commands.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-1 font-mono text-2xs uppercase tracking-[0.12em] text-faint">
                <Terminal size={10} /> 执行命令
              </p>
              <ul className="max-h-40 space-y-0.5 overflow-auto">
                {report.commands.map((command, index) => (
                  <li
                    key={`${command.tool}-${index}`}
                    className="flex items-start gap-2 rounded-sm bg-base/40 px-2 py-1 font-mono text-2xs"
                  >
                    <span className={command.ok ? 'text-ok' : 'text-err'}>
                      {command.exit_code == null ? '—' : command.exit_code}
                    </span>
                    <span className="min-w-0 flex-1 break-all text-dim">{command.command}</span>
                    <span className="shrink-0 text-faint">{command.ms}ms</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {report.files_changed.length > 0 && (
            <div>
              <p className="mb-1 font-mono text-2xs uppercase tracking-[0.12em] text-faint">改动文件</p>
              <ul className="space-y-0.5 font-mono text-2xs text-dim">
                {report.files_changed.map((file) => (
                  <li key={file.path} className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate" title={file.path}>{file.path}</span>
                    <span className="shrink-0 text-faint">{FILE_STATUS[file.status] ?? file.status}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {report.unverified.length > 0 && (
            <div>
              <p className="mb-1 font-mono text-2xs uppercase tracking-[0.12em] text-warn">未验证 / 注意事项</p>
              <ul className="list-disc space-y-0.5 pl-4 text-xs leading-relaxed text-dim">
                {report.unverified.map((item, index) => <li key={index}>{item}</li>)}
              </ul>
            </div>
          )}

          {report.errors.length > 0 && (
            <div>
              <p className="mb-1 font-mono text-2xs uppercase tracking-[0.12em] text-err">错误</p>
              <ul className="list-disc space-y-0.5 pl-4 text-xs leading-relaxed text-err/90">
                {report.errors.map((item, index) => <li key={index}>{item}</li>)}
              </ul>
            </div>
          )}

          <p className="font-mono text-2xs text-faint">
            引用核对 {report.citations.verified} 处 · 异常{' '}
            {report.citations.missing + report.citations.out_of_range} 处 · 权限模式{' '}
            {report.permission_mode}
          </p>
        </div>
      )}
    </div>
  )
}
