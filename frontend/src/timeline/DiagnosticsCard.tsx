import { AlertTriangle, ChevronDown, ChevronRight, Info, ListChecks, XCircle } from 'lucide-react'
import { useState } from 'react'
import { Spinner } from '../components/common'
import type { StreamToolCard } from '../lib/types'
import { TOOL_CARD_CLASS, parsePreviewJson } from './cards'

type Severity = 'error' | 'warning' | 'info'

type Diagnostic = {
  path: string
  line: number
  column: number
  severity: Severity
  code: string
  message: string
}

type DiagnosticsPayload = {
  tool?: string
  summary?: { files?: number; errors?: number; warnings?: number; total?: number }
  truncated?: boolean
  parse_errors?: number
  warning?: string | null
  duration_ms?: number
  diagnostics?: Diagnostic[]
  raw_tail?: string
}

const SEVERITY_ICON = { error: XCircle, warning: AlertTriangle, info: Info } as const
const SEVERITY_CLASS: Record<Severity, string> = {
  error: 'text-err',
  warning: 'text-warn',
  info: 'text-faint',
}

/** 诊断卡：ruff / mypy / tsc 的结构化结果，按文件分组。 */
export function DiagnosticsCard({
  card,
  onOpenFile,
}: {
  card: StreamToolCard
  onOpenFile?: (path: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [showRaw, setShowRaw] = useState(false)
  const running = !card.result
  const payload = parsePreviewJson(card.result?.preview) as DiagnosticsPayload | null
  const diagnostics: Diagnostic[] = payload && Array.isArray(payload.diagnostics)
    ? payload.diagnostics
    : []
  const summary = payload?.summary
  const runner = payload?.tool
    ?? (typeof card.call.args.tool === 'string' && card.call.args.tool !== ''
      ? card.call.args.tool
      : '')
  const parseErrors = payload?.parse_errors ?? 0
  const unstructured = parseErrors > 0 || payload?.truncated === true
  const groups = new Map<string, Diagnostic[]>()
  for (const item of diagnostics) {
    const list = groups.get(item.path) ?? []
    list.push(item)
    groups.set(item.path, list)
  }

  return (
    <div className={TOOL_CARD_CLASS}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={`${open ? '收起' : '展开'}运行诊断${runner ? ` ${runner}` : ''}`}
        className="flex h-8 w-full items-center gap-2 px-2.5 text-left"
      >
        {open
          ? <ChevronDown size={12} className="shrink-0 text-faint" />
          : <ChevronRight size={12} className="shrink-0 text-faint" />}
        <ListChecks size={12} className="shrink-0 text-faint" />
        <span className="min-w-0 flex-1 truncate text-sm text-ink">
          运行诊断{runner ? ` · ${runner}` : ''}
        </span>
        {running && <Spinner className="h-3 w-3 shrink-0" />}
        {!running && summary && (
          <span className="shrink-0 font-mono text-2xs text-dim">
            {summary.errors ?? 0} 错误 · {summary.warnings ?? 0} 警告
          </span>
        )}
        {card.result && !card.result.ok && (
          <span className="shrink-0 font-mono text-2xs text-err">失败</span>
        )}
        {card.result && (
          <span className="shrink-0 font-mono text-2xs text-faint">
            {payload?.duration_ms ?? card.result.ms}ms
          </span>
        )}
      </button>

      {open && (
        <div className="space-y-2 border-t border-edge/60 px-2.5 py-2">
          {card.result && !card.result.ok && card.result.preview && (
            <p className="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-err">
              {card.result.preview}
            </p>
          )}
          {payload?.warning && (
            <p className="rounded-sm border border-warn/40 bg-warn/5 px-2 py-1 text-xs leading-relaxed text-warn">
              {payload.warning}
            </p>
          )}
          {running && <p className="font-mono text-xs text-faint">诊断运行中…</p>}
          {!running && diagnostics.length === 0 && card.result?.ok && payload && !unstructured && (
            <p className="font-mono text-xs text-faint">没有发现问题。</p>
          )}
          {!running && diagnostics.length === 0 && card.result?.ok && payload && unstructured && (
            <p className="font-mono text-xs text-faint">未解析出结构化诊断，见下方原文。</p>
          )}
          {Array.from(groups.entries()).map(([path, items]) => (
            <div key={path} className="space-y-0.5">
              {onOpenFile ? (
                <button
                  type="button"
                  onClick={() => onOpenFile(path)}
                  className="block w-full truncate rounded-sm px-1 py-0.5 text-left font-mono text-xs text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
                  title={`在抽屉打开 ${path}`}
                >
                  {path}
                </button>
              ) : (
                <span className="block truncate px-1 py-0.5 font-mono text-xs text-dim">{path}</span>
              )}
              <ul className="space-y-0.5 pl-3">
                {items.map((item, index) => {
                  const Icon = SEVERITY_ICON[item.severity] ?? Info
                  return (
                    <li key={`${item.line}:${item.column}:${item.code}:${index}`} className="flex gap-1.5">
                      <Icon size={11} className={`mt-0.5 shrink-0 ${SEVERITY_CLASS[item.severity] ?? 'text-faint'}`} />
                      <span className="shrink-0 font-mono text-2xs text-faint">
                        {item.line}:{item.column}
                      </span>
                      {item.code && (
                        <span className="shrink-0 font-mono text-2xs text-dim">{item.code}</span>
                      )}
                      <span className="min-w-0 flex-1 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-dim">
                        {item.message}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))}
          {payload?.truncated && (
            <p className="font-mono text-2xs text-faint">诊断较多，仅显示前 {diagnostics.length} 条。</p>
          )}
          {(payload?.parse_errors ?? 0) > 0 && (
            <div>
              <button
                type="button"
                onClick={() => setShowRaw((value) => !value)}
                aria-expanded={showRaw}
                className="font-mono text-2xs text-faint transition-colors duration-150 hover:text-ink"
              >
                另有 {payload?.parse_errors} 行无法解析{showRaw ? '（收起）' : '（展开）'}
              </button>
              {showRaw && payload?.raw_tail && (
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
                  {payload.raw_tail}
                </pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
