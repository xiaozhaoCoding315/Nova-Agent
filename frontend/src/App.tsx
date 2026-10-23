import clsx from 'clsx'
import { Bot, FolderGit2, MessagesSquare, Settings, LogOut } from 'lucide-react'
import { useEffect, useState } from 'react'
import { StatusDot } from './components/common'
import { api } from './lib/api'
import { useAuth } from './stores/auth'
import { ChatView } from './views/ChatView'
import { LoginView } from './views/LoginView'
import { SettingsView } from './views/SettingsView'
import { WorkspaceView } from './views/WorkspaceView'

type ViewKey = 'chat' | 'workspace' | 'settings'

const NAV: { key: ViewKey; label: string; icon: typeof Bot }[] = [
  { key: 'chat', label: '对话', icon: MessagesSquare },
  { key: 'workspace', label: '工作区', icon: FolderGit2 },
  { key: 'settings', label: '设置', icon: Settings },
]

export default function App() {
  const { user, checked, check, logout } = useAuth()
  const [view, setView] = useState<ViewKey>('chat')
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
        const health = await api.status.health()
        if (!cancelled) setHealthState(health.status === 'ok' ? 'ok' : 'warn')
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

  if (!checked) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[13px] text-dim">加载中…</div>
    )
  }

  if (!user) return <LoginView />

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center gap-1 border-b border-edge bg-panel px-3">
        <div className="mr-3 flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accentSoft/60">
            <Bot size={15} className="text-accent" />
          </div>
          <span className="text-[14px] font-semibold">Nova Agent</span>
        </div>

        <nav className="flex items-center gap-1">
          {NAV.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              onClick={() => setView(key)}
              className={clsx(
                'flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[13px] transition-colors',
                view === key ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
              )}
            >
              <Icon size={14} />
              {label}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <span className="flex items-center gap-1.5 text-[11.5px] text-dim" title="服务健康状态">
            <StatusDot state={healthState} />
            {healthState === 'ok' ? '服务正常' : healthState === 'warn' ? '部分降级' : '服务不可用'}
          </span>
          <span className="text-[12px] text-dim">{user.username}</span>
          <button
            onClick={() => void logout()}
            className="text-dim transition-colors hover:text-ink"
            title="退出登录"
            aria-label="退出登录"
          >
            <LogOut size={14} />
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {view === 'chat' && <ChatView />}
        {view === 'workspace' && <WorkspaceView />}
        {view === 'settings' && <SettingsView />}
      </div>
    </div>
  )
}