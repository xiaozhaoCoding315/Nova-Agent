import clsx from 'clsx'
import { BookOpen, Code2 } from 'lucide-react'
import { useProduct, type ProductMode } from '../stores/product'

const MODES: { value: ProductMode; label: string; hint: string; icon: typeof Code2 }[] = [
  {
    value: 'dev',
    label: '开发',
    hint: '开发模式：代码库、对话、红绿任务与部署',
    icon: Code2,
  },
  {
    value: 'thesis',
    label: '论文',
    hint: '论文模式：DOCX 格式体检、引用核验与报告',
    icon: BookOpen,
  },
]

export function ProductModeSwitch({ compact = false }: { compact?: boolean }) {
  const mode = useProduct((state) => state.mode)
  const setMode = useProduct((state) => state.setMode)

  return (
    <div
      role="tablist"
      aria-label="产品模式"
      className="flex shrink-0 items-center rounded-md border border-edge bg-base/60 p-0.5"
    >
      {MODES.map((item) => {
        const Icon = item.icon
        const active = mode === item.value
        return (
          <button
            key={item.value}
            role="tab"
            aria-selected={active}
            onClick={() => setMode(item.value)}
            title={item.hint}
            className={clsx(
              'flex h-6 items-center gap-1 rounded-sm px-2 font-mono text-2xs transition-colors duration-150',
              active
                ? 'bg-accentSoft text-accent'
                : 'text-faint hover:bg-raised hover:text-ink',
            )}
          >
            <Icon size={11} />
            <span className={compact ? 'hidden sm:inline' : ''}>{item.label}</span>
          </button>
        )
      })}
    </div>
  )
}
