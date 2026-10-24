import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import { useState } from 'react'
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

export function ToolCard({ card }: { card: StreamToolCard }) {
  const [open, setOpen] = useState(false)
  const { call, result } = card
  const done = Boolean(result)

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
          {done && result!.ok && <CheckCircle2 size={12} className="text-ok" />}
          {done && !result!.ok && <XCircle size={12} className="text-err" />}
          {done && <span>{result!.ms}ms</span>}
        </span>
      </button>
      {open && (
        <div className="border-t border-edge px-3 py-2 text-[12px]">
          {card.command && (
            <div className="mb-2">
              <p className="mb-1 text-[11px] uppercase tracking-wide text-dim">
                命令{typeof card.exit_code === 'number' ? `（退出码 ${card.exit_code}${card.timedOut ? ' · 超时' : ''}）` : ''}
              </p>
              <pre className="max-h-24 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11.5px] text-dim">
                {card.command}
              </pre>
            </div>
          )}
          {call.args && Object.keys(call.args).length > 0 && (
            <div className="mb-2">
              <p className="mb-1 text-[11px] uppercase tracking-wide text-dim">入参</p>
              <pre className="max-h-40 overflow-auto rounded bg-base p-2 font-mono text-[11.5px] text-dim">
                {JSON.stringify(call.args, null, 2)}
              </pre>
            </div>
          )}
          {result && (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-dim">
                结果 {result.ok ? '' : '（失败）'}
              </p>
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11.5px] text-dim">
                {result.preview}
              </pre>
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
    },
    command: event.command ?? null,
    exit_code: event.exit_code ?? null,
    timedOut: Boolean(event.timed_out),
  }
}
