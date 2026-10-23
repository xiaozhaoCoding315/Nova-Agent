import clsx from 'clsx'
import { Activity, AlertCircle, PanelRight, Sparkles, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Composer } from '../components/Composer'
import { MessageBubble, StreamingBubble } from '../components/MessageBubble'
import { RefPanel } from '../components/RefPanel'
import { TrajectoryDrawer } from '../components/TrajectoryDrawer'
import { useChat } from '../stores/chat'
import { useRepos } from '../stores/repos'

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

export function ChatView() {
  const {
    sessions, sessionId, messages, streaming, streamText, toolCards, streamEdits, refs, error,
    permissionMode, setPermissionMode, send, stop, clearError,
  } = useChat()
  const { repos, refresh } = useRepos()
  const [selectedRepos, setSelectedRepos] = useState<string[]>([])
  const [trajectoryOpen, setTrajectoryOpen] = useState(false)
  const [refsOpen, setRefsOpen] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!sessionId) {
      setSelectedRepos([])
      return
    }
    const current = sessions.find((session) => session.id === sessionId)
    setSelectedRepos(current?.repo_ids ?? [])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  useEffect(() => {
    const el = scrollRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [messages.length, streamText, toolCards.length])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  const currentSession = sessions.find((session) => session.id === sessionId)
  const readyRepos = repos.filter((repo) => repo.status === 'ready')

  const toggleRepo = (id: string) => {
    setSelectedRepos((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  return (
    <div className="flex h-full min-h-0">
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="shrink-0 border-b border-edge bg-panel/40">
          <div className="flex items-center gap-3 px-5 py-2.5">
            <div className="min-w-0">
              <h1 className="truncate text-[13.5px] font-semibold">
                {currentSession?.title ?? '新对话'}
              </h1>
              <p className="mt-0.5 text-[10.5px] text-dim">
                {messages.length} 条消息 · {selectedRepos.length > 0 ? `${selectedRepos.length} 个关联仓库` : '未关联仓库'}
              </p>
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-1.5">
              <button
                onClick={() => setTrajectoryOpen(true)}
                disabled={!sessionId}
                className="flex items-center gap-1 rounded-md border border-edge px-2 py-1 text-[11.5px] text-dim transition-colors hover:text-ink disabled:opacity-40"
                title="查看本会话完整轨迹"
              >
                <Activity size={12} /> 轨迹
              </button>
              <select
                value={permissionMode}
                onChange={(event) => setPermissionMode(event.target.value as 'readonly' | 'ask' | 'auto')}
                className="rounded-md border border-edge bg-raised px-2 py-1 text-[11.5px] text-dim outline-none"
                title="权限模式：只读 / 确认写入 / 自动执行"
              >
                <option value="readonly">只读</option>
                <option value="ask">确认写入</option>
                <option value="auto">自动执行</option>
              </select>
              <button
                onClick={() => setRefsOpen((value) => !value)}
                className={clsx(
                  'hidden h-7 w-7 items-center justify-center rounded-md border transition-colors lg:flex',
                  refsOpen
                    ? 'border-accentSoft bg-accentSoft/20 text-accent'
                    : 'border-edge text-dim hover:text-ink',
                )}
                title={refsOpen ? '收起引用面板' : '展开引用面板'}
                aria-label="切换引用面板"
              >
                <PanelRight size={13} />
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2 border-t border-edge/60 px-5 py-1.5">
            <span className="shrink-0 text-[10.5px] uppercase tracking-wide text-dim">上下文</span>
            <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto py-0.5">
              {readyRepos.length === 0 ? (
                <span className="truncate text-[11px] text-dim">暂无就绪仓库，去「工作区」导入 ZIP 或 Git 仓库</span>
              ) : (
                readyRepos.map((repo) => (
                  <button
                    key={repo.id}
                    onClick={() => toggleRepo(repo.id)}
                    className={clsx(
                      'shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] transition-colors',
                      selectedRepos.includes(repo.id)
                        ? 'border-accent bg-accentSoft/50 text-ink'
                        : 'border-edge text-dim hover:text-ink',
                    )}
                    title={repo.source}
                  >
                    {repo.name}
                  </button>
                ))
              )}
            </div>
          </div>
        </div>

        <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 py-5">
          <div className="mx-auto max-w-3xl space-y-6">
            {messages.length === 0 && !streaming && (
              <div className="mx-auto max-w-2xl pt-10 text-center">
                <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-2xl border border-accentSoft/60 bg-accentSoft/20">
                  <Sparkles size={18} className="text-accent" />
                </div>
                <h2 className="mt-4 text-[18px] font-semibold">开始一段新的对话</h2>
                <p className="mx-auto mt-1.5 max-w-md text-[12.5px] leading-relaxed text-dim">
                  关联仓库后，Nova 会读懂代码、定位报错、在沙箱里运行验证，并给每个结论附上证据。
                </p>
                <div className="mt-6 grid gap-2.5 sm:grid-cols-3">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example.title}
                      className="rounded-xl border border-edge bg-panel/60 p-3 text-left transition-colors hover:border-accentSoft hover:bg-panel"
                      onClick={() => void send(example.text, selectedRepos)}
                    >
                      <p className="text-[12.5px] font-medium text-ink">{example.title}</p>
                      <p className="mt-1 line-clamp-3 text-[11.5px] leading-relaxed text-dim">{example.text}</p>
                    </button>
                  ))}
                </div>
                <p className="mt-5 text-[10.5px] text-dim/60">
                  提示：左侧会话可重命名或删除；Ctrl/⌘ + B 收起侧栏
                </p>
              </div>
            )}

            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {streaming && (
              <StreamingBubble text={streamText} toolCards={toolCards} editProposals={streamEdits} />
            )}
          </div>
        </div>

        {error && (
          <div className="mx-auto mb-1 flex w-full max-w-3xl items-center gap-2 px-4 text-[12px] text-err">
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
          onSend={(content) => void send(content, selectedRepos)}
          onStop={stop}
        />
      </main>

      {refsOpen && (
        <aside className="hidden w-72 shrink-0 border-l border-edge bg-panel/40 lg:flex lg:flex-col">
          <div className="min-h-0 flex-1">
            <RefPanel refs={refs} />
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
