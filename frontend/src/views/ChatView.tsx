import clsx from 'clsx'
import {
  Activity, AlertCircle, Check, Copy, FolderTree, MessageSquare, MonitorDown, PanelRight,
  Sparkles, Wrench, X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { COMMANDS, type CommandName } from '../lib/commands'
import { ProjectDock } from '../components/ProjectDock'
import { RefPanel } from '../components/RefPanel'
import { TrajectoryDrawer } from '../components/TrajectoryDrawer'
import { Button, Modal, Spinner } from '../components/common'
import { Composer } from '../composer/Composer'
import { ChatTimeline } from '../timeline/ChatTimeline'
import { RunPanel } from '../timeline/RunPanel'
import { useChat } from '../stores/chat'
import { useLlm } from '../stores/llm'
import { useRepos } from '../stores/repos'
import { readStoredRun, useRun, writeStoredRun } from '../stores/run'
import type { LocalExecStatus } from '../lib/types'

const EXAMPLES = [
  {
    title: '读懂代码',
    text: '这个仓库里 HTTP 请求的处理链路是怎样的？请给出关键文件与行号。',
  },
  {
    title: '定位报错',
    text: '帮我诊断这个报错，并告诉我对应代码在哪里：\n\nTraceback (most recent call last):\n  File "app/main.py", line 42, in <module>\n    main()\nValueError: boom',
  },
  {
    title: '写测试并验证',
    text: '给当前仓库里最核心的一个函数写 pytest 单测，并在沙箱里运行到全部通过。',
  },
]

export function ChatView({
  embedded = false,
  onOpenSettings,
  onOpenWorkspace,
  onOpenRun,
  onOpenTasks,
  onOpenLocalAgent,
}: {
  /** 终端工作台内嵌时不渲染旧上下文顶栏；轨迹与本机状态入口在 ChatHeader。 */
  embedded?: boolean
  onOpenSettings: () => void
  onOpenWorkspace: (repoId?: string, path?: string) => void
  /** 新工作台：打开右栏运行面板（Task 5 迁移到 ContextRail）。 */
  onOpenRun?: (repoId?: string) => void
  /** 旧 Shell 回滚入口：仍打开独立任务页，Task 7 随 LegacyShell 删除。 */
  onOpenTasks?: (repoId?: string) => void
  /** 新工作台：空状态的「连接你的电脑」直接打开 ChatHeader 的接入说明。 */
  onOpenLocalAgent?: () => void
}) {
  const {
    sessionId, messages, streaming, streamText, toolCards, streamEdits, plan, approvals, refs, error,
    permissionMode, setPermissionMode, model, setModel, selectedRepoIds, toggleRepo,
    attachments, uploading, uploadAttachment, removeAttachment,
    send, stop, clearError, streamUsage, contextMeter, turnNotice,
  } = useChat()
  const { repos, refresh } = useRepos()
  const { settings: llmSettings } = useLlm()
  const [trajectoryOpen, setTrajectoryOpen] = useState(false)
  const [dockOpen, setDockOpen] = useState(false)
  const [dockTab, setDockTab] = useState<'project' | 'refs'>('project')
  const [localOpen, setLocalOpen] = useState(false)
  const [localStatus, setLocalStatus] = useState<LocalExecStatus | null>(null)
  const [copiedCmd, setCopiedCmd] = useState(false)
  const [commandNotice, setCommandNotice] = useState<{ tone: 'info' | 'error'; text: string } | null>(null)
  const [gitDialog, setGitDialog] = useState<{ kind: 'commit' | 'init'; repoId: string } | null>(null)
  const [commitMessage, setCommitMessage] = useState('')
  const [dialogBusy, setDialogBusy] = useState(false)
  const [dialogError, setDialogError] = useState<string | null>(null)
  const runOpen = useRun((state) => state.open)
  const prevSessionId = useRef<string | null | undefined>(undefined)
  /** 本次会话 id 是新对话发送后由 meta 创建的，而不是用户从列表打开的历史会话。 */
  const sessionCreatedBySend = useRef(false)
  /** 发送时的会话选择版本；期间用户从列表选过会话就不再迁移新对话任务。 */
  const sendSelectionRevision = useRef(0)

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 旧 Shell 继续由本视图轮询本机状态；工作台内嵌时由 ChatHeader 负责。
  useEffect(() => {
    if (embedded) return
    let cancelled = false
    const poll = () => {
      api.local
        .status()
        .then((status) => {
          if (!cancelled) setLocalStatus(status)
        })
        .catch(() => {})
    }
    poll()
    const timer = setInterval(poll, 20_000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [embedded])

  // 每个会话记住自己的 /fix 运行：切换会话时恢复或收起，新会话建立时迁移「new」记录。
  useEffect(() => {
    const previous = prevSessionId.current
    prevSessionId.current = sessionId
    const run = useRun.getState()
    if (previous === undefined) {
      const saved = readStoredRun(sessionId)
      if (saved) void run.restore(saved)
      else run.close()
      return
    }
    if (sessionId === null) {
      sessionCreatedBySend.current = false
      if (previous !== null) run.reset()
      return
    }
    if (previous === null) {
      const saved = readStoredRun(sessionId)
      const createdBySend = sessionCreatedBySend.current
      const selectedSinceSend = useChat.getState().selectionRevision !== sendSelectionRevision.current
      sessionCreatedBySend.current = false
      if (createdBySend && !selectedSinceSend && run.taskId && (!saved || saved === run.taskId)) {
        // 新对话刚通过发送变成真实会话：把 `nova.run.new` 迁移到该会话。
        writeStoredRun(sessionId, run.taskId)
        writeStoredRun(null, null)
      } else if (saved) {
        // 用户从会话列表打开已有会话：恢复它自己的运行，绝不迁移新对话的任务。
        void run.restore(saved)
      } else {
        run.reset()
      }
      return
    }
    if (previous === sessionId) return
    const saved = readStoredRun(sessionId)
    if (saved) void run.restore(saved)
    else run.reset()
  }, [sessionId])

  // Escape 关闭 /commit、/init 对话框；捕获阶段拦住外层 Shell 的 Esc 层级。
  useEffect(() => {
    if (!gitDialog) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || dialogBusy) return
      event.preventDefault()
      event.stopPropagation()
      setGitDialog(null)
      setDialogError(null)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [gitDialog, dialogBusy])

  const readyRepos = repos.filter((repo) => repo.status === 'ready')
  const configured = llmSettings?.source === 'user'
  const provider = llmSettings?.providers.find((item) => item.id === llmSettings.provider)
  const effectiveModel = model ?? (configured ? llmSettings?.model ?? null : null)
  const modelChoices = configured
    ? Array.from(new Set([...(provider?.models ?? []), ...(effectiveModel ? [effectiveModel] : [])]))
    : []
  const modelLabel = configured
    ? (effectiveModel ?? '默认模型')
    : llmSettings?.source === 'server'
      ? `服务端默认${llmSettings.server_model ? ` · ${llmSettings.server_model}` : ''}`
      : '未配置模型 · 点击设置'

  const notice = (text: string, tone: 'info' | 'error' = 'info') => {
    setCommandNotice({ tone, text })
  }

  const openRunPanel = (repoId?: string) => {
    if (onOpenRun) onOpenRun(repoId)
    // 关闭面板会停轮询；重新打开时先取一次最新状态并恢复轮询。
    useRun.setState({ open: true })
    void useRun.getState().refresh()
  }

  const openLocalAgent = () => {
    if (onOpenLocalAgent) onOpenLocalAgent()
    else setLocalOpen(true)
  }

  /** 发送消息，并记录本次 sessionId 是否由这次「新对话发送」产生。 */
  const sendPrompt = (content: string, repoIds: string[]) => {
    if (useChat.getState().sessionId === null) {
      sessionCreatedBySend.current = true
      sendSelectionRevision.current = useChat.getState().selectionRevision
    }
    void send(content, repoIds).finally(() => {
      // 发送失败、没有被后端分配会话时，别让标记泄漏到下一次选择会话。
      if (useChat.getState().sessionId === null) sessionCreatedBySend.current = false
    })
  }

  /** 斜杠命令入口；返回 false 时 Composer 保留草稿，方便修改后重试。 */
  const executeCommand = async (name: CommandName | 'unknown', args: string): Promise<boolean> => {
    const chat = useChat.getState()
    const repoId = chat.selectedRepoIds[0]
    if (name === 'unknown') {
      notice(`未知命令 ${args}。输入 /help 查看全部命令`, 'error')
      return false
    }
    if (name === 'help') {
      notice(COMMANDS.map((item) => item.hint).join('\n'))
      return true
    }
    if (name === 'fix') {
      if (!repoId) {
        notice('先选择一个项目，再使用 /fix', 'error')
        return false
      }
      if (!args) {
        notice('请在 /fix 后描述问题，例如 /fix 结算时折扣超过 100% 会把总价算成负数', 'error')
        return false
      }
      try {
        const task = await api.tasks.create(repoId, args, `/fix: ${args}`.slice(0, 120))
        useRun.getState().start(task)
        // 新工作台把运行面板放在右栏：/fix 创建后主动把右栏（或窄屏覆盖层）打开。
        onOpenRun?.(repoId)
        void useRun.getState().loadRecent(repoId)
        return true
      } catch (err) {
        notice(err instanceof ApiError ? err.message : '创建修复任务失败', 'error')
        return false
      }
    }
    if (name === 'plan') {
      if (!args) {
        notice('请在 /plan 后写明目标，例如 /plan 给登录接口加分页', 'error')
        return false
      }
      sendPrompt(
        `请先给出实施计划，不要修改文件或执行会改变状态的命令。\n\n目标：${args}`,
        chat.selectedRepoIds,
      )
      return true
    }
    if (name === 'review') {
      if (!repoId) {
        notice('先选择一个项目，再使用 /review', 'error')
        return false
      }
      try {
        const { diff } = await api.git.diff(repoId)
        if (!diff.trim()) {
          notice('当前仓库没有未提交的改动')
          return true
        }
        sendPrompt(
          `请审查下面的 git diff，指出正确性风险、回归风险与缺失测试；不要修改文件。\n\n\`\`\`diff\n${diff.slice(0, 6000)}\n\`\`\``,
          chat.selectedRepoIds,
        )
        return true
      } catch (err) {
        notice(err instanceof ApiError ? err.message : '读取 diff 失败', 'error')
        return false
      }
    }
    if (name === 'commit') {
      if (!repoId) {
        notice('先选择一个项目，再使用 /commit', 'error')
        return false
      }
      setCommitMessage(args || 'chore: update')
      setDialogError(null)
      setGitDialog({ kind: 'commit', repoId })
      return true
    }
    if (name === 'init') {
      if (!repoId) {
        notice('先选择一个项目，再使用 /init', 'error')
        return false
      }
      setDialogError(null)
      setGitDialog({ kind: 'init', repoId })
      return true
    }
    return true
  }

  const closeGitDialog = () => {
    if (dialogBusy) return
    setGitDialog(null)
    setDialogError(null)
  }

  const confirmGitDialog = async () => {
    if (!gitDialog || dialogBusy) return
    setDialogBusy(true)
    setDialogError(null)
    try {
      if (gitDialog.kind === 'commit') {
        const info = await api.git.commit(gitDialog.repoId, commitMessage.trim() || 'chore: update')
        const hash = info.commits[0]?.hash
        notice(hash ? `已提交 ${hash.slice(0, 8)}` : '已提交')
      } else {
        await api.git.init(gitDialog.repoId)
        notice('已初始化 Git 仓库')
      }
      setGitDialog(null)
      await refresh()
    } catch (err) {
      const message = err instanceof ApiError
        ? err.message
        : gitDialog.kind === 'commit' ? '提交失败' : '初始化 Git 失败'
      setDialogError(message)
      notice(message, 'error')
    } finally {
      setDialogBusy(false)
    }
  }

  const dialogRepoName = repos.find((repo) => repo.id === gitDialog?.repoId)?.name ?? '当前项目'

  const emptyState = (
    <div className="mx-auto max-w-2xl pt-10 text-center">
      <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-md border border-accentSoft/60 bg-accentSoft/20">
        <Sparkles size={18} className="text-accent" />
      </div>
      <h2 className="mt-4 text-xl font-semibold">开始一段新的对话</h2>
      <p className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-dim">
        直接提问、贴报错，或让 Nova 在沙箱里真实跑代码验证；接入本机后还能直接操作你的电脑。
      </p>

      <div className="mt-7 grid gap-2.5 sm:grid-cols-3">
        <div className="rounded-md border border-edge bg-panel/50 p-3.5 text-left">
          <MessageSquare size={14} className="text-accent" />
          <p className="mt-1.5 text-sm font-medium text-ink">直接提问</p>
          <p className="mt-0.5 text-xs leading-relaxed text-dim">无需任何配置，问代码、贴报错，回答带证据。</p>
        </div>
        <button
          onClick={openLocalAgent}
          className="rounded-md border border-edge bg-panel/50 p-3.5 text-left transition-colors duration-150 hover:border-accent/40"
        >
          <MonitorDown size={14} className="text-accent" />
          <p className="mt-1.5 text-sm font-medium text-ink">连接你的电脑</p>
          <p className="mt-0.5 text-xs leading-relaxed text-dim">挂上 nova agent，Nova 能在你的真实电脑上执行命令、生成文件。</p>
        </button>
        <button
          onClick={() => openRunPanel(selectedRepoIds[0])}
          className="rounded-md border border-edge bg-panel/50 p-3.5 text-left transition-colors duration-150 hover:border-accent/40"
        >
          <Wrench size={14} className="text-accent" />
          <p className="mt-1.5 text-sm font-medium text-ink">用 /fix 修 Bug</p>
          <p className="mt-0.5 text-xs leading-relaxed text-dim">输入 /fix + 问题描述：先复现失败，再修复到测试通过，最后等你批准。</p>
        </button>
      </div>

      <p className="mt-8 font-mono text-2xs uppercase tracking-[0.12em] text-faint">试试这些问题</p>
      <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
        {EXAMPLES.map((example) => (
          <button
            key={example.title}
            className="rounded-md border border-edge bg-panel/60 p-3 text-left transition-colors duration-150 hover:border-accent/40 hover:bg-panel"
            onClick={() => sendPrompt(example.text, selectedRepoIds)}
          >
            <p className="text-sm font-medium text-ink">{example.title}</p>
            <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-dim">{example.text}</p>
          </button>
        ))}
      </div>
      <p className="mt-5 text-2xs leading-relaxed text-faint">
        要让 Nova 读懂某个代码项目？在{embedded ? '左' : '右'}侧「项目」面板导入；需要多步验证的修复输入 /fix 即可。
      </p>
    </div>
  )

  return (
    <div className="flex h-full min-h-0">
      <main className="flex min-w-0 flex-1 flex-col">
        {!embedded && (
          <div className="flex shrink-0 items-center gap-2 border-b border-edge/80 bg-panel/25 px-4 py-2">
            <span className="shrink-0 text-2xs font-medium uppercase tracking-[0.12em] text-dim/70">上下文</span>
            <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto py-0.5">
              {readyRepos.length === 0 ? (
                <span className="truncate text-xs text-dim/80">还没有项目 — 把文件夹拖进对话，或在输入框输入 @</span>
              ) : (
                readyRepos.map((repo) => (
                  <button
                    key={repo.id}
                    onClick={() => toggleRepo(repo.id)}
                    className={clsx(
                      'shrink-0 rounded-sm border px-2.5 py-0.5 text-xs transition-colors duration-150',
                      selectedRepoIds.includes(repo.id)
                        ? 'border-accent/70 bg-accentSoft/45 text-ink'
                        : 'border-edge/80 text-dim hover:border-accentSoft hover:text-ink',
                    )}
                    title={repo.source}
                  >
                    {repo.name}
                  </button>
                ))
              )}
            </div>
            <div className="relative shrink-0">
              <button
                onClick={() => setLocalOpen((value) => !value)}
                className={clsx(
                  'flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs transition-colors duration-150',
                  localStatus?.connected
                    ? 'border-ok/50 bg-ok/10 text-ok'
                    : 'border-edge/80 text-dim hover:text-ink',
                )}
                title={localStatus?.connected ? '本机执行器已连接，Nova 可操作你的电脑' : '本机未连接：挂上 nova agent 后，Nova 可在你的电脑上执行命令、生成文件'}
              >
                <MonitorDown size={12} />
                <span className="hidden sm:inline">{localStatus?.connected ? '本机已连接' : '本机未连接'}</span>
              </button>
              {localOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setLocalOpen(false)} />
                  <div className="absolute right-0 top-full z-20 mt-1.5 w-80 rounded-md border border-edge bg-panel p-3 shadow-pop">
                    <p className="text-sm font-semibold">把你的电脑接入 Nova</p>
                    <p className="mt-1 text-xs leading-relaxed text-dim">
                      在本机运行下面的命令（需要 backend 目录里的 nova.py），Nova 就能直接在你的电脑上
                      执行命令、生成文件——每一步都先经你确认。
                    </p>
                    <div className="mt-2 flex items-center gap-1.5 rounded-sm border border-edge bg-base/60 px-2.5 py-2">
                      <code className="min-w-0 flex-1 truncate font-mono text-2xs text-ink">
                        python nova.py agent --dir 你的项目目录
                      </code>
                      <button
                        onClick={() => {
                          void navigator.clipboard.writeText('python nova.py agent --dir 你的项目目录')
                          setCopiedCmd(true)
                          setTimeout(() => setCopiedCmd(false), 1500)
                        }}
                        className="shrink-0 text-dim transition-colors duration-150 hover:text-ink"
                        title="复制命令"
                        aria-label="复制命令"
                      >
                        {copiedCmd ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
                      </button>
                    </div>
                    <p className="mt-1.5 text-2xs leading-relaxed text-faint">
                      前置环境变量 NOVA_URL / NOVA_USERNAME / NOVA_PASSWORD 指向本站；
                      启动后约 3 秒内这里会变成「已连接」。加 --yes 可跳过逐条确认。
                    </p>
                  </div>
                </>
              )}
            </div>
            <button
              onClick={() => setTrajectoryOpen(true)}
              disabled={!sessionId}
              className="flex h-7 shrink-0 items-center gap-1 rounded-md border border-edge/80 px-2 text-xs text-dim transition-colors duration-150 hover:text-ink disabled:opacity-40"
              title="查看本会话完整轨迹"
            >
              <Activity size={12} /> 轨迹
            </button>
            <button
              onClick={() => onOpenWorkspace(selectedRepoIds[0])}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-edge/80 text-dim transition-colors duration-150 hover:text-ink"
              title="打开完整工作区"
              aria-label="打开完整工作区"
            >
              <FolderTree size={13} />
            </button>
            <button
              onClick={() => setDockOpen((value) => !value)}
              className={clsx(
                'hidden h-7 w-7 shrink-0 items-center justify-center rounded-md border transition-colors duration-150 lg:flex',
                dockOpen
                  ? 'border-accent/50 bg-accentSoft/25 text-accent'
                  : 'border-edge/80 text-dim hover:text-ink',
              )}
              title={dockOpen ? '收起右侧面板' : '展开项目与引用面板'}
              aria-label="切换右侧面板"
            >
              <PanelRight size={13} />
            </button>
          </div>
        )}

        <ChatTimeline
          messages={messages}
          streaming={streaming}
          streamText={streamText}
          toolCards={toolCards}
          streamEdits={streamEdits}
          plan={plan}
          approvals={approvals}
          usage={streamUsage}
          onCancelTool={(toolCallId) => {
            if (!sessionId) return
            void api.sessions.cancelTool(sessionId, toolCallId).catch(() => {})
          }}
          onResolveApproval={(toolCallId, approved) => {
            void useChat.getState().resolveApproval(toolCallId, approved)
          }}
          onOpenFile={(path) => onOpenWorkspace(selectedRepoIds[0], path)}
          emptyState={emptyState}
        />

        {turnNotice && (
          <div className="mx-auto mb-1 flex w-full max-w-4xl items-center gap-2 px-4 text-xs">
            <span className={clsx('flex-1', turnNotice.kind === 'incomplete' ? 'text-warn' : 'text-dim')}>
              {turnNotice.message}
            </span>
            {turnNotice.kind === 'incomplete' && (
              <button
                onClick={() => {
                  useChat.setState({ turnNotice: null })
                  sendPrompt('请从中断处继续完成刚才的任务，完成所有步骤后给出总结。', selectedRepoIds)
                }}
                className="shrink-0 rounded-sm border border-accent/50 bg-accentSoft/20 px-2.5 py-1 text-xs text-accent transition-colors duration-150 hover:bg-accentSoft/40"
              >
                继续任务
              </button>
            )}
          </div>
        )}

        {error && (
          <div className="mx-auto mb-1 flex w-full max-w-4xl items-center gap-2 px-4 text-xs text-err">
            <AlertCircle size={13} />
            <span className="flex-1">{error}</span>
            <button onClick={clearError} className="text-dim hover:text-ink" aria-label="关闭">
              <X size={13} />
            </button>
          </div>
        )}

        {commandNotice && (
          <div
            className={clsx(
              'mx-auto mb-1 flex w-full max-w-4xl items-start gap-2 px-4 text-xs',
              commandNotice.tone === 'error' ? 'text-err' : 'text-dim',
            )}
            role="status"
          >
            <AlertCircle size={12} className="mt-0.5 shrink-0" />
            <span className="min-w-0 flex-1 whitespace-pre-line break-words">{commandNotice.text}</span>
            <button
              onClick={() => setCommandNotice(null)}
              className="shrink-0 text-dim hover:text-ink"
              aria-label="关闭命令提示"
            >
              <X size={12} />
            </button>
          </div>
        )}

        <Composer
          disabled={false}
          streaming={streaming}
          model={effectiveModel}
          models={modelChoices}
          modelLabel={modelLabel}
          onModelChange={setModel}
          permissionMode={permissionMode}
          onPermissionChange={setPermissionMode}
          contextCount={selectedRepoIds.length}
          contextMeter={contextMeter}
          attachments={attachments}
          uploading={uploading}
          onAttach={(file) => void uploadAttachment(file)}
          onRemoveAttachment={(id) => void removeAttachment(id)}
          onConfigureModel={onOpenSettings}
          onSend={(content) => {
            sendPrompt(content, selectedRepoIds)
          }}
          onCommand={executeCommand}
          onStop={stop}
          mentionRepoId={selectedRepoIds[0] ?? null}
        />
      </main>

      {/* 旧 Shell 仍在对话右侧临时挂运行面板；新工作台由 ContextRail 承载（Task 5）。 */}
      {!embedded && runOpen && (
        <>
          <div
            className="fixed inset-0 z-30 bg-black/50 lg:hidden"
            onClick={() => useRun.getState().close()}
            aria-hidden="true"
          />
          <aside className="fixed inset-y-0 right-0 z-40 flex w-[min(380px,100vw)] flex-col border-l border-edge bg-panel shadow-2xl lg:static lg:z-auto lg:w-[380px] lg:shrink-0 lg:bg-panel/25 lg:shadow-none">
            <RunPanel />
          </aside>
        </>
      )}

      {!embedded && dockOpen && !runOpen && (
        <aside className="hidden w-[380px] shrink-0 flex-col border-l border-edge/80 bg-panel/25 lg:flex">
          <div className="flex h-10 shrink-0 items-center gap-1 border-b border-edge/70 px-2">
            <button
              onClick={() => setDockTab('project')}
              className={clsx(
                'flex h-7 items-center gap-1 rounded-md px-2 text-xs transition-colors duration-150',
                dockTab === 'project' ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:text-ink',
              )}
            >
              <FolderTree size={12} /> 项目
            </button>
            <button
              onClick={() => setDockTab('refs')}
              className={clsx(
                'flex h-7 items-center gap-1 rounded-md px-2 text-xs transition-colors duration-150',
                dockTab === 'refs' ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:text-ink',
              )}
            >
              <Sparkles size={12} /> 引用
              {refs.length > 0 && (
                <span className="rounded-sm bg-raised px-1 text-2xs text-dim">{refs.length}</span>
              )}
            </button>
            <button
              onClick={() => setDockOpen(false)}
              className="ml-auto flex h-7 w-7 items-center justify-center rounded-md text-dim/60 transition-colors duration-150 hover:bg-raised hover:text-ink"
              title="收起右侧面板"
              aria-label="收起右侧面板"
            >
              <X size={13} />
            </button>
          </div>
          <div className="min-h-0 flex-1">
            {dockTab === 'project' ? (
              <ProjectDock
                selectedRepos={selectedRepoIds}
                onToggleRepo={toggleRepo}
                onOpenWorkspace={onOpenWorkspace}
                onOpenTasks={onOpenTasks ?? ((repoId) => openRunPanel(repoId))}
              />
            ) : (
              <RefPanel refs={refs} />
            )}
          </div>
        </aside>
      )}

      {!embedded && (
        <TrajectoryDrawer
          sessionId={sessionId}
          open={trajectoryOpen}
          onClose={() => setTrajectoryOpen(false)}
        />
      )}

      <Modal
        open={gitDialog !== null}
        onClose={closeGitDialog}
        title={gitDialog?.kind === 'init' ? '初始化 Git' : '提交 Git'}
        width="max-w-md"
      >
        {gitDialog?.kind === 'init' ? (
          <div className="space-y-3">
            <p className="text-sm leading-relaxed text-dim">
              将为「{dialogRepoName}」初始化 Git 仓库并创建首个快照提交，之后每次写入都能回滚。
            </p>
            {dialogError && <p className="text-xs text-err">{dialogError}</p>}
            <div className="flex justify-end gap-2">
              <Button onClick={closeGitDialog} disabled={dialogBusy}>取消</Button>
              <Button variant="primary" onClick={() => void confirmGitDialog()} disabled={dialogBusy}>
                {dialogBusy && <Spinner />} 初始化
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <label className="block text-xs text-dim" htmlFor="nova-commit-message">
              提交消息 <span className="text-faint">（{dialogRepoName} 的全部改动）</span>
            </label>
            <input
              id="nova-commit-message"
              value={commitMessage}
              onChange={(event) => setCommitMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== 'Enter' || event.nativeEvent.isComposing) return
                event.preventDefault()
                void confirmGitDialog()
              }}
              spellCheck={false}
              className="w-full rounded-md border border-edge bg-base px-2.5 py-1.5 font-mono text-sm text-ink outline-none transition-colors duration-150 placeholder:text-faint focus:border-accent/50"
              placeholder="chore: update"
            />
            {dialogError && <p className="text-xs text-err">{dialogError}</p>}
            <div className="flex justify-end gap-2">
              <Button onClick={closeGitDialog} disabled={dialogBusy}>取消</Button>
              <Button
                variant="primary"
                onClick={() => void confirmGitDialog()}
                disabled={dialogBusy || !commitMessage.trim()}
              >
                {dialogBusy && <Spinner />} 提交
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
