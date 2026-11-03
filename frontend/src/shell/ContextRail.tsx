import clsx from 'clsx'
import {
  ArrowLeft, FlaskConical, GitBranch, PanelRightClose, RefreshCw,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { EditCard } from '../components/EditCard'
import { FileTree } from '../components/FileTree'
import { ImpactPanel } from '../components/ImpactPanel'
import { RefPanel } from '../components/RefPanel'
import { Badge, EmptyState, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { FileNode } from '../lib/types'
import { repoStatus, RUN_STATUS, selectClass } from '../lib/ui'
import { useChat } from '../stores/chat'
import { useRepos } from '../stores/repos'
import { useRun } from '../stores/run'
import { RunPanel } from '../timeline/RunPanel'
import type { WorkspaceTab } from '../views/WorkspaceView'

const RAIL_TAB_KEY = 'nova.rail.tab'

const TABS = [
  { key: 'files', label: '文件' },
  { key: 'refs', label: '引用' },
  { key: 'impact', label: '影响' },
  { key: 'changes', label: '变更' },
] as const

type RailTab = (typeof TABS)[number]['key']

const railTabId = (key: RailTab) => `rail-tab-${key}`
const railPanelId = 'rail-tab-panel'

function readRailTab(): RailTab {
  try {
    const raw = localStorage.getItem(RAIL_TAB_KEY)
    return TABS.some((tab) => tab.key === raw) ? (raw as RailTab) : 'files'
  } catch {
    return 'files'
  }
}

function countFiles(nodes: FileNode[]): number {
  return nodes.reduce(
    (total, node) => total + (node.type === 'dir' ? countFiles(node.children) : 1),
    0,
  )
}

function countDiffFiles(diff: string | null): number {
  return diff ? diff.match(/^diff --git /gm)?.length ?? 0 : 0
}

/** 右栏：文件 / 引用 / 影响 / 变更；有待查看的 /fix 任务时切换为运行面板。 */
export function ContextRail({
  open,
  collapsed,
  active,
  repoId,
  onClose,
  onToggle,
  onOpenFile,
  onOpenWorkspace,
}: {
  /** `< lg` 覆盖层是否展开。桌面是否可见由 `collapsed` 决定。 */
  open: boolean
  /** `lg+` 收起状态（持久化在 nova.rail.collapsed）。 */
  collapsed: boolean
  /** 右栏当前是否可见：可见时才会拉取文件树与 diff。 */
  active: boolean
  repoId?: string
  onClose: () => void
  onToggle: () => void
  onOpenFile: (path: string, repoId?: string) => void
  onOpenWorkspace: (options: { repoId?: string; path?: string; tab: WorkspaceTab }) => void
}) {
  const refs = useChat((state) => state.refs)
  const streamEdits = useChat((state) => state.streamEdits)
  const repos = useRepos((state) => state.repos)
  const runTask = useRun((state) => state.task)
  const runOpen = useRun((state) => state.open)

  const [tab, setTab] = useState<RailTab>(readRailTab)
  const [repoOverride, setRepoOverride] = useState<string | null>(null)
  const [lastPath, setLastPath] = useState<string | null>(null)
  const [tree, setTree] = useState<FileNode[]>([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [treeError, setTreeError] = useState<string | null>(null)
  const [treeTick, setTreeTick] = useState(0)
  const [diff, setDiff] = useState<string | null>(null)
  const [diffLoading, setDiffLoading] = useState(false)
  const [diffError, setDiffError] = useState<string | null>(null)
  const [diffTick, setDiffTick] = useState(0)

  useEffect(() => {
    try {
      localStorage.setItem(RAIL_TAB_KEY, tab)
    } catch {
      /* localStorage 不可用时只失去页签记忆 */
    }
  }, [tab])

  // 对话切换项目时回到「当前项目」，不让上一次的手动切换一直覆盖。
  useEffect(() => {
    setRepoOverride(null)
    setLastPath(null)
  }, [repoId])

  // 项目被移除后，手动覆盖的 id 不应继续生效（否则下拉框选不中任何项）。
  useEffect(() => {
    if (repoOverride && !repos.some((repo) => repo.id === repoOverride)) {
      setRepoOverride(null)
    }
  }, [repoOverride, repos])

  const overrideRepoId = repoOverride && repos.some((repo) => repo.id === repoOverride)
    ? repoOverride
    : null
  const activeRepoId = overrideRepoId ?? repoId ?? repos[0]?.id ?? null
  const activeRepo = repos.find((repo) => repo.id === activeRepoId) ?? null

  useEffect(() => {
    if (!active) return
    if (tab !== 'files' || !activeRepo || activeRepo.status !== 'ready') {
      if (activeRepo?.status !== 'ready') {
        setTree([])
        setTreeError(null)
      }
      return
    }
    let cancelled = false
    setTreeLoading(true)
    setTreeError(null)
    api.repos
      .tree(activeRepo.id)
      .then((nodes) => {
        if (!cancelled) setTree(nodes)
      })
      .catch((err) => {
        if (!cancelled) setTreeError(err instanceof ApiError ? err.message : '加载文件树失败')
      })
      .finally(() => {
        if (!cancelled) setTreeLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [active, tab, activeRepo?.id, activeRepo?.status, treeTick])

  useEffect(() => {
    if (!active) return
    if (tab !== 'changes' || !activeRepo || activeRepo.status !== 'ready') {
      setDiff(null)
      setDiffError(null)
      setDiffLoading(false)
      return
    }
    let cancelled = false
    setDiffLoading(true)
    setDiffError(null)
    api.git
      .diff(activeRepo.id)
      .then(({ diff: text }) => {
        if (!cancelled) setDiff(text)
      })
      .catch((err) => {
        if (!cancelled) {
          setDiff(null)
          setDiffError(err instanceof ApiError ? err.message : '读取工作区变更失败')
        }
      })
      .finally(() => {
        if (!cancelled) setDiffLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [active, tab, activeRepo?.id, activeRepo?.status, diffTick])

  // 恢复任务失败时 task 为 null 但 open 仍为 true：仍要挂载 RunPanel 展示错误。
  const runActive = runOpen
  const runMeta = runTask
    ? RUN_STATUS[runTask.status] ?? { label: runTask.status, tone: 'dim' as const }
    : null
  const diffFiles = countDiffFiles(diff)
  const counts = useMemo<Record<RailTab, number>>(() => ({
    files: countFiles(tree),
    refs: refs.length,
    impact: 0,
    changes: streamEdits.length > 0 ? streamEdits.length : diffFiles,
  }), [tree, refs.length, streamEdits.length, diffFiles])

  /** 关闭只隐藏视图并停止轮询，任务保留；重新打开时先补一次最新状态。 */
  const reopenRun = () => {
    useRun.setState({ open: true })
    void useRun.getState().refresh()
  }

  // 末尾换行会 split 出一个空元素，计数前去掉，避免 200 行显示成 201。
  const diffLines = useMemo(() => {
    const lines = (diff ?? '').split('\n')
    if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop()
    return lines
  }, [diff])
  const diffPreview = diffLines.slice(0, 200)

  return (
    <>
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <aside
        aria-label="上下文栏"
        className={clsx(
          'w-[320px] shrink-0 flex-col border-l border-edge bg-panel lg:bg-panel/50',
          open
            ? 'fixed inset-y-0 right-0 z-40 flex max-w-[92vw] shadow-pop lg:static lg:z-auto lg:max-w-none lg:shadow-none'
            : 'hidden lg:flex',
          collapsed && 'lg:hidden',
        )}
      >
        <header className="flex h-11 shrink-0 items-center gap-1 border-b border-edge px-2 font-mono">
          {runActive ? (
            <>
              <button
                onClick={() => useRun.getState().close()}
                className="flex h-7 shrink-0 items-center gap-1 rounded-md px-1.5 text-xs text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
                title="返回上下文页签"
                aria-label="返回上下文页签"
              >
                <ArrowLeft size={13} /> 返回
              </button>
              <span className="shrink-0 text-xs text-ink">运行</span>
              {runMeta && (
                <Badge tone={runMeta.tone}>{runMeta.label}</Badge>
              )}
              <button
                onClick={onToggle}
                className="ml-auto flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
                title="收起上下文栏"
                aria-label="收起上下文栏"
              >
                <PanelRightClose size={13} />
              </button>
            </>
          ) : (
            <>
              <div
                role="tablist"
                aria-label="上下文页签"
                className="flex min-w-0 flex-1 items-center gap-0.5"
              >
                {TABS.map((item) => {
                  const active = tab === item.key
                  const count = counts[item.key]
                  return (
                    <button
                      key={item.key}
                      id={railTabId(item.key)}
                      role="tab"
                      aria-selected={active}
                      aria-controls={railPanelId}
                      tabIndex={active ? 0 : -1}
                      onClick={() => setTab(item.key)}
                      onKeyDown={(event) => {
                        const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
                        const index = TABS.findIndex((tab) => tab.key === item.key)
                        let next: RailTab | null = null
                        if (step) next = TABS[(index + step + TABS.length) % TABS.length].key
                        else if (event.key === 'Home') next = TABS[0].key
                        else if (event.key === 'End') next = TABS[TABS.length - 1].key
                        if (!next) return
                        event.preventDefault()
                        setTab(next)
                        document.getElementById(railTabId(next))?.focus()
                      }}
                      className={clsx(
                        'flex h-7 min-w-0 flex-1 items-center justify-center gap-1 rounded-sm px-1 text-2xs transition-colors duration-150',
                        active ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
                      )}
                    >
                      <span className="truncate">{item.label}</span>
                      {count > 0 && (
                        <span
                          className={clsx(
                            'shrink-0 rounded-sm px-1 font-mono text-2xs',
                            active ? 'bg-accentSoft text-accent' : 'bg-raised text-faint',
                          )}
                        >
                          {count}
                        </span>
                      )}
                    </button>
                  )
                })}
              </div>
              {runTask && (
                <button
                  onClick={reopenRun}
                  className="flex h-7 shrink-0 items-center gap-1 rounded-md px-1.5 text-2xs text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
                  title={`打开运行面板：${runTask.title}`}
                  aria-label="打开运行面板"
                >
                  <FlaskConical size={12} className="text-accent" />
                  运行
                </button>
              )}
              <button
                onClick={onToggle}
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
                title="收起上下文栏"
                aria-label="收起上下文栏"
              >
                <PanelRightClose size={13} />
              </button>
            </>
          )}
        </header>

        <div className="min-h-0 flex-1 overflow-hidden">
          {runActive ? (
            <RunPanel />
          ) : (
            <div
              id={railPanelId}
              role="tabpanel"
              aria-labelledby={railTabId(tab)}
              className="h-full min-h-0"
            >
              {tab === 'files' && (
                <div className="flex h-full min-h-0 flex-col">
                  <div className="shrink-0 border-b border-edge/70 px-2 py-1.5">
                    <select
                      value={activeRepoId ?? ''}
                      onChange={(event) => {
                        setRepoOverride(event.target.value || null)
                        setLastPath(null)
                      }}
                      disabled={repos.length === 0}
                      className={selectClass}
                      aria-label="切换上下文项目"
                    >
                      {repos.length === 0 && <option value="">暂无项目</option>}
                      {repos.map((repo) => (
                        <option key={repo.id} value={repo.id}>
                          {repo.name}
                          {repo.status === 'ready' ? '' : `（${repoStatus(repo.status).label}）`}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto px-1 py-1">
                    {!activeRepo ? (
                      <p className="px-3 py-4 text-xs leading-relaxed text-dim">
                        还没有项目。从左侧项目栏导入项目后，这里会显示文件树。
                      </p>
                    ) : activeRepo.status !== 'ready' ? (
                      <p className="px-3 py-4 text-xs leading-relaxed text-dim">
                        项目{repoStatus(activeRepo.status).label}，索引完成后显示文件树。
                      </p>
                    ) : treeLoading ? (
                      <p className="flex items-center gap-2 px-3 py-3 text-xs text-dim">
                        <Spinner /> 加载文件树…
                      </p>
                    ) : treeError ? (
                      <div className="space-y-1.5 px-3 py-3">
                        <p className="text-xs leading-relaxed text-err">{treeError}</p>
                        <button
                          onClick={() => setTreeTick((value) => value + 1)}
                          className="flex h-6 items-center gap-1 rounded-sm border border-edge px-1.5 text-2xs text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink"
                          aria-label="重试加载文件树"
                        >
                          <RefreshCw size={11} /> 重试
                        </button>
                      </div>
                    ) : (
                      <FileTree
                        nodes={tree}
                        selectedPath={lastPath}
                        onSelect={(path) => {
                          setLastPath(path)
                          onOpenFile(path, activeRepo.id)
                        }}
                      />
                    )}
                  </div>
                </div>
              )}

              {tab === 'refs' && (
                <div className="h-full min-h-0">
                  <RefPanel refs={refs} />
                </div>
              )}

              {tab === 'impact' && (
                !activeRepo ? (
                  <EmptyState
                    title="尚未选择项目"
                    hint="选择项目后，可以分析函数、类或文件改动会影响哪些代码。"
                  />
                ) : activeRepo.status !== 'ready' ? (
                  <EmptyState
                    title="项目尚未就绪"
                    hint={`项目${repoStatus(activeRepo.status).label}，索引完成后可以分析影响范围。`}
                  />
                ) : (
                  <ImpactPanel
                    repoId={activeRepo.id}
                    onOpenFile={(path) => onOpenFile(path, activeRepo.id)}
                  />
                )
              )}

              {tab === 'changes' && (
                <div className="flex h-full min-h-0 flex-col">
                  <div className="flex shrink-0 items-center gap-1.5 border-b border-edge/70 px-2 py-1.5">
                    <span className="min-w-0 flex-1 truncate text-2xs uppercase tracking-[0.12em] text-faint">
                      {activeRepo?.name ?? '未选择项目'}
                    </span>
                    <button
                      onClick={() => setDiffTick((value) => value + 1)}
                      className="flex h-6 w-6 shrink-0 items-center justify-center rounded-sm text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
                      title="刷新工作区变更"
                      aria-label="刷新工作区变更"
                    >
                      <RefreshCw size={11} />
                    </button>
                    <button
                      onClick={() => onOpenWorkspace({ repoId: activeRepo?.id, tab: 'git' })}
                      disabled={!activeRepo || activeRepo.status !== 'ready'}
                      className="flex h-6 shrink-0 items-center gap-1 rounded-sm border border-edge px-1.5 text-2xs text-dim transition-colors duration-150 hover:border-accent/40 hover:text-ink disabled:opacity-40"
                      title="在抽屉中打开 Git 交付面板"
                    >
                      <GitBranch size={11} /> 打开 Git
                    </button>
                  </div>
                  <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-2">
                    {streamEdits.length > 0 && (
                      <section className="space-y-1.5">
                        <h3 className="text-2xs uppercase tracking-[0.12em] text-faint">
                          本次会话编辑提案（{streamEdits.length}）
                        </h3>
                        {streamEdits.map((edit) => <EditCard key={edit.id} edit={edit} />)}
                      </section>
                    )}
                    <section className="space-y-1.5">
                      <div className="flex items-center gap-2">
                        <h3 className="min-w-0 flex-1 text-2xs uppercase tracking-[0.12em] text-faint">
                          工作区 diff
                        </h3>
                        {diffFiles > 0 && (
                          <span className="shrink-0 text-2xs text-dim">{diffFiles} 个文件</span>
                        )}
                      </div>
                      {!activeRepo ? (
                        <p className="text-xs leading-relaxed text-dim">
                          还没有选择项目。打开一个项目后，这里会显示未提交的改动。
                        </p>
                      ) : activeRepo.status !== 'ready' ? (
                        <p className="text-xs leading-relaxed text-dim">
                          项目{repoStatus(activeRepo.status).label}，索引完成后可以查看工作区变更。
                        </p>
                      ) : diffLoading ? (
                        <p className="flex items-center gap-2 text-xs text-dim">
                          <Spinner /> 读取工作区变更…
                        </p>
                      ) : diffError ? (
                        <p className="text-xs leading-relaxed text-err">{diffError}</p>
                      ) : !diff || !diff.trim() ? (
                        streamEdits.length === 0 ? (
                          <p className="rounded-md border border-edge bg-panel/60 px-2.5 py-3 text-xs text-dim">
                            工作区干净
                          </p>
                        ) : (
                          <p className="rounded-md border border-edge bg-panel/60 px-2.5 py-3 text-xs text-dim">
                            还没有未提交的文件改动。
                          </p>
                        )
                      ) : (
                        <>
                          <pre className="max-h-[420px] overflow-auto rounded-md border border-edge bg-base/60 p-2 font-mono text-xs leading-relaxed">
                            {diffPreview.map((line, index) => (
                              <span
                                key={index}
                                className={clsx(
                                  'block whitespace-pre',
                                  line.startsWith('+++') || line.startsWith('---')
                                    ? 'text-dim'
                                    : line.startsWith('+')
                                      ? 'text-ok'
                                      : line.startsWith('-')
                                        ? 'text-err'
                                        : line.startsWith('@@')
                                          ? 'text-accent'
                                          : 'text-dim',
                                )}
                              >
                                {line || ' '}
                              </span>
                            ))}
                          </pre>
                          {diffLines.length > 200 && (
                            <p className="text-2xs text-faint">
                              仅显示前 200 行（共 {diffLines.length} 行），完整内容请在 Git 面板查看。
                            </p>
                          )}
                        </>
                      )}
                    </section>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </>
  )
}
