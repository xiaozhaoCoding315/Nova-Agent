import clsx from 'clsx'
import { useCallback, useEffect, useRef, useState } from 'react'

const KEY_PREFIX = 'nova.rail.width.'

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function readWidth(key: string, fallback: number, min: number, max: number): number {
  try {
    const raw = localStorage.getItem(KEY_PREFIX + key)
    const parsed = raw ? Number(raw) : NaN
    return Number.isFinite(parsed) ? clamp(parsed, min, max) : fallback
  } catch {
    return fallback
  }
}

/**
 * 侧栏宽度：记住用户拖出来的宽度，双击复位。
 *
 * 只在桌面断点生效——窄屏下两侧栏是覆盖层，宽度由视口决定，
 * 用户拖出来的宽度留到下次回到宽屏时再用。
 */
export function useRailWidth({
  key,
  initial,
  min,
  max,
  media = '(min-width: 1024px)',
}: {
  key: string
  initial: number
  min: number
  max: number
  media?: string
}) {
  const [width, setWidth] = useState(() => readWidth(key, initial, min, max))
  const [active, setActive] = useState(() => window.matchMedia(media).matches)

  useEffect(() => {
    const query = window.matchMedia(media)
    const onChange = () => setActive(query.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [media])

  const update = useCallback(
    (next: number) => {
      const value = clamp(Math.round(next), min, max)
      setWidth(value)
      try {
        localStorage.setItem(KEY_PREFIX + key, String(value))
      } catch {
        /* 存不下就只在本次会话生效 */
      }
      return value
    },
    [key, min, max],
  )

  const reset = useCallback(() => update(initial), [update, initial])

  return { width, active, update, reset }
}

/**
 * 侧栏拖拽把手。4px 宽的可聚焦分隔条，命中区比视觉宽度宽一点，
 * 键盘 `←/→` 调 16px、`Home`/`End` 到头、双击复位。
 *
 * `side` 是把手相对侧栏的位置：`left` 用于右栏（把手在左边缘，
 * 向左拖变宽），`right` 用于左栏。
 */
export function RailResizer({
  side,
  width,
  min,
  max,
  onChange,
  onReset,
  label,
  className,
}: {
  side: 'left' | 'right'
  width: number
  min: number
  max: number
  onChange: (next: number) => number
  onReset: () => void
  label: string
  className?: string
}) {
  const drag = useRef<{ startX: number; startWidth: number } | null>(null)
  const [dragging, setDragging] = useState(false)

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    event.preventDefault()
    drag.current = { startX: event.clientX, startWidth: width }
    setDragging(true)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = drag.current
    if (!state) return
    const delta = event.clientX - state.startX
    onChange(state.startWidth + (side === 'left' ? -delta : delta))
  }

  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    drag.current = null
    setDragging(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const forward = side === 'left' ? 'ArrowLeft' : 'ArrowRight'
    const back = side === 'left' ? 'ArrowRight' : 'ArrowLeft'
    if (event.key === forward) onChange(width + 16)
    else if (event.key === back) onChange(width - 16)
    else if (event.key === 'Home') onChange(min)
    else if (event.key === 'End') onChange(max)
    else return
    event.preventDefault()
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      title="拖动调整宽度，双击复位"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      className={clsx(
        // 4px 命中区用负外边距吃掉自身宽度，正好骑在侧栏边界上：
        // 视觉上是一条线，鼠标不用瞄准 1px。
        'group relative -mx-0.5 w-1 shrink-0 cursor-col-resize touch-none outline-none',
        className,
      )}
    >
      {/* 视觉上是一条 1px 的分隔线，hover/拖动时才亮起来，不抢占两侧的呼吸感。 */}
      <span
        className={clsx(
          'absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors duration-150',
          dragging ? 'bg-accent' : 'bg-edge group-hover:bg-faint group-focus-visible:bg-accent',
        )}
      />
    </div>
  )
}
