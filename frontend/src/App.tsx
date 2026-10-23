import clsx from 'clsx'
import {
  Bot, Command, FlaskConical, FolderGit2, GitPullRequest, LogOut, Menu,
  MessagesSquare, Settings, X,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { CommandPalette, type PaletteAction } from './components/CommandPalette'
import { SessionList } from './components/SessionList'
import { StatusDot } from './components/common'
import { api } from './lib/api'
import type { Health, Usage } from './lib/types'
import { useAuth } from './stores/auth'
import { useChat } from './stores/chat'
import { ChangesView } from './views/ChangesView'
import { ChatView } from './views/ChatView'
import { LoginView } from './views/LoginView'
import { SettingsView } from './views/SettingsView'
import { TasksView } from './views/TasksView'
import { WorkspaceView } from './views/WorkspaceView'

type ViewKey = 'chat' | 'workspace' | 'changes' | 'tasks' | 'settings'

const NAV: { key: ViewKey; label: string; icon: typeof Bot }[] = [
  { key: 'chat', label: '对话', icon: MessagesSquare },
  { key: 'workspace', label: '工作区', icon: FolderGit2 },
  { key: 'changes', label: '变更', icon: GitPullRequest },
  { key: 'tasks', label: '任务', icon: FlaskConical },
  { key: 'settings', label: '设置', icon: Settings },
]

const VIEW_TITLE: Record<ViewKey, string> = {
  chat: '对话',
  workspace: '工作区',
  changes: '变更中心',
  tasks: '修复任务',
  settings: '设置',
}

const VIEW_SUBTITLE: Record<ViewKey, string> = {
  chat: '带着证据与仓库上下文对话',
  workspace: '导入、索引、项目地图与交付',
  changes: 'SPEC → 计划 → Gate → 审查',
  tasks: '复现、修复并验证',
  settings: '服务健康、用量与账号',
}

const PERMISSION_LABEL: Record<string, string> = {
  readonly: '只读',
  ask: '确认写入',
  auto: '自动执行',
}

export default function App() {
  const { user, checked, check, logout } = useAuth()
  const {
    sessions, sessionId, loadSessions, selectSession, newSession, deleteSession, renameSession,
    permissionMode, setPermissionMode,
  } = useChat()

  const [view, setView] = useState<ViewKey>('chat')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [healthState, setHealthState] = useState<'ok' | 'warn' | 'err'>('warn')

  useEffect(() => {
    void check()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (user) void loadSessions()
  }, [user, loadSessions])

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
        setSidebarOpen((value) => !value)
      } else if (mod && ['1', '2', '3', '4', '5'].includes(event.key)) {
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
  const model = (health?.components.model as string) ?? '—'

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
      hint: '会话',
      run: startNewChat,
    })
    for (const mode of ['readonly', 'ask', 'auto'] as const) {
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
  }, [permissionMode, setPermissionMode, logout])

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
          'fixed inset-y-0 left-0 z-40 flex w-[268px] shrink-0 flex-col border-r border-edge bg-panel transition-transform duration-200 md:static md:z-auto md:translate-x-0',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',
        )}
      >
        <div className="flex h-12 items-center gap-2.5 border-b border-edge px-3.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accentSoft/60">
            <Bot size={15} className="text-accent" />
          </div>
          <div className="min-w-0 flex-1">
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

        <nav className="space-y-0.5 px-2 py-2">
          {NAV.map(({ key, label, icon: Icon }, index) => (
            <button
              key={key}
              onClick={() => {
                setView(key)
                setSidebarOpen(false)
              }}
              className={clsx(
                'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[12.5px] transition-colors',
                view === key
                  ? 'bg-accentSoft/35 text-ink'
                  : 'text-dim hover:bg-raised hover:text-ink',
              )}
            >
              <Icon size={15} className={view === key ? 'text-accent' : ''} />
              <span className="flex-1 text-left">{label}</span>
              <span className="font-mono text-[9.5px] text-dim/50">{index + 1}</span>
            </button>
          ))}
        </nav>

        <div className="mx-3 border-t border-edge/70" />

        <div className="min-h-0 flex-1 pt-2">
          <SessionList
            sessions={sessions}
            activeId={sessionId}
            onSelect={(id) => void openSession(id)}
            onNew={startNewChat}
            onDelete={(id) => void deleteSession(id)}
            onRename={(id, title) => void renameSession(id, title)}
          />
        </div>

        <div className="border-t border-edge p-2.5">
          <div className="flex items-center gap-2 rounded-lg px-1 py-1">
            <div className="flex h-7 w-7 items-center justify-center rounded-full bg-accentSoft/50 text-[11px] font-medium text-accent">
              {user.username.slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[12px] text-ink">{user.username}</p>
              <p className="text-[10px] uppercase tracking-wide text-dim">{user.role}</p>
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
        <header className="flex h-11 shrink-0 items-center gap-3 border-b border-edge bg-panel/70 px-3">
          <button
            className="flex h-7 w-7 items-center justify-center rounded-md text-dim hover:bg-raised hover:text-ink md:hidden"
            onClick={() => setSidebarOpen(true)}
            aria-label="打开侧栏"
          >
            <Menu size={16} />
          </button>
          <div className="min-w-0">
            <span className="text-[12.5px] font-medium">{VIEW_TITLE[view]}</span>
            <span className="ml-2 hidden text-[11px] text-dim sm:inline">{VIEW_SUBTITLE[view]}</span>
          </div>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => setPaletteOpen(true)}
              className="hidden items-center gap-1.5 rounded-md border border-edge px-2 py-1 text-[11px] text-dim hover:text-ink sm:flex"
              title="命令面板"
            >
              <Command size={11} /> K
            </button>
            <span className="flex items-center gap-1.5 text-[11.5px] text-dim" title="服务健康状态">
              <StatusDot state={healthState} />
              {healthState === 'ok' ? '服务正常' : healthState === 'warn' ? '部分降级' : '服务不可用'}
            </span>
          </div>
        </header>

        <div className="min-h-0 flex-1">
          {view === 'chat' && <ChatView />}
          {view === 'workspace' && <WorkspaceView />}
          {view === 'changes' && <ChangesView />}
          {view === 'tasks' && <TasksView />}
          {view === 'settings' && <SettingsView />}
        </div>

        <footer className="flex h-7 shrink-0 items-center gap-3 border-t border-edge bg-panel px-3 text-[10.5px] text-dim">
          <span className="flex items-center gap-1.5">
            <StatusDot state={healthState} />
            {model}
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
    </div>
  )
}
