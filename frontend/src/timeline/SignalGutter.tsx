import type { Evidence } from '../lib/types'

/**
 * 证据信号轨：每一轮的数字编号、工具刻度与证据点。
 * 28px（移动端 20px），左侧 1px 竖线；流式进行时竖线变 accent，
 * 结束后 600ms 渐隐回 edge（一次性，不循环）。
 */
export function SignalGutter({
  index,
  tools,
  evidence,
  active,
}: {
  index: number
  tools: number
  evidence?: Evidence | null
  active?: boolean
}) {
  const label = `T${String(index).padStart(2, '0')}`
  const visible = Math.min(Math.max(tools, 0), 6)
  const overflow = Math.max(tools - 6, 0)

  return (
    <div
      className="relative w-5 shrink-0 self-stretch border-l border-edge md:w-7"
      aria-hidden="true"
    >
      <span
        className={`absolute inset-y-0 left-0 w-px bg-accent transition-opacity duration-[600ms] ease-out ${
          active ? 'opacity-100' : 'opacity-0'
        }`}
      />
      <div className="flex flex-col gap-1 pl-0.5 pt-0.5 md:pl-1.5">
        <span className="font-mono text-2xs leading-none text-faint">{label}</span>
        {tools > 0 && (
          <span className="flex max-w-full flex-wrap content-start gap-0.5">
            {Array.from({ length: visible }).map((_, tick) => (
              <span key={tick} className="h-[3px] w-[3px] bg-dim/70" />
            ))}
            {overflow > 0 && (
              <span className="font-mono text-2xs leading-none text-faint">+{overflow}</span>
            )}
          </span>
        )}
      </div>
      {evidence && evidence.verified > 0 && (
        <span
          className="absolute bottom-1 left-1 h-1 w-1 rounded-full bg-ok md:left-1.5"
          title={`${evidence.verified} 处证据已核对`}
        />
      )}
    </div>
  )
}
