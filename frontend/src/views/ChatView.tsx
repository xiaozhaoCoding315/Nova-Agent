import clsx from 'clsx'
import { Activity, AlertCircle, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Composer } from '../components/Composer'
import { MessageBubble, StreamingBubble } from '../components/MessageBubble'
import { RefPanel } from '../components/RefPanel'
import { SessionList } from '../components/SessionList'
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
    permissionMode, setPermissionMode,
    loadSessions, selectSession, newSession, deleteSession, send, stop, clearError,
  } = useChat()
  const { repos, refresh } = useRepos()
  const [selectedRepos, setSelectedRepos] = useState<string[]>([])
  const [trajectoryOpen, setTrajectoryOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)

  useEffect(() => {
    void loadSessions()
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!sessionId) {
      setSelectedRepos([])
      return
    }
    const current = sessions.find((s) => s.id === sessionId)
    setSelectedRepos(current?.repo_ids ?? [])
    // Restore the persisted selection when switching sessions. The meta event
    // updates sessionId and the session entry atomically, so reading sessions
    // here sees the new repo_ids.
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

  const readyRepos = repos.filter((r) => r.status === 'ready')

  const toggleRepo = (id: string) => {
    setSelectedRepos((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  return (
    <div className="flex h-full min-h-0">
      <aside className="hidden w-60 shrink-0 border-r border-edge bg-panel md:block">
        <SessionList
          sessions={sessions}
          activeId={sessionId}
          onSelect={(id) => void selectSession(id)}
          onNew={newSession}
          onDelete={(id) => void deleteSession(id)}
        />
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-edge bg-panel/60 px-4 py-2">
          <select
            className="max-w-[45%] rounded-md border border-edge bg-raised px-2 py-1 text-[12px] text-ink outline-none md:hidden"
            value={sessionId ?? ''}
            onChange={(e) => {
              const value = e.target.value
              if (!value) newSession()
              else void selectSession(value)
            }}
            aria-label="切换会话"
          >
            <option value="">新对话</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.title}
              </option>
            ))}
          </select>
          <span className="shrink-0 text-[11.5px] text-dim">关联仓库</span>
          <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto py-0.5">
            {readyRepos.length === 0 ? (
              <span className="truncate text-[11.5px] text-dim">暂无就绪仓库，去「工作区」导入 ZIP 或 Git 仓库</span>
            ) : (
              readyRepos.map((repo) => (
                <button
                  key={repo.id}
                  onClick={() => toggleRepo(repo.id)}
                  className={clsx(
                    'shrink-0 rounded-full border px-2.5 py-1 text-[11.5px] transition-colors',
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
          <button
            onClick={() => setTrajectoryOpen(true)}
            disabled={!sessionId}
            className="flex shrink-0 items-center gap-1 rounded-md border border-edge px-2 py-1 text-[11.5px] text-dim hover:text-ink disabled:opacity-40"
            title="查看本会话的完整执行轨迹（检索/工具/审批）"
          >
            <Activity size={12} /> 轨迹
          </button>
          <select
            value={permissionMode}
            onChange={(e) => setPermissionMode(e.target.value as 'readonly' | 'ask' | 'auto')}
            className="shrink-0 rounded-md border border-edge bg-raised px-2 py-1 text-[11.5px] text-dim outline-none"
            title="权限模式：只读不写入；确认模式下修改先生成提案；自动模式直接写入"
          >
            <option value="readonly">只读</option>
            <option value="ask">确认写入</option>
            <option value="auto">自动执行</option>
          </select>
        </div>

        <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-4 py-5">
          <div className="mx-auto max-w-3xl space-y-5">
            {messages.length === 0 && !streaming && (
              <div className="pt-10 text-center">
                <h2 className="text-[17px] font-semibold">给 Nova 派活</h2>
                <p className="mt-1.5 text-[13px] text-dim">
                  读懂代码 · 定位报错 · 沙箱里写代码并验证 —— 关联一个仓库后，回答会带 文件:行号 引用
                </p>
                <div className="mt-6 grid gap-2.5 sm:grid-cols-3">
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex.title}
                      className="rounded-xl border border-edge bg-panel/70 p-3 text-left transition-colors hover:border-accentSoft"
                      onClick={() => void send(ex.text, selectedRepos)}
                    >
                      <p className="text-[13px] font-medium text-ink">{ex.title}</p>
                      <p className="mt-1 line-clamp-3 text-[12px] leading-relaxed text-dim">{ex.text}</p>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
            {streaming && (
              <StreamingBubble text={streamText} toolCards={toolCards} editProposals={streamEdits} />
            )}
          </div>
        </div>

        {error && (
          <div className="mx-auto mb-1 flex w-full max-w-3xl items-center gap-2 px-4 text-[12.5px] text-err">
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

      <aside className="hidden w-72 shrink-0 border-l border-edge bg-panel lg:flex lg:flex-col">
        <div className="min-h-0 flex-1">
          <RefPanel refs={refs} />
        </div>
      </aside>

      <TrajectoryDrawer
        sessionId={sessionId}
        open={trajectoryOpen}
        onClose={() => setTrajectoryOpen(false)}
      />
    </div>
  )
}