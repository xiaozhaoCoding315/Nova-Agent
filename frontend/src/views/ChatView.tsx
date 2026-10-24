import clsx from 'clsx'
import { Activity, AlertCircle, Copy, Check, FolderTree, ListTodo, MessageSquare, MonitorDown, PanelRight, Sparkles, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { Composer } from '../components/Composer'
import { MessageBubble, StreamingBubble } from '../components/MessageBubble'
import { ProjectDock } from '../components/ProjectDock'
import { RefPanel } from '../components/RefPanel'
import { TrajectoryDrawer } from '../components/TrajectoryDrawer'
import { useChat } from '../stores/chat'
import { useLlm } from '../stores/llm'
import { useRepos } from '../stores/repos'
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
  onOpenSettings,
  onOpenWorkspace,
  onOpenTasks,
}: {
  onOpenSettings: () => void
  onOpenWorkspace: (repoId?: string, path?: string) => void
  onOpenTasks: (repoId?: string) => void
}) {
  const {
    sessionId, messages, streaming, streamText, toolCards, streamEdits, refs, error,
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
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)

  useEffect(() => {
    void refresh()
    const pollLocal = () => void api.local.status().then(setLocalStatus).catch(() => {})
    pollLocal()
    const timer = setInterval(pollLocal, 20_000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [messages.length, streamText, toolCards.length])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

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

  return (
    <div className="flex h-full min-h-0">
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex shrink-0 items-center gap-2 border-b border-edge/80 bg-panel/25 px-4 py-2">
          <span className="shrink-0 text-[10px] font-medium uppercase tracking-[0.12em] text-dim/70">上下文</span>
          <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto py-0.5">
            {readyRepos.length === 0 ? (
              <span className="truncate text-[11px] text-dim/80">还没有项目 — 把文件夹拖进对话，或在输入框输入 @</span>
            ) : (
              readyRepos.map((repo) => (
                <button
                  key={repo.id}
                  onClick={() => toggleRepo(repo.id)}
                  className={clsx(
                    'shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] transition-colors',
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
                'flex h-7 items-center gap-1.5 rounded-lg border px-2 text-[11px] transition-colors',
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
                <div className="absolute right-0 top-full z-20 mt-1.5 w-80 rounded-xl border border-edge bg-panel p-3 shadow-xl">
                  <p className="text-[12.5px] font-semibold">把你的电脑接入 Nova</p>
                  <p className="mt-1 text-[11px] leading-relaxed text-dim">
                    在本机运行下面的命令（需要 backend 目录里的 nova.py），Nova 就能直接在你的电脑上
                    执行命令、生成文件——每一步都先经你确认。
                  </p>
                  <div className="mt-2 flex items-center gap-1.5 rounded-lg border border-edge bg-base/60 px-2.5 py-2">
                    <code className="min-w-0 flex-1 truncate font-mono text-[10.5px] text-ink">
                      python nova.py agent --dir 你的项目目录
                    </code>
                    <button
                      onClick={() => {
                        void navigator.clipboard.writeText('python nova.py agent --dir 你的项目目录')
                        setCopiedCmd(true)
                        setTimeout(() => setCopiedCmd(false), 1500)
                      }}
                      className="shrink-0 text-dim hover:text-ink"
                      title="复制命令"
                      aria-label="复制命令"
                    >
                      {copiedCmd ? <Check size={12} className="text-ok" /> : <Copy size={12} />}
                    </button>
                  </div>
                  <p className="mt-1.5 text-[10px] leading-relaxed text-dim/70">
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
            className="flex h-7 shrink-0 items-center gap-1 rounded-lg border border-edge/80 px-2 text-[11px] text-dim transition-colors hover:text-ink disabled:opacity-40"
            title="查看本会话完整轨迹"
          >
            <Activity size={12} /> 轨迹
          </button>
          <button
            onClick={() => onOpenWorkspace(selectedRepoIds[0])}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-edge/80 text-dim transition-colors hover:text-ink"
            title="打开完整工作区"
            aria-label="打开完整工作区"
          >
            <FolderTree size={13} />
          </button>
          <button
            onClick={() => setDockOpen((value) => !value)}
            className={clsx(
              'hidden h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition-colors lg:flex',
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

        <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 py-5">
          <div className="mx-auto max-w-5xl space-y-6">
            {messages.length === 0 && !streaming && (
              <div className="mx-auto max-w-2xl pt-10 text-center">
                <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl border border-accentSoft/60 bg-accentSoft/20">
                  <Sparkles size={18} className="text-accent" />
                </div>
                <h2 className="mt-4 text-[18px] font-semibold">开始一段新的对话</h2>
                <p className="mx-auto mt-1.5 max-w-md text-[12.5px] leading-relaxed text-dim">
                  直接提问、贴报错，或让 Nova 在沙箱里真实跑代码验证；接入本机后还能直接操作你的电脑。
                </p>

                <div className="mt-7 grid gap-2.5 sm:grid-cols-3">
                  <div className="rounded-xl border border-edge bg-panel/50 p-3.5 text-left">
                    <MessageSquare size={14} className="text-accent" />
                    <p className="mt-1.5 text-[12.5px] font-medium text-ink">直接提问</p>
                    <p className="mt-0.5 text-[11px] leading-relaxed text-dim">无需任何配置，问代码、贴报错，回答带证据。</p>
                  </div>
                  <button
                    onClick={() => setLocalOpen(true)}
                    className="rounded-xl border border-edge bg-panel/50 p-3.5 text-left transition-colors hover:border-accentSoft"
                  >
                    <MonitorDown size={14} className="text-accent" />
                    <p className="mt-1.5 text-[12.5px] font-medium text-ink">连接你的电脑</p>
                    <p className="mt-0.5 text-[11px] leading-relaxed text-dim">挂上 nova agent，Nova 能在你的真实电脑上执行命令、生成文件。</p>
                  </button>
                  <button
                    onClick={() => onOpenTasks(selectedRepoIds[0])}
                    className="rounded-xl border border-edge bg-panel/50 p-3.5 text-left transition-colors hover:border-accentSoft"
                  >
                    <ListTodo size={14} className="text-accent" />
                    <p className="mt-1.5 text-[12.5px] font-medium text-ink">大任务走流水线</p>
                    <p className="mt-0.5 text-[11px] leading-relaxed text-dim">修 Bug / 多文件改动，逐步真实验证，最后统一等你批准。</p>
                  </button>
                </div>

                <p className="mt-8 text-[11px] uppercase tracking-[0.12em] text-dim/60">试试这些问题</p>
                <div className="mt-3 grid gap-2.5 sm:grid-cols-3">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example.title}
                      className="rounded-xl border border-edge bg-panel/60 p-3 text-left transition-colors hover:border-accentSoft hover:bg-panel"
                      onClick={() => void send(example.text, selectedRepoIds)}
                    >
                      <p className="text-[12.5px] font-medium text-ink">{example.title}</p>
                      <p className="mt-1 line-clamp-3 text-[11.5px] leading-relaxed text-dim">{example.text}</p>
                    </button>
                  ))}
                </div>
                <p className="mt-5 text-[10.5px] leading-relaxed text-dim/60">
                  要让 Nova 读懂某个代码项目？在右侧「项目」面板导入；需要多步验证的修复或功能交给「任务」。
                </p>
              </div>
            )}

            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {streaming && (
              <StreamingBubble text={streamText} toolCards={toolCards} editProposals={streamEdits} usage={streamUsage} />
            )}
          </div>
        </div>

        {turnNotice && (
          <div className="mx-auto mb-1 flex w-full max-w-5xl items-center gap-2 px-4 text-[11.5px]">
            <span className={clsx('flex-1', turnNotice.kind === 'incomplete' ? 'text-warn' : 'text-dim')}>
              {turnNotice.message}
            </span>
            {turnNotice.kind === 'incomplete' && (
              <button
                onClick={() => {
                  useChat.setState({ turnNotice: null })
                  void send('请从中断处继续完成刚才的任务，完成所有步骤后给出总结。', selectedRepoIds)
                }}
                className="shrink-0 rounded-lg border border-accent/50 bg-accentSoft/20 px-2.5 py-1 text-[11px] text-accent transition-colors hover:bg-accentSoft/40"
              >
                继续任务
              </button>
            )}
          </div>
        )}

        {error && (
          <div className="mx-auto mb-1 flex w-full max-w-5xl items-center gap-2 px-4 text-[12px] text-err">
            <AlertCircle size={13} />
            <span className="flex-1">{error}</span>
            <button onClick={clearError} className="text-dim hover:text-ink" aria-label="关闭">
              <X size={13} />
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
            void send(content, selectedRepoIds)
          }}
          onStop={stop}
        />
      </main>

      {dockOpen && (
        <aside className="hidden w-[380px] shrink-0 flex-col border-l border-edge/80 bg-panel/25 lg:flex">
          <div className="flex h-10 shrink-0 items-center gap-1 border-b border-edge/70 px-2">
            <button
              onClick={() => setDockTab('project')}
              className={clsx(
                'flex h-7 items-center gap-1 rounded-md px-2 text-[11px] transition-colors',
                dockTab === 'project' ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:text-ink',
              )}
            >
              <FolderTree size={12} /> 项目
            </button>
            <button
              onClick={() => setDockTab('refs')}
              className={clsx(
                'flex h-7 items-center gap-1 rounded-md px-2 text-[11px] transition-colors',
                dockTab === 'refs' ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:text-ink',
              )}
            >
              <Sparkles size={12} /> 引用
              {refs.length > 0 && (
                <span className="rounded bg-raised px-1 text-[9.5px] text-dim">{refs.length}</span>
              )}
            </button>
            <button
              onClick={() => setDockOpen(false)}
              className="ml-auto flex h-7 w-7 items-center justify-center rounded-md text-dim/60 transition-colors hover:bg-raised hover:text-ink"
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
                onOpenTasks={onOpenTasks}
              />
            ) : (
              <RefPanel refs={refs} />
            )}
          </div>
        </aside>
      )}

      <TrajectoryDrawer
        sessionId={sessionId}
        open={trajectoryOpen}
        onClose={() => setTrajectoryOpen(false)}
      />

    </div>
  )
}
