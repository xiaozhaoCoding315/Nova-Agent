import clsx from 'clsx'
import { useEffect, useRef } from 'react'

const LENGTH = 6

/**
 * 6 位数字验证码分格输入。
 *
 * 每个格子是一个真 `<input>`：密码管理器、短信/邮件自动填充、输入法都能
 * 正常识别，不必和 `contenteditable` 搏斗。粘贴 6 位会一次填满（这是
 * 最常见的操作，也是普通输入框唯一做得比它好的地方），`Backspace`
 * 空一格时回退到上一格，左右方向键可以在格子间移动。
 *
 * 只在本地 `error` 变化时抖一下：抖动是"这次提交失败"的信号，不是
 * 输入过程中的噪音。
 */
export function OtpInput({
  value,
  onChange,
  invalid = false,
  shakeKey = 0,
  autoFocus = false,
  disabled = false,
  label = '邮箱验证码',
}: {
  value: string
  onChange: (next: string) => void
  /** 由外部在提交失败时置 true，用来标红。 */
  invalid?: boolean
  /**
   * 每次自增重放一次抖动。用计数器而不是 `invalid` 布尔：连续两次失败时
   * 布尔一直是 true，class 没变，动画不会重放。
   */
  shakeKey?: number
  autoFocus?: boolean
  disabled?: boolean
  label?: string
}) {
  const refs = useRef<(HTMLInputElement | null)[]>([])
  const digits = value.padEnd(LENGTH, ' ').slice(0, LENGTH).split('')

  useEffect(() => {
    if (autoFocus) refs.current[0]?.focus()
  }, [autoFocus])

  const focusAt = (index: number) => {
    const target = Math.min(LENGTH - 1, Math.max(0, index))
    refs.current[target]?.focus()
    refs.current[target]?.select()
  }

  /** 写入第 index 格起的字符，返回新的值。 */
  const write = (index: number, chars: string) => {
    const next = value.padEnd(LENGTH, ' ').split('')
    for (let offset = 0; offset < chars.length && index + offset < LENGTH; offset += 1) {
      next[index + offset] = chars[offset]
    }
    return next.join('').trimEnd()
  }

  const handleChange = (index: number, raw: string) => {
    const chars = raw.replace(/\D/g, '')
    if (!chars) return
    // 一次输入多个字符（自动填充 / 输入法 / 粘贴被浏览器拦成 input 事件）时整体写入。
    onChange(write(index, chars))
    focusAt(index + chars.length)
  }

  const handleKeyDown = (index: number, event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Backspace') {
      event.preventDefault()
      const next = value.padEnd(LENGTH, ' ').split('')
      if (next[index] && next[index] !== ' ') {
        next[index] = ' '
        onChange(next.join('').trimEnd())
        focusAt(index)
      } else {
        next[index - 1] = ' '
        onChange(next.join('').trimEnd())
        focusAt(index - 1)
      }
      return
    }
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      focusAt(index - 1)
    } else if (event.key === 'ArrowRight') {
      event.preventDefault()
      focusAt(index + 1)
    } else if (event.key === 'Delete') {
      event.preventDefault()
      const next = value.padEnd(LENGTH, ' ').split('')
      next[index] = ' '
      onChange(next.join('').trimEnd())
    }
  }

  const handlePaste = (event: React.ClipboardEvent<HTMLDivElement>) => {
    const text = event.clipboardData.getData('text').replace(/\D/g, '').slice(0, LENGTH)
    if (!text) return
    event.preventDefault()
    onChange(text)
    focusAt(text.length)
  }

  return (
    <div role="group" aria-label={label} onPaste={handlePaste}>
      {/* key 变化即重挂载整组，抖动关键帧随之重放；比手写 classList 更稳。 */}
      <div key={shakeKey} className={clsx('flex w-full gap-1.5', invalid && 'nova-shake')}>
        {digits.map((digit, index) => {
          const filled = digit.trim() !== ''
          return (
            <input
              key={index}
              ref={(node) => { refs.current[index] = node }}
              value={filled ? digit : ''}
              onChange={(event) => handleChange(index, event.target.value)}
              onKeyDown={(event) => handleKeyDown(index, event)}
              onFocus={(event) => event.target.select()}
              disabled={disabled}
              inputMode="numeric"
              autoComplete={index === 0 ? 'one-time-code' : 'off'}
              aria-label={`${label}第 ${index + 1} 位`}
              maxLength={1}
              className={clsx(
                'h-10 w-full min-w-0 rounded-md border bg-base/40 text-center font-mono text-md tabular-nums text-ink outline-none transition-colors duration-150',
                'focus:border-accent/60 focus:bg-base',
                invalid ? 'border-err/60' : filled ? 'border-edge' : 'border-edge/70',
                disabled && 'opacity-50',
              )}
            />
          )
        })}
      </div>
    </div>
  )
}
