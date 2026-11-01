import { ChevronDown, ChevronRight, ExternalLink, Globe } from 'lucide-react'
import { useState } from 'react'
import { Spinner } from '../components/common'
import type { StreamToolCard } from '../lib/types'
import { TOOL_CARD_CLASS, toolLabel, toolQuery, webResults } from './cards'

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

/** 网络搜索卡：把结果渲染成可点击的外部链接，而不是一段原始 JSON。 */
export function WebSearchCard({ card }: { card: StreamToolCard }) {
  const [open, setOpen] = useState(false)
  const query = toolQuery(card) ?? toolLabel(card.call.name)
  const results = webResults(card)
  const running = !card.result

  return (
    <div className={TOOL_CARD_CLASS}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-label={`${open ? '收起' : '展开'}网络搜索 ${query}`}
        className="flex h-8 w-full items-center gap-2 px-2.5 text-left"
      >
        {open
          ? <ChevronDown size={12} className="shrink-0 text-faint" />
          : <ChevronRight size={12} className="shrink-0 text-faint" />}
        <Globe size={12} className="shrink-0 text-faint" />
        <span className="min-w-0 flex-1 truncate font-mono text-sm text-ink" title={query}>{query}</span>
        {running && <Spinner className="h-3 w-3 shrink-0" />}
        {!running && results.length > 0 && (
          <span className="shrink-0 font-mono text-2xs text-dim">{results.length} 条</span>
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
          {results.length > 0 ? (
            <ul className="space-y-0.5">
              {results.map((result, index) => (
                <li key={`${result.url}-${index}`}>
                  <a
                    href={result.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="group block rounded-sm px-1 py-1.5 transition-colors duration-150 hover:bg-raised"
                    title={result.url}
                  >
                    <span className="flex items-start gap-1.5">
                      <span className="min-w-0 flex-1 text-xs leading-relaxed text-ink">
                        {result.title}
                      </span>
                      <ExternalLink
                        size={11}
                        className="mt-0.5 shrink-0 text-faint transition-colors duration-150 group-hover:text-accent"
                      />
                    </span>
                    <span className="mt-0.5 block truncate font-mono text-2xs text-accent/80">
                      {hostOf(result.url)}
                    </span>
                    {result.snippet && (
                      <span className="mt-1 line-clamp-2 text-2xs leading-relaxed text-dim">
                        {result.snippet}
                      </span>
                    )}
                  </a>
                </li>
              ))}
            </ul>
          ) : running ? (
            <p className="font-mono text-xs text-faint">搜索中…</p>
          ) : (
            card.result?.preview && card.result.ok ? (
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-sm bg-base/70 p-2 font-mono text-xs leading-relaxed text-dim">
                {card.result.preview}
              </pre>
            ) : null
          )}
        </div>
      )}
    </div>
  )
}
