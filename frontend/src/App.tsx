import clsx from 'clsx'
import {
  Bot, Command, FlaskConical, FolderGit2, GitPullRequest, LogOut, MessagesSquare, Settings,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { CommandPalette, type PaletteAction } from './components/CommandPalette'
import { StatusDot } from './components/common'
import { api } from './lib/api'
import type { Health, Usage } from './lib/types'
import { useAuth } from './stores/auth'
import { useChat } from './stores/chat'
import { ChatView } from './views/ChatView'
import { ChangesView } from './views/ChangesView'
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

const PERMISSION_LABEL: Record<string, string> = {
  readonly: '只读',
  ask: '确认写入',
  auto: '自动执行',
}

export default function App() {
  const { user, checked, check, logout } = useAuth()
  const permissionMode = useChat((s) => s.permissionMode)
  const setPermissionMode = useChat((s) => s.setPermissionMode)
  const newSession = useChat((s) => s.newSession)

  const [view, setView] = useState<ViewKey>('chat')
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [health, setHealth] = useState<Health | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [healthState, setHealthState] = useState<'ok' | 'warn' | 'err'>('warn')

  useEffect(() => {
    void check()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
        setPaletteOpen((v) => !v)
      } else if (mod && ['1', '2', '3', '4', '5'].includes(event.key)) {
        event.preventDefault()
        setView(NAV[Number(event.key) - 1].key)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const sandbox = (health?.components.sandbox ?? {}) as { available?: boolean }
  const model = (health?.components.model as string) ?? '—'

  const actions = useMemo<PaletteAction[]>(() => {
    const items: PaletteAction[] = NAV.map((item, i) => ({
      id: `view-${item.key}`,
      label: `打开${item.label}`,
      hint: `Ctrl ${i + 1}`,
      run: () => setView(item.key),
    }))
    items.push({
      id: 'new-chat',
      label: '新建对话',
      hint: '会话',
      run: () => {
        newSession()
        setView('chat')
      },
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
  }, [permissionMode, newSession, setPermissionMode, logout])

  if (!checked) {
    return <div className="flex min-h-screen items-center justify-center text-[13px] text-dim">加载中…</div>
  }

  if (!user) return <LoginView />

  return (
    <div className="flex h-screen">
      {/* Left rail — desktop-agent style */}
      <aside className="flex w-16 shrink-0 flex-col items-center border-r border-edge bg-panel">
        <div className="flex h-12 w-full items-center justify-center border-b border-edge">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-accentSoft/60" title="Nova Agent">
            <Bot size={17} className="text-accent" />
          </div>
        </div>
        <nav className="flex flex-1 flex-col items-center gap-1 py-2">
          {NAV.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setView(key)}
              title={`${label}（Ctrl ${NAV.findIndex((n) => n.key === key) + 1}）`}
              className={clsx(
                'flex w-12 flex-col items-center gap-0.5 rounded-lg py-2 text-[10px] transition-colors',
                view === key
                  ? 'bg-accentSoft/40 text-ink'
                  : 'text-dim hover:bg-raised hover:text-ink',
              )}
            >
              <Icon size={17} />
              {label}
            </button>
          ))}
        </nav>
        <div className="flex flex-col items-center gap-2 border-t border-edge py-3">
          <button
            onClick={() => setPaletteOpen(true)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-dim hover:bg-raised hover:text-ink"
            title="命令面板（Ctrl/⌘ K）"
          >
            <Command size={15} />
          </button>
          <div
            className="flex h-7 w-7 items-center justify-center rounded-full bg-accentSoft/50 text-[11px] font-medium text-accent"
            title={`${user.username}（${user.role}）`}
          >
            {user.username.slice(0, 1).toUpperCase()}
          </div>
          <button
            onClick={() => void logout()}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-dim hover:bg-raised hover:text-ink"
            title="退出登录"
          >
            <LogOut size={14} />
          </button>
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-11 shrink-0 items-center gap-3 border-b border-edge bg-panel/80 px-4">
          <div className="min-w-0">
            <span className="text-[13px] font-medium">{VIEW_TITLE[view]}</span>
            <span className="ml-2 text-[11px] text-dim">Nova Agent · 可验证的工程 Agent</span>
          </div>
          <div className="ml-auto flex items-center gap-3">
            <button
              onClick={() => setPaletteOpen(true)}
              className="hidden items-center gap-1.5 rounded-md border border-edge px-2 py-1 text-[11px] text-dim hover:text-ink sm:flex"
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

        {/* Status bar — like a desktop IDE */}
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