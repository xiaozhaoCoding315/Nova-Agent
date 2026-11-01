import { ChevronDown, ChevronRight, Search } from 'lucide-react'
import { useState } from 'react'
import { Spinner } from '../components/common'
import type { StreamToolCard } from '../lib/types'
import {
  TOOL_CARD_CLASS, parsePreviewJson, searchHitCount, searchPaths, toolLabel, toolQuery,
} from './cards'

/** 检索卡：search_code / grep / glob / impact_analysis / diagnose_error。 */
export function SearchCard({
  card,
  onOpenFile,
}: {
  card: StreamToolCard
  onOpenFile?: (path: string) => void
}) {
  const [open, setOpen] = useState(false)
  const query = toolQuery(card) ?? toolLabel(card.call.name)
  const parsed = parsePreviewJson(card.result?.preview)
  const paths = searchPaths(card)
  const visible = paths.slice(0, 5)
  const hits = searchHitCount(parsed) ?? (paths.length > 0 ? paths.length : null)
  const running = !card.result

  return (
    <div className={TOOL_CARD_CLASS}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={`${open ? '收起' : '展开'}检索 ${query}`}
        className="flex h-8 w-full items-center gap-2 px-2.5 text-left"
      >
        {open
          ? <ChevronDown size={12} className="shrink-0 text-faint" />
          : <ChevronRight size={12} className="shrink-0 text-faint" />}
        <Search size={12} className="shrink-0 text-faint" />
        <span className="min-w-0 flex-1 truncate font-mono text-sm text-ink" title={query}>{query}</span>
        {running && <Spinner className="h-3 w-3 shrink-0" />}
        {!running && hits != null && (
          <span className="shrink-0 font-mono text-2xs text-dim">{hits} 命中</span>
        )}
        {card.result && !card.result.ok && (
          <span className="shrink-0 font-mono text-2xs text-err">失败</span>
        )}
        {card.result && (
          <span className="shrink-0 font-mono text-2xs text-faint">{card.result.ms}ms</span>
        )}
      </button>

      {open && (
        <div className="border-t border-edge/60 px-2.5 py-2">
          {card.result && !card.result.ok && card.result.preview && (
            <p className="mb-2 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-err">
              {card.result.preview}
            </p>
          )}
          {visible.length > 0 ? (
            <ul className="space-y-0.5">
              {visible.map((path) => (
                <li key={path}>
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
                </li>
              ))}
            </ul>
          ) : running ? (
            <p className="font-mono text-xs text-faint">检索中…</p>
          ) : (
            card.result?.preview && card.result.ok ? (
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
                {card.result.preview}
              </pre>
            ) : null
          )}
          {paths.length > visible.length && (
            <p className="mt-1 font-mono text-2xs text-faint">还有 {paths.length - visible.length} 条命中</p>
          )}
        </div>
      )}
    </div>
  )
}
