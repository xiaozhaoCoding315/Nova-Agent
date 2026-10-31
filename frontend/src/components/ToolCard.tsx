import { ChevronDown, ChevronRight, CheckCircle2, Copy, Check, XCircle, Loader2, ExternalLink } from 'lucide-react'
import { useMemo, useState } from 'react'
import { highlightCode, languageFromPath } from '../lib/highlight'
import type { StreamToolCard, ToolEvent } from '../lib/types'

const TOOL_LABELS: Record<string, string> = {
  run_code: '沙箱执行代码',
  read_file: '读取文件',
  list_files: '列出文件',
  read_uploaded_file: '读取附件',
  search_code: '检索代码',
  impact_analysis: '影响分析',
  diagnose_error: '解析报错',
  write_files: '写入文件',
  edit_file: '精确编辑文件',
  grep: '正则搜索',
  glob: '查找文件',
  install_deps: '安装依赖',
  json_tool: 'JSON/YAML 处理',
  sql_tool: 'SQL 审阅',
  fetch_url: '抓取网页',
}

export function toolLabel(name: string): string {
  if (TOOL_LABELS[name]) return TOOL_LABELS[name]
  if (name.startsWith('mcp__')) return `外部工具 ${name.split('__')[1] ?? name}`
  return name
}

export function ToolCard({
  card,
  onCancel,
  onOpenFile,
}: {
  card: StreamToolCard
  onCancel?: () => void
  onOpenFile?: (path: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const { call, result } = card
  const done = Boolean(result)
  const command = card.command
    ?? (typeof call.args?.command === 'string' ? call.args.command : null)
  const filePath = typeof call.args?.path === 'string' ? call.args.path : null
  const hasTerminal = Boolean(result?.stdout_tail || result?.stderr_tail)
  const highlighted = useMemo(() => {
    if (!result?.content_preview) return null
    return highlightCode(result.content_preview, languageFromPath(filePath ?? ''))
  }, [result?.content_preview, filePath])

  const copy = (text: string) => {
    void navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className="my-1.5 overflow-hidden rounded-lg border border-edge bg-panel/70">
      <button
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12.5px] hover:bg-raised"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown size={13} className="text-dim" /> : <ChevronRight size={13} className="text-dim" />}
        <span className="font-medium text-ink">{toolLabel(call.name)}</span>
        <span className="font-mono text-[11px] text-dim">{call.name}</span>
        {typeof call.round === 'number' && (
          <span className="rounded bg-raised px-1.5 py-px font-mono text-[10px] text-dim">第 {call.round} 轮</span>
        )}
        <span className="ml-auto flex min-w-fit items-center gap-2 text-[11px] text-dim">
          {!done && <Loader2 size={12} className="animate-spin text-accent" />}
          {!done && onCancel && (
            <span
              role="button"
              tabIndex={0}
              onClick={(event) => {
                event.stopPropagation()
                onCancel()
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.stopPropagation()
                  onCancel()
                }
              }}
              className="rounded border border-edge px-1.5 py-0.5 text-[10px] text-dim transition-colors hover:border-err/50 hover:text-err"
              title="取消这个工具"
            >
              取消
            </span>
          )}
          {done && result!.ok && <CheckCircle2 size={12} className="text-ok" />}
          {done && !result!.ok && <XCircle size={12} className="text-err" />}
          {done && <span>{result!.ms}ms</span>}
        </span>
      </button>
      {open && (
        <div className="border-t border-edge px-3 py-2 text-[12px]">
          {command && (
            <div className="mb-2">
              <div className="mb-1 flex items-center gap-2 text-[11px] uppercase tracking-wide text-dim">
                <span>
                  命令{typeof card.exit_code === 'number' ? `（退出码 ${card.exit_code}${card.timedOut ? ' · 超时' : ''}）` : ''}
                </span>
                <button
                  onClick={() => copy(command)}
                  className="ml-auto text-dim transition-colors hover:text-ink"
                  title="复制命令"
                  aria-label="复制命令"
                >
                  {copied ? <Check size={11} /> : <Copy size={11} />}
                </button>
              </div>
              <pre className="max-h-24 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11.5px] text-dim">
                {command}
              </pre>
            </div>
          )}
          {filePath && onOpenFile && (
            <button
              onClick={() => onOpenFile(filePath)}
              className="mb-2 flex items-center gap-1 rounded-lg border border-edge px-2 py-1 text-[11px] text-dim transition-colors hover:border-accentSoft hover:text-ink"
            >
              <ExternalLink size={11} /> 在工作区打开 {filePath}
            </button>
          )}
          {call.args && Object.keys(call.args).length > 0 && (
            <div className="mb-2">
              <p className="mb-1 text-[11px] uppercase tracking-wide text-dim">入参</p>
              <pre className="max-h-40 overflow-auto rounded bg-base p-2 font-mono text-[11.5px] text-dim">
                {JSON.stringify(call.args, null, 2)}
              </pre>
            </div>
          )}
          {!result && card.output && (
            <div className="mb-2">
              <p className="mb-1 text-[11px] uppercase tracking-wide text-dim">实时输出</p>
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11.5px] text-dim">
                {card.output}
              </pre>
            </div>
          )}
          {result && (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-dim">
                结果 {result.ok ? '' : '（失败）'}
              </p>
              {result.content_preview ? (
                <div>
                  <div className="mb-1 flex items-center gap-2 text-[10.5px] text-dim">
                    <span className="font-mono">{filePath ?? '文件内容'}</span>
                    <button
                      onClick={() => copy(result.content_preview ?? '')}
                      className="ml-auto flex items-center gap-1 hover:text-ink"
                      title="复制内容"
                    >
                      {copied ? <Check size={11} /> : <Copy size={11} />}
                    </button>
                  </div>
                  {highlighted ? (
                    <pre className="max-h-80 overflow-auto rounded bg-[#0d1117] p-2 font-mono text-[11.5px] leading-relaxed">
                      <code className="hljs bg-transparent p-0" dangerouslySetInnerHTML={{ __html: highlighted }} />
                    </pre>
                  ) : (
                    <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11.5px] text-dim">
                      {result.content_preview}
                    </pre>
                  )}
                  <p className="mt-1 text-[10px] text-dim/60">预览前 3000 字符；点击上方按钮打开工作区查看全文。</p>
                </div>
              ) : hasTerminal ? (
                <div className="space-y-1.5">
                  {result?.stdout_tail && (
                    <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11.5px] text-dim">
                      {result.stdout_tail}
                    </pre>
                  )}
                  {result?.stderr_tail && (
                    <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11.5px] text-err/90">
                      {result.stderr_tail}
                    </pre>
                  )}
                </div>
              ) : (
                <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11.5px] text-dim">
                  {result.preview}
                </pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** Adapter that renders a persisted tool_event with the same collapsible card. */
export function eventToCard(event: ToolEvent, index: number): StreamToolCard {
  return {
    call: {
      id: `event-${index}`,
      name: event.name,
      args: event.args ?? {},
      round: event.round ?? 0,
    },
    result: {
      id: `event-${index}`,
      name: event.name,
      ok: event.ok,
      ms: event.ms,
      preview: event.error ? `错误：${event.error}` : (event.preview ?? ''),
      stdout_tail: event.stdout_tail ?? null,
      stderr_tail: event.stderr_tail ?? null,
      content_preview: event.content_preview ?? null,
    },
    command: event.command ?? null,
    exit_code: event.exit_code ?? null,
    timedOut: Boolean(event.timed_out),
  }
}
