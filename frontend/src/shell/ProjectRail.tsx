import clsx from 'clsx'
import { Bot, FolderOpen, FolderUp, LogOut, Plus, Settings, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { IcpNotice } from '../components/IcpNotice'
import { ImportDialog } from '../components/ImportDialog'
import { LocalFolderDialog } from '../components/LocalFolderDialog'
import { NewProjectDialog } from '../components/NewProjectDialog'
import { SessionList } from '../components/SessionList'
import { StatusDot } from '../components/common'
import type { Repo, RepoStatus } from '../lib/types'
import { useAuth } from '../stores/auth'
import { useChat } from '../stores/chat'
import { useMode } from '../stores/mode'
import { useRepos } from '../stores/repos'
import { ModeBadge } from './ModeBadge'

const ROLE_LABEL: Record<string, string> = {
  admin: '管理员',
  local: '本地用户',
  demo: '普通用户',
}

function guestHoursLeft(expiresAt?: string | null): number | null {
  if (!expiresAt) return null
  const diff = new Date(expiresAt).getTime() - Date.now()
  return Number.isNaN(diff) ? null : Math.max(0, Math.ceil(diff / 3_600_000))
}

function repoDot(status: RepoStatus): 'ok' | 'warn' | 'err' | 'idle' {
  if (status === 'ready') return 'ok'
  if (status === 'failed') return 'err'
  if (['pending', 'indexing', 'planning', 'generating'].includes(status)) return 'warn'
  return 'idle'
}

function RailAction({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className="flex h-7 w-7 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
      title={label}
      aria-label={label}
    >
      {children}
    </button>
  )
}

export function ProjectRail({
  open,
  onClose,
  onOpenSettings,
  onShowChat,
  width,
}: {
  open: boolean
  onClose: () => void
  onOpenSettings: () => void
  onShowChat: () => void
  /** 桌面宽度（可拖拽）；窄屏是覆盖层，固定 264px。 */
  width: number
}) {
  const user = useAuth((state) => state.user)
  const logout = useAuth((state) => state.logout)
  const sessions = useChat((state) => state.sessions)
  const sessionId = useChat((state) => state.sessionId)
  const historyRepoId = useChat((state) => state.historyRepoId)
  const selectedRepoIds = useChat((state) => state.selectedRepoIds)
  const setHistoryRepoId = useChat((state) => state.setHistoryRepoId)
  const selectSession = useChat((state) => state.selectSession)
  const newSession = useChat((state) => state.newSession)
  const deleteSession = useChat((state) => state.deleteSession)
  const renameSession = useChat((state) => state.renameSession)
  const repos = useRepos((state) => state.repos)
  const refresh = useRepos((state) => state.refresh)
  const mode = useMode((state) => state.mode)
  const [localFolderOpen, setLocalFolderOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [newProjectOpen, setNewProjectOpen] = useState(false)

  const local = Boolean(mode?.local)
  const currentRepoId = historyRepoId ?? selectedRepoIds[0] ?? null
  const displayName = user?.display_name || user?.username || ''
  const guestRemaining = user ? guestHoursLeft(user.expires_at) : null
  const roleText = user?.is_guest
    ? `游客体验${guestRemaining == null ? '' : ` · 剩余 ${guestRemaining}h`}`
    : ROLE_LABEL[user?.role ?? ''] ?? '普通用户'

  const selectProject = async (repo: Repo) => {
    useChat.getState().setSelectedRepoIds([repo.id])
    await setHistoryRepoId(repo.id)
    const state = useChat.getState()
    if (state.sessionId && !state.sessions.some((item) => item.id === state.sessionId)) {
      state.newSession()
    }
    onShowChat()
    onClose()
  }

  const changeHistoryFilter = async (repoId: string) => {
    await setHistoryRepoId(repoId || null)
    const state = useChat.getState()
    if (state.sessionId && !state.sessions.some((item) => item.id === state.sessionId)) {
      state.newSession()
    }
  }

  const startNewChat = () => {
    newSession()
    onShowChat()
    onClose()
  }

  const openSession = async (id: string) => {
    await selectSession(id)
    onShowChat()
    onClose()
  }

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/60 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <aside
        aria-label="项目与会话"
        style={{ '--rail-w': `${width}px` } as React.CSSProperties}
        className={clsx(
          // visibility 参与过渡：关闭时先滑出、动画结束才真正隐藏，打开时立即可见。
          'fixed inset-y-0 left-0 z-40 flex w-[264px] shrink-0 flex-col border-r border-edge bg-panel transition-[transform,visibility] duration-150 md:static md:z-auto md:w-[var(--rail-w)] md:translate-x-0',
          // 收起时只靠 transform 移出屏幕，控件仍在 Tab 序列里：屏幕阅读器能读到、
          // 键盘能 Tab 到看不见的按钮。visibility:hidden 同时移出焦点与无障碍树，
          // 而 md+ 是常驻侧栏，不受影响。
          open ? 'translate-x-0' : '-translate-x-full max-md:invisible',
        )}
      >
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-edge px-3">
          <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accentSoft">
            <Bot size={14} className="text-accent" />
          </div>
          <span className="font-mono text-sm font-medium uppercase tracking-[0.12em]">NOVA</span>
          <ModeBadge />
          <button
            onClick={onClose}
            className="ml-auto flex h-7 w-7 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink md:hidden"
            title="关闭侧栏"
            aria-label="关闭侧栏"
          >
            <X size={14} />
          </button>
        </div>

        <section aria-label="项目" className="shrink-0 border-b border-edge">
          <div className="flex items-center gap-2 px-3 pb-1 pt-3">
            <span className="font-mono text-sm font-medium uppercase tracking-[0.12em] text-faint">项目</span>
            <span className="rounded-sm bg-raised px-1.5 py-0.5 font-mono text-2xs text-dim">{repos.length}</span>
            <div className="ml-auto flex items-center gap-0.5">
              {local && (
                <RailAction label="打开本地文件夹" onClick={() => setLocalFolderOpen(true)}>
                  <FolderOpen size={13} />
                </RailAction>
              )}
              <RailAction label="导入项目" onClick={() => setImportOpen(true)}>
                <FolderUp size={13} />
              </RailAction>
              <RailAction label="新建项目" onClick={() => setNewProjectOpen(true)}>
                <Plus size={14} />
              </RailAction>
            </div>
          </div>

          <div className="max-h-64 overflow-y-auto px-2 pb-2">
            {repos.length === 0 ? (
              <p className="px-2 py-3 text-xs leading-relaxed text-faint">
                还没有项目。导入文件夹、ZIP 或 Git 仓库开始。
              </p>
            ) : (
              repos.map((repo) => {
                const active = repo.id === currentRepoId
                return (
                  <button
                    key={repo.id}
                    onClick={() => void selectProject(repo)}
                    aria-pressed={active}
                    title={repo.source}
                    className={clsx(
                      'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors duration-150',
                      active ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
                    )}
                  >
                    <StatusDot state={repoDot(repo.status)} />
                    <span className="min-w-0 flex-1 truncate text-sm">{repo.name}</span>
                    {repo.origin === 'local' && (
                      <span className="shrink-0 font-mono text-2xs text-accent/80">本地</span>
                    )}
                    {repo.kind === 'builder' && (
                      <span className="shrink-0 font-mono text-2xs text-faint">构建</span>
                    )}
                  </button>
                )
              })
            )}
          </div>
        </section>

        <div className="min-h-0 flex-1 pt-1">
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

        <div className="shrink-0 border-t border-edge p-2">
          <button
            onClick={onOpenSettings}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
          >
            <Settings size={14} />
            设置
          </button>

          <div className="mt-0.5 flex items-center gap-2 rounded-md px-2 py-1.5">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accentSoft text-xs font-medium text-accent">
              {(displayName || '?').slice(0, 1).toUpperCase()}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-ink">{displayName || '未登录'}</p>
              <p className="truncate text-2xs text-faint">{roleText}</p>
            </div>
            {!local && (
              <button
                onClick={() => void logout()}
                className="flex h-7 w-7 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
                title="退出登录"
                aria-label="退出登录"
              >
                <LogOut size={14} />
              </button>
            )}
          </div>

          <p className="px-2 pb-0.5 pt-1 font-mono text-2xs text-faint">
            {mode ? (local ? '本地模式 · 无容器隔离' : '云端模式 · 容器隔离') : '正在读取运行模式…'}
          </p>
          <IcpNotice className="block px-2 pb-1.5 font-mono text-2xs text-dim hover:text-ink" />
        </div>
      </aside>

      {local && (
        <LocalFolderDialog
          open={localFolderOpen}
          onClose={() => setLocalFolderOpen(false)}
          onOpened={(repo) => {
            setLocalFolderOpen(false)
            void refresh().then(() => selectProject(repo))
          }}
        />
      )}
      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={() => {
          setImportOpen(false)
          void refresh()
        }}
      />
      <NewProjectDialog
        open={newProjectOpen}
        onClose={() => setNewProjectOpen(false)}
        onCreated={(repoId) => {
          setNewProjectOpen(false)
          void refresh().then(() => {
            const repo = useRepos.getState().repos.find((item) => item.id === repoId)
            if (repo) void selectProject(repo)
          })
        }}
        onStartImport={() => setImportOpen(true)}
      />
    </>
  )
}
