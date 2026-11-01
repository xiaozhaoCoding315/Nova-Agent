import clsx from 'clsx'
import {
  Check, ChevronDown, Command, Cpu, FolderTree, GitBranch, PanelLeft, Plus, ShieldCheck,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { StatusDot } from '../components/common'
import { ModelPicker, useModelPicker } from '../composer/ModelPicker'
import { api } from '../lib/api'
import type { GitInfo, Health, PermissionMode, RepoStatus, Usage } from '../lib/types'
import { useChat } from '../stores/chat'
import { useLlm } from '../stores/llm'
import { useRepos } from '../stores/repos'

const PERMISSIONS: { value: PermissionMode; label: string; hint: string }[] = [
  { value: 'readonly', label: '计划模式', hint: '只读探索，不改动文件' },
  { value: 'ask', label: '变更前确认', hint: '写入或执行前先询问' },
  { value: 'auto', label: '自主模式', hint: '自动执行，可随时停止' },
  { value: 'full', label: '完全访问', hint: '跳过确认，谨慎使用' },
]

const REPO_STATUS_LABEL: Record<RepoStatus, string> = {
  pending: '排队中',
  indexing: '索引中…',
  ready: '',
  failed: '索引失败',
  planning: '规划中…',
  plan_ready: '待确认方案',
  approved: '已确认方案',
  generating: '生成中…',
  review: '待审阅',
}

const HEALTH_LABEL = {
  ok: '服务正常',
  warn: '部分降级',
  err: '服务不可用',
} as const

export function ChatHeader({
  onOpenRail,
  onNewChat,
  onOpenPalette,
  onOpenSettings,
  onOpenWorkspace,
  healthState,
  health,
  usage,
}: {
  onOpenRail: () => void
  onNewChat: () => void
  onOpenPalette: () => void
  onOpenSettings: () => void
  onOpenWorkspace: (repoId?: string) => void
  healthState: 'ok' | 'warn' | 'err'
  health: Health | null
  usage: Usage | null
}) {
  const historyRepoId = useChat((state) => state.historyRepoId)
  const selectedRepoIds = useChat((state) => state.selectedRepoIds)
  const permissionMode = useChat((state) => state.permissionMode)
  const setPermissionMode = useChat((state) => state.setPermissionMode)
  const repos = useRepos((state) => state.repos)
  const llmSettings = useLlm((state) => state.settings)
  const picker = useModelPicker()

  const [permissionOpen, setPermissionOpen] = useState(false)
  const [modelOpen, setModelOpen] = useState(false)
  const [gitInfo, setGitInfo] = useState<GitInfo | null>(null)
  const [gitChecked, setGitChecked] = useState(false)

  const currentRepoId = historyRepoId ?? selectedRepoIds[0] ?? null
  const currentRepo = repos.find((repo) => repo.id === currentRepoId) ?? null
  const repoStatus = currentRepo?.status ?? null

  useEffect(() => {
    if (!permissionOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setPermissionOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [permissionOpen])

  useEffect(() => {
    let cancelled = false
    setGitInfo(null)
    setGitChecked(false)
    if (!currentRepoId || repoStatus !== 'ready') return
    api.git
      .status(currentRepoId)
      .then((info) => {
        if (cancelled) return
        setGitInfo(info)
        setGitChecked(true)
      })
      .catch(() => {
        if (!cancelled) setGitChecked(true)
      })
    return () => {
      cancelled = true
    }
  }, [currentRepoId, repoStatus])

  const permission = PERMISSIONS.find((item) => item.value === permissionMode) ?? PERMISSIONS[1]
  const modelLabel = picker.value.provider && picker.value.model
    ? `${picker.value.provider}/${picker.value.model}`
    : llmSettings?.source === 'server'
      ? `服务端/${llmSettings.server_model ?? '默认模型'}`
      : llmSettings?.source === 'user'
        ? [llmSettings.provider, llmSettings.model].filter(Boolean).join('/') || '默认模型'
        : '未配置模型'
  const modelSource = llmSettings?.source === 'user'
    ? '个人密钥'
    : llmSettings?.source === 'server' ? '服务端密钥' : '未配置'
  const sandbox = health?.components.sandbox as { available?: boolean } | undefined

  const gitBranch = gitInfo?.available && gitInfo.initialized
    ? gitInfo.branch ?? 'detached'
    : null

  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-edge bg-panel/60 px-3 font-mono">
      <button
        onClick={onOpenRail}
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink md:hidden"
        title="打开项目栏"
        aria-label="打开项目栏"
      >
        <PanelLeft size={15} />
      </button>

      <div className="flex min-w-0 items-center gap-2">
        <span className="max-w-[180px] truncate text-sm text-ink" title={currentRepo?.name ?? '全部项目'}>
          {currentRepo?.name ?? '全部项目'}
        </span>
        {currentRepo && (
          currentRepo.status === 'ready' ? (
            gitBranch ? (
              <span className="flex min-w-0 items-center gap-1 text-faint">
                <GitBranch size={11} className="shrink-0" />
                <code className="truncate font-mono text-xs text-dim">{gitBranch}</code>
                {gitInfo?.dirty && <span className="shrink-0 text-2xs text-warn">*</span>}
              </span>
            ) : (
              <code className="hidden font-mono text-xs text-faint sm:inline">
                {gitChecked ? '未初始化 Git' : '检查 Git…'}
              </code>
            )
          ) : (
            <span className="hidden text-xs text-faint sm:inline">
              {REPO_STATUS_LABEL[currentRepo.status] || '索引中…'}
            </span>
          )
        )}
      </div>

      <div className="relative">
        <button
          onClick={() => {
            setModelOpen(false)
            setPermissionOpen((value) => !value)
          }}
          className={clsx(
            'flex h-7 items-center gap-1 rounded-md border px-2 text-xs transition-colors duration-150',
            permissionMode === 'full'
              ? 'border-err/40 text-err hover:bg-err/10'
              : 'border-edge text-dim hover:border-accent/40 hover:text-ink',
          )}
          title={`权限：${permission.label} · ${permission.hint}`}
          aria-label={`权限：${permission.label}`}
          aria-haspopup="menu"
          aria-expanded={permissionOpen}
        >
          <ShieldCheck size={12} />
          <span className="hidden sm:inline">{permission.label}</span>
          <ChevronDown size={11} className="text-faint" />
        </button>
        {permissionOpen && (
          <>
            <div className="fixed inset-0 z-30" onClick={() => setPermissionOpen(false)} aria-hidden="true" />
            <div
              role="menu"
              aria-label="权限模式"
              className="absolute left-0 top-full z-40 mt-1.5 w-60 rounded-md border border-edge bg-panel p-1 shadow-pop"
            >
              {PERMISSIONS.map((item) => {
                const active = item.value === permissionMode
                return (
                  <button
                    key={item.value}
                    role="menuitemradio"
                    aria-checked={active}
                    onClick={() => {
                      setPermissionMode(item.value)
                      setPermissionOpen(false)
                    }}
                    className={clsx(
                      'flex w-full items-start gap-2 rounded-sm px-2 py-1.5 text-left transition-colors duration-150',
                      active ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
                    )}
                  >
                    <span className="mt-0.5 w-3 shrink-0 text-accent">
                      {active && <Check size={11} />}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-sm">{item.label}</span>
                      <span className="block text-2xs text-faint">{item.hint}</span>
                    </span>
                  </button>
                )
              })}
            </div>
          </>
        )}
      </div>

      <div className="relative">
        <button
          onClick={() => {
            setPermissionOpen(false)
            setModelOpen((value) => !value)
          }}
          className="flex h-7 min-w-0 items-center gap-1.5 rounded-md border border-edge px-2 text-xs text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink"
          title={`模型：${modelLabel}（${modelSource}）· 仅本会话，点击切换`}
          aria-label={`模型：${modelLabel}，打开模型选择`}
          aria-haspopup="dialog"
          aria-expanded={modelOpen}
        >
          <Cpu size={12} className={llmSettings?.source === 'user' ? 'text-accent' : 'text-faint'} />
          <span className="hidden max-w-[200px] truncate font-mono lg:inline">{modelLabel}</span>
        </button>
        <ModelPicker
          open={modelOpen}
          onClose={() => setModelOpen(false)}
          settings={picker.settings}
          value={picker.value}
          onChange={picker.onChange}
          onSetDefault={picker.onSetDefault}
          reasoningCleared={picker.reasoningCleared}
          onConfigure={() => {
            setModelOpen(false)
            onOpenSettings()
          }}
          placement="below"
        />
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        <button
          onClick={onNewChat}
          className="hidden h-7 items-center gap-1 rounded-md border border-edge px-2 text-xs text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink sm:flex"
          title="新建对话 · Ctrl/⌘ N"
        >
          <Plus size={12} />
          新对话
        </button>
        <button
          onClick={onOpenPalette}
          className="flex h-7 items-center gap-1 rounded-md border border-edge px-2 text-xs text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink"
          title="命令面板 · Ctrl/⌘ K"
          aria-label="打开命令面板"
        >
          <Command size={12} />
          <span className="hidden md:inline">K</span>
        </button>
        <span
          className="flex items-center gap-1.5 px-1 text-xs text-dim"
          title={`${HEALTH_LABEL[healthState]} · v${health?.version ?? '2.0.0'}${sandbox ? ` · 沙箱${sandbox.available ? '可用' : '不可用'}` : ''} · 今日 ${usage ? usage.today_tokens.toLocaleString() : '—'} tokens`}
        >
          <StatusDot state={healthState} />
          <span className="hidden lg:inline">{HEALTH_LABEL[healthState]}</span>
          <span className="hidden text-2xs text-faint xl:inline">
            {usage ? `${usage.today_tokens.toLocaleString()} tok` : '—'}
          </span>
        </span>
        <button
          onClick={() => onOpenWorkspace(currentRepoId ?? undefined)}
          className="flex h-7 w-7 items-center justify-center rounded-md border border-edge text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink"
          title="打开工作区"
          aria-label="打开工作区"
        >
          <FolderTree size={13} />
        </button>
      </div>
    </header>
  )
}
