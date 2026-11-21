import { BookOpen, Settings } from 'lucide-react'
import { ProductModeSwitch } from '../components/ProductModeSwitch'
import { StatusDot } from '../components/common'
import type { Health, Usage } from '../lib/types'

export function ThesisHeader({
  onOpenSettings,
  healthState,
  health,
  usage,
}: {
  onOpenSettings: () => void
  healthState: 'ok' | 'warn' | 'err'
  health: Health | null
  usage: Usage | null
}) {
  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-edge bg-panel/60 px-3 font-mono">
      <div className="flex min-w-0 items-center gap-2">
        <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accentSoft">
          <BookOpen size={13} className="text-accent" />
        </div>
        <span className="text-sm font-medium uppercase tracking-[0.12em]">NOVA</span>
        <span className="hidden rounded-sm border border-accent/30 bg-accentSoft/40 px-1.5 py-0.5 text-2xs text-accent sm:inline">
          论文模式
        </span>
      </div>

      <ProductModeSwitch />

      <div className="ml-auto flex shrink-0 items-center gap-2">
        <span
          className="hidden items-center gap-1.5 px-1 text-xs text-dim sm:flex"
          title={`${health?.status === 'ok' ? '服务正常' : '服务状态待确认'}${health?.version ? ` · v${health.version}` : ''}${usage ? ` · 今日 ${usage.today_tokens.toLocaleString()} tokens` : ''}`}
        >
          <StatusDot state={healthState} />
          <span className="hidden text-2xs text-faint xl:inline">
            {health?.version ? `v${health.version}` : '服务'}
          </span>
          {usage && (
            <span className="hidden text-2xs text-faint xl:inline">
              {usage.today_tokens.toLocaleString()} tok
            </span>
          )}
        </span>
        <button
          onClick={onOpenSettings}
          className="flex h-7 w-7 items-center justify-center rounded-md border border-edge text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink"
          title="模型与密钥"
          aria-label="打开模型与密钥设置"
        >
          <Settings size={13} />
        </button>
      </div>
    </header>
  )
}
