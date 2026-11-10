import clsx from 'clsx'

/** 点阵尺寸：3 行 × 9 列，2px 点 + 2px 间距，整体 34×10，正好当一个图标用。 */
const COLS = 9
const ROWS = 3
/** 每列的相位偏移，斜向流动；行间再错开半格，读起来是两道交错的波。 */
const STEP = 0.09

/**
 * Agent 工作状态的点阵指示器。
 *
 * 旋转圆环只说明"有东西在转"，点阵的流动更像"正在逐个处理"。纯 CSS
 * 动画，没有 canvas 或 rAF 常驻循环；`prefers-reduced-motion` 下由
 * globals.css 的全局兜底把动画压到一帧，元素回到基态（满不透明度的静态点阵），
 * 仍然是一个可读的图形而不是空白。
 */
export function DotLoader({ className }: { className?: string }) {
  return (
    <span
      className={clsx('inline-flex shrink-0 flex-col gap-[2px]', className)}
      aria-hidden="true"
    >
      {Array.from({ length: ROWS }, (_, row) => (
        <span key={row} className="flex gap-[2px]">
          {Array.from({ length: COLS }, (_, col) => (
            <span
              key={col}
              className="h-[2px] w-[2px] rounded-full bg-accent"
              style={{
                animation: 'nova-dot 1.5s ease-in-out infinite',
                animationDelay: `${((col + row * 0.5) * STEP).toFixed(2)}s`,
              }}
            />
          ))}
        </span>
      ))}
    </span>
  )
}
