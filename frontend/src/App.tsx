import clsx from 'clsx'
import {
  ArrowLeft, Bot, Command, Cpu, ListTodo, LogOut, MessageSquarePlus, MessagesSquare,
  MonitorDown, PanelLeft, Plus, Settings, X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { CommandPalette, type PaletteAction } from './components/CommandPalette'
import { RecoveryCodeModal } from './components/RecoveryCodeModal'
import { SessionList } from './components/SessionList'
import { StatusDot } from './components/common'
import { api } from './lib/api'
import type { Health, Usage } from './lib/types'
import { useAuth } from './stores/auth'
import { useChat } from './stores/chat'
import { useLlm } from './stores/llm'
import { useRepos } from './stores/repos'
import { ChatView } from './views/ChatView'
import { LoginView } from './views/LoginView'
import { SettingsView } from './views/SettingsView'
import { TasksView } from './views/TasksView'
import { WorkspaceView } from './views/WorkspaceView'

type ViewKey = 'chat' | 'tasks' | 'workspace' | 'settings'

const NAV: { key: ViewKey; label: string; icon: typeof Bot }[] = [
  { key: 'chat', label: '对话', icon: MessagesSquare },
  { key: 'tasks', label: '任务', icon: ListTodo },
  { key: 'settings', label: '设置', icon: Settings },
]

const VIEW_TITLE: Record<ViewKey, string> = {
  chat: '对话',
  tasks: '任务',
  workspace: '工作区',
  settings: '设置',
}

const VIEW_SUBTITLE: Record<ViewKey, string> = {
  chat: '带着证据与仓库上下文对话',
  tasks: '修复与变更，统一推进、验证与审批',
  workspace: '浏览代码与版本历史',
  settings: '模型、用量与账号',
}

const PERMISSION_LABEL: Record<string, string> = {
  readonly: '计划模式',
  ask: '变更前确认',
  auto: '自主模式',
  full: '完全访问',
}

function guestHoursLeft(expiresAt?: string | null): number | null {
  if (!expiresAt) return null
  const diff = new Date(expiresAt).getTime() - Date.now()
  return Number.isNaN(diff) ? null : Math.max(0, Math.ceil(diff / 3_600_000))
}

export default function App() {
  const {
    user, checked, check, logout, pendingRecoveryCode, clearRecoveryCode,
  } = useAuth()
  const {
    sessions, sessionId, messages, historyRepoId, loadSessions, setHistoryRepoId, selectSession,
    newSession, deleteSession, renameSession, permissionMode, setPermissionMode,
  } = useChat()
  const { settings: llmSettings, load: loadLlm } = useLlm()
  const { repos, loading: reposLoading, refresh: refreshRepos } = useRepos()

  const [view, setView] = useState<ViewKey>('chat')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem('nova.sidebar.collapsed') === '1',
  )
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [healthState, setHealthState] = useState<'ok' | 'warn' | 'err'>('warn')
  const [guestBannerHidden, setGuestBannerHidden] = useState(
    () => localStorage.getItem('nova.guest-banner') === 'dismissed',
  )
  const [workspaceTarget, setWorkspaceTarget] = useState<{ repoId?: string; path?: string }>({})
  const [tasksTarget, setTasksTarget] = useState<{ repoId?: string }>({})

  useEffect(() => {
    void check()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!user) return
    void loadSessions()
    void loadLlm()
    void refreshRepos()
  }, [user, loadSessions, loadLlm, refreshRepos])

  useEffect(() => {
    if (!historyRepoId || reposLoading) return
    if (!repos.some((repo) => repo.id === historyRepoId)) {
      void setHistoryRepoId(null)
    }
  }, [historyRepoId, repos, reposLoading, setHistoryRepoId])

  useEffect(() => {
    localStorage.setItem('nova.sidebar.collapsed', sidebarCollapsed ? '1' : '0')
  }, [sidebarCollapsed])

  useEffect(() => {
    if (!user) return
    let cancelled = false
    const poll = async () => {
      try {
        const [h, u] = await Promise.all([api.status.health(), api.status.usage()])
        if (cancelled) return
        setHealth(h)
        setUsage(u)
        setHealthState(h.status === 'ok' ? 'ok' : 'warn')
      } catch {
        if (!cancelled) setHealthState('err')
      }
    }
    void poll()
    const timer = setInterval(poll, 60_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [user])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey
      if (mod && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((value) => !value)
      } else if (mod && event.key.toLowerCase() === 'b') {
        event.preventDefault()
        if (window.matchMedia('(min-width: 768px)').matches) {
          setSidebarCollapsed((value) => !value)
        } else {
          setSidebarOpen((value) => !value)
        }
      } else if (mod && event.key.toLowerCase() === 'n') {
        event.preventDefault()
        newSession()
        setView('chat')
      } else if (mod && ['1', '2', '3'].includes(event.key)) {
        event.preventDefault()
        setView(NAV[Number(event.key) - 1].key)
      } else if (event.key === 'Escape') {
        setPaletteOpen(false)
        setSidebarOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const sandbox = (health?.components.sandbox ?? {}) as { available?: boolean }
  const activeSession = sessions.find((session) => session.id === sessionId)
  const model = llmSettings?.source === 'user'
    ? llmSettings.model
    : llmSettings?.source === 'server'
      ? llmSettings.server_model
      : llmSettings
        ? '未配置模型'
        : (health?.components.model as string) ?? '—'
  const modelSource = llmSettings?.source === 'user'
    ? '个人密钥'
    : llmSettings?.source === 'server' ? '服务端密钥' : '未配置'
  const displayName = user?.display_name || user?.username || ''
  const guestRemaining = user ? guestHoursLeft(user.expires_at) : null
  const pageTitle = view === 'chat'
    ? (sessionId ? activeSession?.title ?? '对话' : '新对话')
    : VIEW_TITLE[view]
  const pageSubtitle = view === 'chat'
    ? (messages.length > 0 ? `${messages.length} 条消息` : VIEW_SUBTITLE.chat)
    : VIEW_SUBTITLE[view]

  const activeNav = view === 'workspace' ? 'chat' : view

  const toggleSidebar = () => {
    if (window.matchMedia('(min-width: 768px)').matches) {
      setSidebarCollapsed((value) => !value)
    } else {
      setSidebarOpen((value) => !value)
    }
  }

  const openWorkspace = (repoId?: string, path?: string) => {
    setWorkspaceTarget({ repoId, path })
    setView('workspace')
    setSidebarOpen(false)
  }

  const openTasks = (repoId?: string) => {
    setTasksTarget({ repoId })
    setView('tasks')
    setSidebarOpen(false)
  }

  const changeHistoryFilter = async (repoId: string) => {
    await setHistoryRepoId(repoId || null)
    const state = useChat.getState()
    if (state.sessionId && !state.sessions.some((session) => session.id === state.sessionId)) {
      state.newSession()
    }
  }

  const startNewChat = () => {
    newSession()
    setView('chat')
    setSidebarOpen(false)
  }

  const openSession = async (id: string) => {
    await selectSession(id)
    setView('chat')
    setSidebarOpen(false)
  }

  const actions = useMemo<PaletteAction[]>(() => {
    const items: PaletteAction[] = NAV.map((item, index) => ({
      id: `view-${item.key}`,
      label: `打开${item.label}`,
      hint: `Ctrl ${index + 1}`,
      run: () => setView(item.key),
    }))
    items.push({
      id: 'new-chat',
      label: '新建对话',
      hint: 'Ctrl N',
      run: startNewChat,
    })
    items.push({
      id: 'open-workspace',
      label: '打开工作区',
      hint: '浏览代码',
      run: () => openWorkspace(),
    })
    items.push({
      id: 'open-tasks',
      label: '打开任务',
      hint: '修复与变更',
      run: () => openTasks(),
    })
    items.push({
      id: 'llm-settings',
      label: '模型与 API Key',
      hint: llmSettings?.source === 'user' ? '个人密钥' : '服务端',
      run: () => setView('settings'),
    })
    for (const mode of ['readonly', 'ask', 'auto', 'full'] as const) {
      items.push({
        id: `perm-${mode}`,
        label: `权限模式：${PERMISSION_LABEL[mode]}`,
        hint: permissionMode === mode ? '当前' : '',
        run: () => setPermissionMode(mode),
      })
    }
    items.push({ id: 'logout', label: '退出登录', run: () => void logout() })
    return items
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [permissionMode, setPermissionMode, logout, llmSettings?.source])

  if (!checked) {
    return <div className="flex min-h-screen items-center justify-center text-[13px] text-dim">加载中…</div>
  }

  if (!user) return <LoginView />

  return (
    <div className="flex h-screen overflow-hidden">
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 backdrop-blur-[1px] md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <aside
        className={clsx(
          'fixed inset-y-0 left-0 z-40 flex w-[268px] shrink-0 flex-col border-r border-edge/80 bg-panel transition-all duration-200 md:static md:z-auto md:translate-x-0',
          sidebarCollapsed ? 'md:w-[64px]' : 'md:w-[268px]',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className={clsx(
          'flex h-12 items-center gap-2.5 border-b border-edge/70 px-3.5',
          sidebarCollapsed && 'md:justify-center md:px-0',
        )}>
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accentSoft/60">
            <Bot size={15} className="text-accent" />
          </div>
          <div className={clsx('min-w-0 flex-1', sidebarCollapsed && 'md:hidden')}>
            <p className="truncate text-[13px] font-semibold">Nova Agent</p>
            <p className="truncate text-[10px] text-dim">可验证的工程 Agent</p>
          </div>
          <button
            className="flex h-7 w-7 items-center justify-center rounded-md text-dim hover:bg-raised hover:text-ink md:hidden"
            onClick={() => setSidebarOpen(false)}
            aria-label="关闭侧栏"
          >
            <X size={14} />
          </button>
        </div>

        <nav className={clsx('space-y-0.5 py-2', sidebarCollapsed ? 'md:px-2' : 'px-2')}>
          {NAV.map(({ key, label, icon: Icon }, index) => (
            <button
              key={key}
              onClick={() => {
                setView(key)
                setSidebarOpen(false)
              }}
              title={sidebarCollapsed ? label : undefined}
              className={clsx(
                'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[12.5px] transition-colors',
                sidebarCollapsed && 'md:justify-center md:px-0',
                activeNav === key
                  ? 'bg-accentSoft/35 text-ink'
                  : 'text-dim hover:bg-raised hover:text-ink',
              )}
            >
              <Icon size={15} className={activeNav === key ? 'text-accent' : ''} />
              <span className={clsx('flex-1 text-left', sidebarCollapsed && 'md:hidden')}>{label}</span>
              <span className={clsx('font-mono text-[9.5px] text-dim/50', sidebarCollapsed && 'md:hidden')}>{index + 1}</span>
            </button>
          ))}
        </nav>

        {sidebarCollapsed && (
          <button
            onClick={startNewChat}
            className="mx-2 mb-1 hidden h-9 items-center justify-center rounded-lg bg-accentSoft/30 text-accent transition-colors hover:bg-accentSoft/50 md:flex"
            title="新建对话 · Ctrl/⌘ N"
            aria-label="新建对话"
          >
            <MessageSquarePlus size={16} />
          </button>
        )}

        <div className={clsx('mx-3 border-t border-edge/70', sidebarCollapsed && 'md:hidden')} />

        <div className={clsx('min-h-0 flex-1 pt-2', sidebarCollapsed && 'md:hidden')}>
          <SessionList
            sessions={sessions}
            projects={repos}
            projectFilter={historyRepoId ?? ''}
            onProjectFilterChange={(repoId) => void changeHistoryFilter(repoId)}
            activeId={sessionId}
            onSelect={(id) => void openSession(id)}
            onNew={startNewChat}
            onDelete={(id) => void deleteSession(id)}
            onRename={(id, title) => void renameSession(id, title)}
          />
        </div>

        <div className="border-t border-edge/80 p-2.5">
          <div className={clsx(
            'flex items-center gap-2 rounded-lg px-1 py-1',
            sidebarCollapsed && 'md:flex-col md:gap-1 md:px-0',
          )}>
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accentSoft/50 text-[11px] font-medium text-accent">
              {displayName.slice(0, 1).toUpperCase()}
            </div>
            <div className={clsx('min-w-0 flex-1', sidebarCollapsed && 'md:hidden')}>
              <p className="truncate text-[12px] text-ink">{displayName}</p>
              <p className="truncate text-[10px] text-dim">
                {user.is_guest
                  ? `游客体验${guestRemaining == null ? '' : ` · 剩余 ${guestRemaining}h`}`
                  : user.role === 'admin' ? '管理员' : '普通用户'}
              </p>
            </div>
            <button
              onClick={() => void logout()}
              className="flex h-7 w-7 items-center justify-center rounded-md text-dim hover:bg-raised hover:text-ink"
              title="退出登录"
            >
              <LogOut size={14} />
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-edge/80 bg-panel/35 px-3">
          <button
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-dim transition-colors hover:bg-raised hover:text-ink"
            onClick={toggleSidebar}
            title="切换侧栏 · Ctrl/⌘ B"
            aria-label="切换侧栏"
          >
            <PanelLeft size={16} />
          </button>
          {view === 'workspace' && (
            <button
              onClick={() => setView('chat')}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-dim transition-colors hover:bg-raised hover:text-ink"
              title="返回对话"
              aria-label="返回对话"
            >
              <ArrowLeft size={15} />
            </button>
          )}
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-[12.5px] font-medium">{pageTitle}</span>
            <span className="hidden truncate text-[11px] text-dim sm:inline">{pageSubtitle}</span>
          </div>
          {view === 'chat' && (
            <button
              onClick={startNewChat}
              className="ml-1 hidden h-7 shrink-0 items-center gap-1 rounded-lg border border-edge/80 px-2 text-[11px] text-dim transition-colors hover:border-accentSoft hover:text-ink sm:flex"
              title="新建对话 · Ctrl/⌘ N"
            >
              <Plus size={12} /> 新对话
            </button>
          )}
          <div className="ml-auto flex items-center gap-1.5">
            <button
              onClick={() => setView('settings')}
              className="flex h-7 items-center gap-1.5 rounded-lg border border-edge/70 bg-raised/40 px-2 text-[10.5px] text-dim transition-colors hover:border-accentSoft hover:text-ink"
              title={`${modelSource} · 点击配置模型与 API Key`}
            >
              <Cpu size={11} className={llmSettings?.source === 'user' ? 'text-accent' : 'text-dim'} />
              <span className="hidden max-w-[150px] truncate sm:inline">{model ?? '未配置模型'}</span>
            </button>
            <button
              onClick={() => setPaletteOpen(true)}
              className="hidden h-7 items-center gap-1.5 rounded-lg border border-edge/70 px-2 text-[10.5px] text-dim transition-colors hover:text-ink sm:flex"
              title="命令面板"
            >
              <Command size={11} /> K
            </button>
            <span className="flex items-center gap-1.5 text-[11px] text-dim" title="服务健康状态">
              <StatusDot state={healthState} />
              <span className="hidden md:inline">
                {healthState === 'ok' ? '服务正常' : healthState === 'warn' ? '部分降级' : '服务不可用'}
              </span>
            </span>
          </div>
        </header>

        <div className="min-h-0 flex-1">
          {user.is_guest && !guestBannerHidden && (
            <div className="flex shrink-0 items-center gap-2 border-b border-accentSoft/40 bg-accentSoft/15 px-3 py-1.5 text-[11.5px] text-ink">
              <MonitorDown size={13} className="shrink-0 text-accent" />
              <span className="min-w-0 flex-1 truncate">
                你在游客模式，数据 24 小时后清理。长期使用请注册账号；
                <a href="/downloads/" target="_blank" rel="noreferrer" className="ml-1 text-accent underline underline-offset-2">
                  下载桌面客户端
                </a>
                可从桌面直达。
              </span>
              <button
                onClick={() => {
                  setGuestBannerHidden(true)
                  localStorage.setItem('nova.guest-banner', 'dismissed')
                }}
                className="shrink-0 text-dim hover:text-ink"
                aria-label="关闭"
              >
                <X size={13} />
              </button>
            </div>
          )}
          {view === 'chat' && (
            <ChatView
              onOpenSettings={() => setView('settings')}
              onOpenWorkspace={openWorkspace}
              onOpenTasks={openTasks}
            />
          )}
          {view === 'tasks' && (
            <TasksView
              key={tasksTarget.repoId ?? 'any'}
              initialRepoId={tasksTarget.repoId}
              onBackToChat={() => setView('chat')}
            />
          )}
          {view === 'workspace' && (
            <WorkspaceView
              key={`${workspaceTarget.repoId ?? 'all'}-${workspaceTarget.path ?? ''}`}
              initialRepoId={workspaceTarget.repoId}
              initialPath={workspaceTarget.path}
              onClose={() => setView('chat')}
            />
          )}
          {view === 'settings' && <SettingsView />}
        </div>

        <footer className="flex h-7 shrink-0 items-center gap-3 border-t border-edge/80 bg-panel px-3 text-[10.5px] text-dim">
          <span className="flex items-center gap-1.5" title={`${modelSource}：${model ?? '未配置'}`}>
            <StatusDot state={healthState} />
            <span className="max-w-[220px] truncate">{model}</span>
            <span className={clsx(
              'rounded px-1 py-px text-[9px]',
              llmSettings?.source === 'user' ? 'bg-accentSoft/50 text-accent' : 'bg-raised text-dim',
            )}>
              {modelSource}
            </span>
          </span>
          <span className="hidden sm:inline">权限：{PERMISSION_LABEL[permissionMode]}</span>
          <span className="hidden md:inline">
            沙箱：{sandbox.available ? '可用' : '不可用'}
          </span>
          <span className="hidden md:inline">
            今日 {usage ? usage.today_tokens.toLocaleString() : '—'} tokens
          </span>
          <span className="ml-auto text-dim/70">v{health?.version ?? '2.0.0'}</span>
        </footer>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} actions={actions} />
      {pendingRecoveryCode && (
        <RecoveryCodeModal code={pendingRecoveryCode} onClose={clearRecoveryCode} />
      )}
    </div>
  )
}
