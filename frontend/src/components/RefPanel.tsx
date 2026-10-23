import { Check, Copy, FileCode2 } from 'lucide-react'
import { useState } from 'react'
import type { RetrievalHit } from '../lib/types'

function HitRow({ hit }: { hit: RetrievalHit }) {
  const [copied, setCopied] = useState(false)
  const location = hit.path ? `${hit.path}:${hit.line_start}` : '片段'

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${hit.path}:${hit.line_start}-${hit.line_end}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="group rounded-lg border border-edge bg-panel/60 p-2.5">
      <div className="flex items-center gap-1.5">
        <FileCode2 size={12} className="shrink-0 text-accent" />
        <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-ink" title={location}>
          {location}
        </span>
        <button className="text-dim/60 hover:text-ink" onClick={copy} aria-label="复制引用">
          {copied ? <Check size={11} className="text-ok" /> : <Copy size={11} />}
        </button>
      </div>
      <div className="mt-1 flex items-center gap-2 text-[10.5px] text-dim">
        <span
          className={
            hit.source.includes('dense')
              ? 'rounded bg-accentSoft/50 px-1 text-accent'
              : 'rounded bg-raised px-1 text-dim'
          }
        >
          {hit.source === 'dense'
            ? '语义'
            : hit.source === 'keyword'
              ? '关键词'
              : hit.source.includes('+')
                ? '混合'
                : hit.source}
        </span>
        <span>相关度 {(hit.score * 100).toFixed(0)}%</span>
      </div>
      {hit.snippet && (
        <p className="mt-1.5 line-clamp-4 whitespace-pre-wrap font-mono text-[10.5px] leading-relaxed text-dim/90">
          {hit.snippet}
        </p>
      )}
    </div>
  )
}

export function RefPanel({ refs }: { refs: RetrievalHit[] }) {
  return (
    <div className="flex h-full flex-col">
      <p className="px-3 py-2.5 text-[12px] font-medium uppercase tracking-wide text-dim">
        引用来源 {refs.length > 0 && <span className="text-accent">{refs.length}</span>}
      </p>
      <div className="flex-1 space-y-2 overflow-y-auto px-3 pb-3">
        {refs.length === 0 && (
          <p className="text-[12px] leading-relaxed text-dim">
            回答涉及代码时，检索到的「文件:行号」会显示在这里，可一键复制引用。
          </p>
        )}
        {refs.map((hit, i) => (
          <HitRow key={`${hit.path}-${hit.line_start}-${i}`} hit={hit} />
        ))}
      </div>
    </div>
  )
}