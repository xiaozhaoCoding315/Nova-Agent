import { ChevronDown, ChevronRight, CheckCircle2, XCircle, Loader2 } from 'lucide-react'
import { useState } from 'react'
import type { StreamToolCard } from '../lib/types'

const TOOL_LABELS: Record<string, string> = {
  run_code: '沙箱执行代码',
  diagnose_error: '解析报错',
  search_code: '检索代码',
  json_tool: 'JSON/YAML 处理',
  sql_tool: 'SQL 审阅',
  fetch_url: '抓取网页',
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
        <span className="font-medium text-ink">{TOOL_LABELS[call.name] ?? call.name}</span>
        <span className="font-mono text-[11px] text-dim">{call.name}</span>
        <span className="ml-auto flex items-center gap-2 text-[11px] text-dim">
          {!done && <Loader2 size={12} className="animate-spin text-accent" />}
          {done && result!.ok && <CheckCircle2 size={12} className="text-ok" />}
          {done && !result!.ok && <XCircle size={12} className="text-err" />}
          {done && <span>{result!.ms}ms</span>}
        </span>
      </button>
      {open && (
        <div className="border-t border-edge px-3 py-2 text-[12px]">
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