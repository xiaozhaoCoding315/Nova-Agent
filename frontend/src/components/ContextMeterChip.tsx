import clsx from 'clsx'
import { Gauge } from 'lucide-react'
import { useState } from 'react'
import type { ContextMeter } from '../lib/types'

/** token 数人性化：1234 → 1.2k */
export function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return String(value)
}

function toneOf(pct: number): { bar: string; text: string } {
  if (pct >= 85) return { bar: 'bg-err', text: 'text-err' }
  if (pct >= 60) return { bar: 'bg-warn', text: 'text-warn' }
  return { bar: 'bg-accent', text: 'text-accent' }
}

/**
 * 上下文计量条：显示本轮提示的估算 token 与窗口占比，点击展开构成分解
 * （系统提示 / 检索 / 记忆 / 历史…），对齐桌面端 Agent 的上下文可视化习惯。
 */
export function ContextMeterChip({ meter }: { meter: ContextMeter | null }) {
  const [open, setOpen] = useState(false)
  if (!meter || !meter.window) return null

  const pct = Math.min(100, Math.round((meter.total / meter.window) * 100))
  const tone = toneOf(pct)
  const sections = Object.entries(meter.sections).sort((a, b) => b[1] - a[1])

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={clsx(
          'flex items-center gap-1.5 rounded-lg border bg-raised/70 px-2 py-1 text-[11px] transition-colors',
          open ? 'border-accent/50 text-ink' : 'border-edge/80 text-dim hover:text-ink',
        )}
        title="本轮提示的上下文占用（估算）"
      >
        <Gauge size={12} className={tone.text} />
        <span className="tabular-nums">{formatTokens(meter.total)}</span>
        <span className="text-dim/50">/ {formatTokens(meter.window)}</span>
        <span className="relative hidden h-1 w-10 overflow-hidden rounded-full bg-raised sm:block">
          <span
            className={clsx('absolute inset-y-0 left-0 rounded-full', tone.bar)}
            style={{ width: `${Math.max(3, pct)}%` }}
          />
        </span>
        <span className={clsx('hidden text-[10px] tabular-nums sm:inline', tone.text)}>{pct}%</span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full left-0 z-30 mb-2 w-72 rounded-xl border border-edge bg-panel p-3 shadow-xl">
            <div className="flex items-baseline gap-1.5">
              <span className="text-[12px] font-semibold">本轮上下文</span>
              <span className={clsx('text-[11px] tabular-nums', tone.text)}>
                {formatTokens(meter.total)} / {formatTokens(meter.window)}（{pct}%）
              </span>
            </div>
            <p className="mt-0.5 text-[10px] leading-relaxed text-dim/70">
              按字符估算，实际以模型返回的用量为准
              {meter.actualPromptTokens ? `（本轮实际 ${formatTokens(meter.actualPromptTokens)}）` : ''}。
              接近窗口时可在设置里换更长上下文的模型或清空会话。
            </p>
            <div className="mt-2.5 space-y-1.5">
              {sections.length === 0 && (
                <p className="text-[11px] text-dim">暂无构成数据。</p>
              )}
              {sections.map(([label, tokens]) => {
                const share = meter.total > 0 ? Math.round((tokens / meter.total) * 100) : 0
                return (
                  <div key={label} className="space-y-0.5">
                    <div className="flex items-baseline gap-2 text-[11px]">
                      <span className="min-w-0 flex-1 truncate text-dim">{label}</span>
                      <span className="tabular-nums text-dim/80">{formatTokens(tokens)}</span>
                      <span className="w-8 text-right tabular-nums text-dim/60">{share}%</span>
                    </div>
                    <div className="h-1 overflow-hidden rounded-full bg-raised">
                      <div
                        className="h-full rounded-full bg-accent/70"
                        style={{ width: `${Math.max(2, share)}%` }}
                      />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
