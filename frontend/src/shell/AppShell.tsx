import { ArrowLeft, MonitorDown, X } from 'lucide-react'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { CommandPalette, type PaletteAction } from '../components/CommandPalette'
import { LocalSetupDialog } from '../components/LocalSetupDialog'
import { RecoveryCodeModal } from '../components/RecoveryCodeModal'
import { api } from '../lib/api'
import type { Health, Usage } from '../lib/types'
import { useAuth } from '../stores/auth'
import { useChat } from '../stores/chat'
import { useLlm } from '../stores/llm'
import { useMode } from '../stores/mode'
import { useRepos } from '../stores/repos'
import { useRun } from '../stores/run'
import type { WorkspaceTab } from '../views/WorkspaceView'
import { ChatHeader } from './ChatHeader'
import { ContextRail } from './ContextRail'
import { ProjectRail } from './ProjectRail'
import { WorkspaceDrawer } from './WorkspaceDrawer'

const ChatView = lazy(() => import('../views/ChatView').then((m) => ({ default: m.ChatView })))
const LoginView = lazy(() => import('../views/LoginView').then((m) => ({ default: m.LoginView })))
const SettingsView = lazy(() => import('../views/SettingsView').then((m) => ({ default: m.SettingsView })))

const PERMISSION_LABEL = {
  readonly: '计划模式',
  ask: '变更前确认',
  auto: '自主模式',
  full: '完全访问',
} as const

type Overlay = 'settings' | null

const ViewFallback = () => (
  <div className="flex h-full min-h-[40vh] flex-1 items-center justify-center font-mono text-sm text-dim">
    加载中…
  </div>
)

const BootLine = () => (
  <div className="flex h-screen items-center justify-center bg-base font-mono text-sm text-dim">
    <span className="mr-2 text-accent">$</span>
    <span>nova --connect</span>
    <span className="nova-caret ml-1 text-accent">▍</span>
  </div>
)

export function AppShell() {
  const {
    user, checked, check, logout, pendingRecoveryCode, clearRecoveryCode,
  } = useAuth()
  const historyRepoId = useChat((state) => state.historyRepoId)
  const selectedRepoIds = useChat((state) => state.selectedRepoIds)
  const permissionMode = useChat((state) => state.permissionMode)
  const setPermissionMode = useChat((state) => state.setPermissionMode)
  const newSession = useChat((state) => state.newSession)
  const loadSessions = useChat((state) => state.loadSessions)
  const setHistoryRepoId = useChat((state) => state.setHistoryRepoId)
  const { settings: llmSettings, load: loadLlm } = useLlm()
  const { repos, loading: reposLoading, refresh: refreshRepos } = useRepos()
  const {
    mode, setup, load: loadMode, loadSetup, markConfigured,
  } = useMode()

  const [setupOpen, setSetupOpen] = useState(false)
  const setupPrompted = useRef(false)
  /** 左侧项目栏的 `< md` 覆盖层。 */
  const [railOpen, setRailOpen] = useState(false)
  /** 右侧上下文栏的 `< lg` 覆盖层；桌面可见性由 collapsed 决定。 */
  const [contextRailOpen, setContextRailOpen] = useState(false)
  const [contextRailCollapsed, setContextRailCollapsed] = useState(
    () => localStorage.getItem('nova.rail.collapsed') === '1',
  )
  const [localAgentOpen, setLocalAgentOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [overlay, setOverlay] = useState<Overlay>(null)
  const [drawer, setDrawer] = useState<{ repoId?: string; path?: string; tab?: WorkspaceTab } | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [healthState, setHealthState] = useState<'ok' | 'warn' | 'err'>('warn')
  const [guestBannerHidden, setGuestBannerHidden] = useState(
    () => localStorage.getItem('nova.guest-banner') === 'dismissed',
  )

  useEffect(() => {
    void check()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    void loadMode()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!user || !mode?.local) return
    void loadSetup().then((status) => {
      if (status && !status.configured && !setupPrompted.current) {
        setupPrompted.current = true
        setSetupOpen(true)
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, mode?.local])

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
    try {
      localStorage.setItem('nova.rail.collapsed', contextRailCollapsed ? '1' : '0')
    } catch {
      /* localStorage 不可用时只失去折叠记忆 */
    }
  }, [contextRailCollapsed])

  const openSettings = () => {
    setOverlay('settings')
    setRailOpen(false)
    setDrawer(null)
  }

  /** 工作区只通过项目头 / 右栏进入：打开右侧抽屉而不是独立页面。 */
  const openWorkspace = (repoId?: string, path?: string, tab?: WorkspaceTab) => {
    setRailOpen(false)
    setDrawer({ repoId, path, tab })
  }

  const openRun = () => {
    useRun.setState({ open: true })
    setRailOpen(false)
    setContextRailCollapsed(false)
    if (!window.matchMedia('(min-width: 1024px)').matches) setContextRailOpen(true)
  }

  /** 桌面折叠 / 展开，窄屏切换右侧覆盖层。 */
  const toggleContextRail = () => {
    if (window.matchMedia('(min-width: 1024px)').matches) {
      setContextRailCollapsed((value) => !value)
    } else {
      setContextRailOpen((value) => !value)
    }
  }

  const startNewChat = () => {
    newSession()
    setOverlay(null)
    setRailOpen(false)
    setContextRailOpen(false)
    setDrawer(null)
  }

  const currentRepoId = historyRepoId ?? selectedRepoIds[0] ?? undefined

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey
      if (mod && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen((value) => !value)
      } else if (mod && event.key.toLowerCase() === 'b') {
        // 桌面端栏位固定展示，不拦截浏览器快捷键；仅抽屉模式（< md）切换。
        if (!window.matchMedia('(min-width: 768px)').matches) {
          event.preventDefault()
          setRailOpen((value) => !value)
        }
      } else if (mod && event.key.toLowerCase() === 'n') {
        event.preventDefault()
        useChat.getState().newSession()
        setOverlay(null)
        setRailOpen(false)
      } else if (mod && ['1', '3'].includes(event.key)) {
        event.preventDefault()
        if (event.key === '1') {
          setOverlay(null)
        } else {
          setOverlay('settings')
          setRailOpen(false)
          setDrawer(null)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Esc 必须在捕获阶段处理：AppShell 会随覆盖层状态重订阅监听器，若留在冒泡阶段，
  // 后挂载的 RunPanel 可能先收到事件并关闭自己，反而留下设置覆盖层。
  // 每次只关闭最上层：命令面板 → 对话框 → 工作区抽屉 → 设置 → 左栏 → 右栏覆盖层；
  // 标记已处理后下层忽略。WorkspaceDrawer 自己也会捕获 Esc，靠 defaultPrevented 保证只关一层。
  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      if (paletteOpen) {
        event.preventDefault()
        setPaletteOpen(false)
      } else if (setupOpen) {
        event.preventDefault()
        setSetupOpen(false)
      } else if (drawer) {
        event.preventDefault()
        setDrawer(null)
      } else if (overlay) {
        event.preventDefault()
        setOverlay(null)
      } else if (railOpen) {
        event.preventDefault()
        setRailOpen(false)
      } else if (contextRailOpen) {
        event.preventDefault()
        setContextRailOpen(false)
      }
    }
    window.addEventListener('keydown', onEscape, true)
    return () => window.removeEventListener('keydown', onEscape, true)
  }, [paletteOpen, setupOpen, drawer, overlay, railOpen, contextRailOpen])

  const actions = useMemo<PaletteAction[]>(() => {
    const items: PaletteAction[] = [
      { id: 'new-chat', label: '新建对话', hint: 'Ctrl N', run: startNewChat },
      { id: 'open-workspace', label: '打开工作区', hint: '浏览代码', run: () => openWorkspace(currentRepoId) },
      {
        id: 'llm-settings',
        label: '模型与 API Key',
        hint: llmSettings?.source === 'user' ? '个人密钥' : '服务端',
        run: openSettings,
      },
    ]
    for (const value of ['readonly', 'ask', 'auto', 'full'] as const) {
      items.push({
        id: `perm-${value}`,
        label: `权限模式：${PERMISSION_LABEL[value]}`,
        hint: permissionMode === value ? '当前' : '',
        run: () => setPermissionMode(value),
      })
    }
    if (!mode?.local) {
      items.push({ id: 'logout', label: '退出登录', run: () => void logout() })
    }
    return items
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [permissionMode, setPermissionMode, logout, llmSettings?.source, mode?.local, currentRepoId])

  if (!checked) {
    return <BootLine />
  }

  if (!user) {
    return (
      <Suspense fallback={<BootLine />}>
        <LoginView />
      </Suspense>
    )
  }

  return (
    <div className="flex h-screen overflow-hidden bg-base text-ink">
      <ProjectRail
        open={railOpen}
        onClose={() => setRailOpen(false)}
        onOpenSettings={openSettings}
        onShowChat={() => setOverlay(null)}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <ChatHeader
          onOpenRail={() => setRailOpen(true)}
          onToggleContextRail={toggleContextRail}
          onNewChat={startNewChat}
          onOpenPalette={() => setPaletteOpen(true)}
          onOpenSettings={openSettings}
          onOpenWorkspace={openWorkspace}
          healthState={healthState}
          health={health}
          usage={usage}
          localOpen={localAgentOpen}
          onLocalOpenChange={setLocalAgentOpen}
        />

        {!mode?.local && user.is_guest && !guestBannerHidden && (
          <div className="flex shrink-0 items-center gap-2 border-b border-accent/20 bg-accentSoft/25 px-3 py-1.5 text-sm text-ink">
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
              className="shrink-0 text-dim transition-colors duration-150 hover:text-ink"
              aria-label="关闭"
            >
              <X size={13} />
            </button>
          </div>
        )}

        <div className="min-h-0 flex-1">
          <Suspense fallback={<ViewFallback />}>
            <ChatView
              embedded
              onOpenSettings={openSettings}
              onOpenWorkspace={openWorkspace}
              onOpenRun={openRun}
              onOpenLocalAgent={() => setLocalAgentOpen(true)}
            />
          </Suspense>
        </div>
      </main>

      <ContextRail
        open={contextRailOpen}
        collapsed={contextRailCollapsed}
        repoId={currentRepoId}
        onClose={() => setContextRailOpen(false)}
        onToggle={toggleContextRail}
        onOpenFile={(path, repoId) => openWorkspace(repoId, path)}
        onOpenWorkspace={(options) => openWorkspace(options.repoId, options.path, options.tab)}
      />

      {overlay && (
        <div className="fixed inset-0 z-50 flex flex-col bg-base">
          {overlay === 'settings' && (
            <div className="flex h-11 shrink-0 items-center gap-2 border-b border-edge bg-panel px-3">
              <button
                onClick={() => setOverlay(null)}
                className="flex h-7 w-7 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
                title="返回对话 · Esc"
                aria-label="返回对话"
              >
                <ArrowLeft size={14} />
              </button>
              <span className="font-mono text-sm text-dim">设置</span>
            </div>
          )}
          <div className="min-h-0 flex-1">
            <Suspense fallback={<ViewFallback />}>
              {overlay === 'settings' && <SettingsView />}
            </Suspense>
          </div>
        </div>
      )}

      <WorkspaceDrawer
        open={drawer !== null}
        repoId={drawer?.repoId}
        path={drawer?.path}
        tab={drawer?.tab}
        onClose={() => setDrawer(null)}
      />

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} actions={actions} />

      {mode?.local && (
        <LocalSetupDialog
          open={setupOpen}
          status={setup}
          onClose={() => setSetupOpen(false)}
          onDone={(status) => {
            markConfigured(status)
            setSetupOpen(false)
            void loadLlm()
            void refreshRepos()
          }}
        />
      )}
      {pendingRecoveryCode && (
        <RecoveryCodeModal code={pendingRecoveryCode} onClose={clearRecoveryCode} />
      )}
    </div>
  )
}
