import { BookOpen, Briefcase, FileText, GitPullRequest, Settings, Smartphone } from 'lucide-react'
import { ProductModeSwitch } from '../components/ProductModeSwitch'
import { StatusDot } from '../components/common'
import type { Health, Usage } from '../lib/types'

export function ThesisHeader({
  onOpenSettings,
  onOpenDocuments,
  onOpenResume,
  onOpenRemote,
  onOpenGithub,
  remoteUnread,
  healthState,
  health,
  usage,
}: {
  onOpenSettings: () => void
  onOpenDocuments: () => void
  onOpenResume: () => void
  onOpenRemote: () => void
  onOpenGithub: () => void
  remoteUnread: number
  healthState: 'ok' | 'warn' | 'err'
  health: Health | null
  usage: Usage | null
}) {
  const navButton =
    'relative flex h-7 items-center gap-1 rounded-md border border-edge px-2 text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink'
  const navLabel = 'hidden text-2xs xl:inline'
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

      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        <button
          onClick={onOpenDocuments}
          className={navButton}
          title="文档工作区：Markdown、格式转换与导出"
          aria-label="打开文档工作区"
        >
          <FileText size={13} />
          <span className={navLabel}>文档</span>
        </button>
        <button
          onClick={onOpenResume}
          className={navButton}
          title="简历工作台：事实库与岗位版本"
          aria-label="打开简历工作台"
        >
          <Briefcase size={13} />
          <span className={navLabel}>简历</span>
        </button>
        <button
          onClick={onOpenRemote}
          className={navButton}
          title="遥控 / 手机工作台：配对手机、看进度、收通知"
          aria-label="打开遥控与手机工作台"
        >
          <Smartphone size={13} />
          <span className={navLabel}>遥控</span>
          {remoteUnread > 0 && (
            <span className="absolute -right-1 -top-1 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-accent px-1 font-mono text-[9px] text-graphite">
              {remoteUnread > 9 ? '9+' : remoteUnread}
            </span>
          )}
        </button>
        <button
          onClick={onOpenGithub}
          className={navButton}
          title="GitHub 交付：draft PR、CI 与评审意见"
          aria-label="打开 GitHub 交付面板"
        >
          <GitPullRequest size={13} />
          <span className={navLabel}>交付</span>
        </button>
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
