import { ArrowUp, Check, Cpu, Plus, ShieldCheck, Slash } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

/** 轮播的示例提问：都是本项目真实能做、且结果可核验的活。 */
const PROMPTS = [
  '修复 orders 列表的 N+1 查询',
  '这个仓库的鉴权是怎么串起来的？',
  '把 tools/ 下的重复校验抽成一个函数',
]

const TYPE_MS = 62
const HOLD_MS = 2200

/**
 * 宣传页的 hero 演示：一张与真实输入框同版式的卡片，提示词逐字打出来。
 *
 * 只借用输入框的排布（圆形 `+`、权限胶囊、上下文圆环、模型胶囊、圆形发送），
 * 不复制任何交互逻辑——这里没有输入框、没有会话，点它只会滚到登录按钮。
 * `prefers-reduced-motion` 下停在第一句完整提示词上，不做逐字动画。
 */
export function HeroComposer({ onStart }: { onStart: () => void }) {
  const [text, setText] = useState('')
  const [promptIndex, setPromptIndex] = useState(0)
  const [reduced, setReduced] = useState(false)
  const timer = useRef<number | null>(null)

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)')
    const sync = () => setReduced(query.matches)
    sync()
    query.addEventListener('change', sync)
    return () => query.removeEventListener('change', sync)
  }, [])

  useEffect(() => {
    if (reduced) {
      setText(PROMPTS[0])
      return
    }
    const target = PROMPTS[promptIndex]
    let cancelled = false

    const schedule = (fn: () => void, delay: number) => {
      timer.current = window.setTimeout(() => {
        if (!cancelled) fn()
      }, delay)
    }

    if (text.length < target.length) {
      schedule(() => setText(target.slice(0, text.length + 1)), TYPE_MS)
    } else if (text === target) {
      schedule(() => {
        // 打完后先停一会儿让人读完，再整句退格。
        setText('')
        setPromptIndex((index) => (index + 1) % PROMPTS.length)
      }, HOLD_MS + target.length * 8)
    }

    return () => {
      cancelled = true
      if (timer.current) window.clearTimeout(timer.current)
    }
  }, [text, promptIndex, reduced])

  const typing = text.length > 0 && text.length < PROMPTS[promptIndex].length

  return (
    <div className="relative min-w-0">
      <div className="overflow-hidden rounded-lg border border-edge bg-panel shadow-pop transition-colors duration-150 hover:border-faint/60">
        <div className="px-3.5 pb-1 pt-3">
          <p className="min-h-[3.75rem] text-md leading-relaxed text-ink">
            {text || <span className="text-faint">问代码、贴报错，或让 Nova 修改并真实运行验证…</span>}
            {typing && <span className="ml-0.5 inline-block h-[1em] w-[2px] translate-y-[2px] bg-accent align-middle" />}
          </p>
        </div>

        <div className="flex items-center gap-0.5 px-1.5 pb-1.5 pt-0.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-full text-dim">
            <Plus size={16} />
          </span>
          <span className="flex h-8 w-8 items-center justify-center rounded-full text-dim">
            <Slash size={15} />
          </span>
          <span className="flex h-8 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-xs text-dim">
            <ShieldCheck size={13} />
            请求批准
          </span>
          <span className="flex h-7 w-7 items-center justify-center" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 18 18" className="-rotate-90">
              <circle cx="9" cy="9" r="6.5" fill="none" strokeWidth="2" className="stroke-edge" />
              <circle
                cx="9"
                cy="9"
                r="6.5"
                fill="none"
                strokeWidth="2"
                strokeLinecap="round"
                stroke="currentColor"
                strokeDasharray="40.84"
                strokeDashoffset="28"
                className="text-accent"
              />
            </svg>
          </span>

          <span className="ml-auto flex min-w-0 items-center gap-0.5">
            <span className="flex h-8 min-w-0 items-center gap-1.5 rounded-full px-2.5 text-xs text-dim">
              <Cpu size={13} className="shrink-0" />
              <span className="truncate font-mono">glm-4.6</span>
              <span className="shrink-0 text-faint">·</span>
              <span className="shrink-0">中</span>
            </span>
            <button
              type="button"
              onClick={onStart}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-graphite transition-colors duration-150 hover:bg-accent/85"
              aria-label="开始使用 Nova Agent"
            >
              <ArrowUp size={16} />
            </button>
          </span>
        </div>
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-2xs text-faint">
        <span className="flex items-center gap-1.5">
          <Check size={11} className="text-accent" />
          引用已核验
        </span>
        <span className="flex items-center gap-1.5">
          <Check size={11} className="text-accent" />
          命令真实执行
        </span>
        <span className="flex items-center gap-1.5">
          <Check size={11} className="text-accent" />
          补丁待你批准
        </span>
      </div>
    </div>
  )
}
