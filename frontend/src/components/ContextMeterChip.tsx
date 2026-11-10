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

/** 圆环半径与周长：18px 画布内留 2px 描边余量。 */
const RING_RADIUS = 6.5
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS

/**
 * 上下文计量：输入框底栏里的一个小圆环，点击展开构成分解
 * （系统提示 / 检索 / 记忆 / 历史…）。
 *
 * 圆环只表达占比，具体数字放在 title 与展开面板里——底栏一行要放
 * 附件、命令、权限、模型、发送，长数字会把模型胶囊挤掉。
 */
export function ContextMeterChip({
  meter,
  repoCount,
}: {
  meter: ContextMeter | null
  /** 关联仓库数；为空时展开面板里不显示这一行。 */
  repoCount?: number
}) {
  const [open, setOpen] = useState(false)
  if (!meter || !meter.window) return null

  const pct = Math.min(100, Math.round((meter.total / meter.window) * 100))
  const tone = toneOf(pct)
  const sections = Object.entries(meter.sections).sort((a, b) => b[1] - a[1])
  const summary = `本轮上下文 ${formatTokens(meter.total)} / ${formatTokens(meter.window)}（${pct}%）`

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className={clsx(
          'flex h-7 w-7 items-center justify-center rounded-full transition-colors duration-150',
          open ? 'bg-raised text-ink' : 'text-dim hover:bg-raised hover:text-ink',
        )}
        title={summary}
        aria-label={summary}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" className="-rotate-90">
          <circle cx="9" cy="9" r={RING_RADIUS} fill="none" strokeWidth="2" className="stroke-edge" />
          <circle
            cx="9"
            cy="9"
            r={RING_RADIUS}
            fill="none"
            strokeWidth="2"
            strokeLinecap="round"
            stroke="currentColor"
            className={tone.text}
            strokeDasharray={RING_CIRCUMFERENCE}
            // 至少留一小段弧，0% 时也看得出这是一个计量环而不是空按钮。
            strokeDashoffset={RING_CIRCUMFERENCE * (1 - Math.max(0.04, pct / 100))}
          />
        </svg>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            role="dialog"
            aria-label="上下文占用"
            className="absolute bottom-full right-0 z-30 mb-2 w-72 rounded-xl border border-edge bg-panel p-3 shadow-xl"
          >
            <div className="flex items-baseline gap-1.5">
              <span className="text-sm font-semibold">本轮上下文</span>
              <span className={clsx('text-xs tabular-nums', tone.text)}>
                {formatTokens(meter.total)} / {formatTokens(meter.window)}（{pct}%）
              </span>
            </div>
            {repoCount != null && (
              <p className="mt-0.5 text-2xs text-dim">
                {repoCount > 0 ? `关联 ${repoCount} 个仓库` : '未关联仓库'}
              </p>
            )}
            <p className="mt-0.5 text-2xs leading-relaxed text-dim/70">
              按字符估算，实际以模型返回的用量为准
              {meter.actualPromptTokens ? `（本轮实际 ${formatTokens(meter.actualPromptTokens)}）` : ''}。
              接近窗口时可在设置里换更长上下文的模型或清空会话。
            </p>
            <div className="mt-2.5 space-y-1.5">
              {sections.length === 0 && (
                <p className="flex items-center gap-1.5 text-xs text-dim">
                  <Gauge size={11} /> 暂无构成数据。
                </p>
              )}
              {sections.map(([label, tokens]) => {
                const share = meter.total > 0 ? Math.round((tokens / meter.total) * 100) : 0
                return (
                  <div key={label} className="space-y-0.5">
                    <div className="flex items-baseline gap-2 text-xs">
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
