import clsx from 'clsx'
import { Check, ChevronDown, ChevronRight, Copy, X } from 'lucide-react'
import { useState } from 'react'
import { Spinner } from '../components/common'
import type { StreamToolCard } from '../lib/types'
import { TOOL_CARD_CLASS, toolCommand, toolLabel } from './cards'

function statusOf(card: StreamToolCard): { label: string; tone: 'ok' | 'warn' | 'err' } | null {
  if (!card.result) return null
  if (card.timedOut) return { label: '超时', tone: 'warn' }
  if (!card.result.ok) {
    const text = card.result.preview ?? ''
    if (/拒绝|取消|cancel/i.test(text)) return { label: '已取消', tone: 'warn' }
    return { label: '失败', tone: 'err' }
  }
  return { label: '成功', tone: 'ok' }
}

/** 终端卡：run_code / run_command / install_deps。 */
export function ToolTerminal({
  card,
  onCancel,
}: {
  card: StreamToolCard
  onCancel?: () => void
}) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const result = card.result
  const running = !result
  const command = toolCommand(card)
  const title = command ?? toolLabel(card.call.name)
  const status = statusOf(card)

  const copy = () => {
    if (!command) return
    void navigator.clipboard.writeText(command)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className={TOOL_CARD_CLASS}>
      <div className="flex h-8 items-center">
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-label={`${open ? '收起' : '展开'}命令 ${title}`}
          className="flex h-8 min-w-0 flex-1 items-center gap-2 pl-2.5 pr-1 text-left"
        >
          {open
            ? <ChevronDown size={12} className="shrink-0 text-faint" />
            : <ChevronRight size={12} className="shrink-0 text-faint" />}
          <span className="shrink-0 font-mono text-sm text-accent">$</span>
          <span className="min-w-0 flex-1 truncate font-mono text-sm text-ink" title={title}>{title}</span>
          {running && <Spinner className="h-3 w-3 shrink-0" />}
          {status && (
            <span
              className={clsx(
                'shrink-0 font-mono text-2xs',
                status.tone === 'ok' && 'text-ok',
                status.tone === 'warn' && 'text-warn',
                status.tone === 'err' && 'text-err',
              )}
            >
              {status.label}
            </span>
          )}
          {result && <span className="shrink-0 font-mono text-2xs text-faint">{result.ms}ms</span>}
        </button>
        {command && (
          <button
            type="button"
            onClick={copy}
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-faint transition-colors duration-150 hover:text-ink"
            title="复制命令"
            aria-label="复制命令"
          >
            {copied ? <Check size={11} className="text-ok" /> : <Copy size={11} />}
          </button>
        )}
        {running && onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="mr-1 flex h-6 shrink-0 items-center gap-0.5 rounded-sm border border-edge px-1.5 font-mono text-2xs text-faint transition-colors duration-150 hover:border-err/50 hover:text-err"
            title="取消这个工具"
          >
            <X size={10} /> 取消
          </button>
        )}
      </div>

      {running && card.output && (
        <pre className="max-h-16 overflow-hidden whitespace-pre-wrap break-words border-t border-edge/60 px-2.5 py-1.5 font-mono text-2xs leading-relaxed text-dim">
          {card.output.slice(-600)}
        </pre>
      )}

      {open && (
        <div className="space-y-2 border-t border-edge/60 px-2.5 py-2">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-2xs text-faint">
            {status && (
              <span
                className={clsx(
                  status.tone === 'ok' && 'text-ok',
                  status.tone === 'warn' && 'text-warn',
                  status.tone === 'err' && 'text-err',
                )}
              >
                {status.label}
              </span>
            )}
            {typeof card.exit_code === 'number' && <span>退出码 {card.exit_code}</span>}
            {card.timedOut && <span className="text-warn">已超时</span>}
            {result && <span>{result.ms}ms</span>}
            <span className="text-faint/70">#{card.call.round}</span>
          </div>

          {result?.stdout_tail && (
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
              {result.stdout_tail}
            </pre>
          )}
          {result?.stderr_tail && (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-err/90">
              {result.stderr_tail}
            </pre>
          )}
          {result && !result.ok && result.preview && (
            <p className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-err">
              {result.preview}
            </p>
          )}
          {running && card.output && (
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
              {card.output}
            </pre>
          )}
          {running && !card.output && (
            <p className="font-mono text-xs text-faint">等待输出…</p>
          )}
          {result && result.ok && !result.stdout_tail && !result.stderr_tail && result.preview && (
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
              {result.preview}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
