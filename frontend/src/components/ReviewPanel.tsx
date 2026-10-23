import clsx from 'clsx'
import { ChevronDown, ChevronRight, ShieldAlert, ShieldCheck, ShieldX } from 'lucide-react'
import { useState } from 'react'
import type { Review, ReviewFinding } from '../lib/types'
import { Badge } from './common'

const VERDICT: Record<
  Review['verdict'],
  { label: string; tone: 'ok' | 'warn' | 'err'; icon: typeof ShieldCheck }
> = {
  pass: { label: '审查通过', tone: 'ok', icon: ShieldCheck },
  warn: { label: '需要关注', tone: 'warn', icon: ShieldAlert },
  block: { label: '阻止交付', tone: 'err', icon: ShieldX },
}

function FindingRow({ item }: { item: ReviewFinding }) {
  return (
    <li className="rounded-md border border-edge bg-base/50 px-2.5 py-1.5">
      <p className="text-[12px] leading-relaxed text-ink">{item.issue}</p>
      <p className="mt-0.5 font-mono text-[10.5px] text-dim">
        {item.file ? `${item.file}${item.line ? `:${item.line}` : ''}` : '整体'}
      </p>
      {item.suggestion && <p className="mt-0.5 text-[11.5px] text-dim">建议：{item.suggestion}</p>}
    </li>
  )
}

export function ReviewPanel({ review }: { review: Review | null | undefined }) {
  const [open, setOpen] = useState(true)
  if (!review) return null
  const meta = VERDICT[review.verdict] ?? VERDICT.warn
  const Icon = meta.icon
  const blocking = review.blocking ?? []
  const nonBlocking = review.non_blocking ?? []
  const evidence = review.evidence ?? []

  return (
    <div className="my-2 rounded-lg border border-edge bg-panel/70">
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen(!open)}
      >
        <Icon size={14} className={clsx(
          meta.tone === 'ok' && 'text-ok',
          meta.tone === 'warn' && 'text-warn',
          meta.tone === 'err' && 'text-err',
        )} />
        <span className="text-[12.5px] font-medium">只读审查</span>
        <Badge tone={meta.tone}>{meta.label}</Badge>
        <span className="min-w-0 flex-1 truncate text-[11.5px] text-dim">{review.summary}</span>
        {open ? <ChevronDown size={13} className="text-dim" /> : <ChevronRight size={13} className="text-dim" />}
      </button>
      {open && (
        <div className="space-y-2 border-t border-edge px-3 py-2">
          {blocking.length > 0 && (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-err">Blocking</p>
              <ul className="space-y-1.5">
                {blocking.map((item, i) => <FindingRow key={`b-${i}`} item={item} />)}
              </ul>
            </div>
          )}
          {nonBlocking.length > 0 && (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-dim">Non-blocking</p>
              <ul className="space-y-1.5">
                {nonBlocking.map((item, i) => <FindingRow key={`n-${i}`} item={item} />)}
              </ul>
            </div>
          )}
          {evidence.length > 0 && (
            <div>
              <p className="mb-1 text-[11px] uppercase tracking-wide text-dim">依据</p>
              <ul className="list-disc space-y-0.5 pl-4 text-[11.5px] text-dim">
                {evidence.map((item, i) => <li key={`e-${i}`}>{item}</li>)}
              </ul>
            </div>
          )}
          {blocking.length === 0 && nonBlocking.length === 0 && (
            <p className="text-[11.5px] text-dim">没有发现需要修复的问题。</p>
          )}
        </div>
      )}
    </div>
  )
}
