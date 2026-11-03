import { useEffect } from 'react'
import type { RefObject } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
  '[contenteditable="true"]',
].join(',')

/**
 * 弹层里当前真正能被 Tab 到的元素。`display:none` / `visibility:hidden`
 * 的元素仍在 DOM 里，但拿不到焦点，所以按是否渲染来过滤。
 */
export function focusableIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE))
    .filter((element) => {
      // offsetParent 为 null 的元素要么没渲染，要么自己是 position:fixed——
      // 后者仍能聚焦，所以两种判断都要看。
      if (element.offsetParent === null && element.getClientRects().length === 0) return false
      const style = window.getComputedStyle(element)
      return style.visibility !== 'hidden' && style.display !== 'none'
    })
}

/**
 * 把焦点关在弹层里：打开时移入、Tab/Shift+Tab 在首尾循环、关闭后还给触发元素。
 *
 * 没有它，键盘用户可以 Tab 到遮罩背后的页面上——屏幕阅读器仍会读那些控件，
 * 视觉上却完全看不见。各弹层的打开/关闭逻辑不同（受控 open、条件渲染），
 * 所以这里只管焦点，不管渲染。
 */
export function useFocusTrap(
  ref: RefObject<HTMLElement>,
  active: boolean,
  { initialFocus }: { initialFocus?: RefObject<HTMLElement> } = {},
) {
  useEffect(() => {
    if (!active) return
    const root = ref.current
    if (!root) return

    const trigger = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    // 没有显式指定时落到弹层本身（它带 tabIndex={-1}），焦点不会停在背景上。
    const target = initialFocus?.current ?? root
    target.focus()

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const items = focusableIn(root)
      if (items.length === 0) {
        event.preventDefault()
        root.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const current = document.activeElement
      if (event.shiftKey) {
        if (current === first || current === root || !root.contains(current)) {
          event.preventDefault()
          last.focus()
        }
        return
      }
      if (current === last || !root.contains(current)) {
        event.preventDefault()
        first.focus()
      }
    }

    // 捕获阶段：弹层内部的输入框也可能自己处理 Tab（自动补全），先在这里兜住。
    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      if (trigger && document.contains(trigger)) trigger.focus()
    }
  }, [ref, active, initialFocus])
}
