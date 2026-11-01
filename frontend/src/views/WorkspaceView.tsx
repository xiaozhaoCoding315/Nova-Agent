import clsx from 'clsx'
import {
  Activity, ArrowLeft, CheckCircle2, ChevronDown, FilePlus2, FlaskConical, FolderOpen, GitBranch, GitCompare,
  MoreHorizontal, Radar, RefreshCw, Rocket, Sparkles, Trash2, Waypoints, XCircle,
} from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { BrainPanel } from '../components/BrainPanel'
import { BuilderPanel } from '../components/BuilderPanel'
import { CodeViewer } from '../components/CodeViewer'
import { ContractPanel } from '../components/ContractPanel'
import { DebtPanel } from '../components/DebtPanel'
import { DeployPanel } from '../components/DeployPanel'
import { FileTree } from '../components/FileTree'
import { GitPanel } from '../components/GitPanel'
import { ImpactPanel } from '../components/ImpactPanel'
import { ImportDialog } from '../components/ImportDialog'
import { LocalFolderDialog } from '../components/LocalFolderDialog'
import { NewProjectDialog } from '../components/NewProjectDialog'
import { Badge, Button, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { FileNode, Job, Repo, VerifyResult } from '../lib/types'
import { REPO_STATUS, selectClass } from '../lib/ui'
import { useMode } from '../stores/mode'
import { useRepos } from '../stores/repos'

export type WorkspaceTab = 'builder' | 'code' | 'brain' | 'impact' | 'contract' | 'deploy' | 'git' | 'debt'

type Tab = WorkspaceTab

/** 收进「更多」菜单的低频页签（分析类能力仍在对话里作为工具自动使用）。 */
const MORE_LABEL = { brain: '项目地图', impact: '影响分析', debt: '技术债', contract: '契约对齐', deploy: '预览部署' }

function RepoCard({
  repo,
  active,
  onSelect,
  onReindex,
  onRemove,
}: {
  repo: Repo
  active: boolean
  onSelect: () => void
  onReindex: () => void
  onRemove: () => void
}) {
  const [confirming, setConfirming] = useState(false)
  const meta = REPO_STATUS[repo.status]

  return (
    <div
      className={clsx(
        'cursor-pointer rounded-xl border p-3 transition-colors',
        active ? 'border-accent bg-accentSoft/25' : 'border-edge bg-panel/60 hover:border-accentSoft',
      )}
      onClick={onSelect}
    >
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-base font-medium text-ink">{repo.name}</span>
        {['indexing', 'pending', 'planning', 'generating'].includes(repo.status) && <Spinner />}
        {repo.kind === 'builder' && <Badge tone="accent">Builder</Badge>}
        {repo.origin === 'local' && <Badge tone="accent">本地</Badge>}
        <Badge tone={meta.tone}>{meta.label}</Badge>
      </div>
      <p className="mt-1 truncate font-mono text-xs text-dim" title={repo.source}>
        {repo.source}
      </p>
      {repo.status === 'ready' && repo.stats && (
        <p className="mt-1.5 text-sm text-dim">
          {repo.stats.files ?? 0} 文件 · {repo.stats.chunks ?? 0} 分块 · {repo.stats.symbols ?? 0} 符号
          {repo.stats.embedded ? ` · ${repo.stats.embedded} 向量` : ''}
        </p>
      )}
      {repo.status === 'failed' && repo.error && (
        <p className="mt-1.5 line-clamp-3 text-sm text-err" title={repo.error}>
          {repo.error}
        </p>
      )}
      <div className="mt-2 flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
        <button
          className="flex items-center gap-1 rounded-md border border-edge px-2 py-0.5 text-xs text-dim hover:text-ink"
          onClick={onReindex}
          title="重新阅读项目代码，更新检索索引"
        >
          <RefreshCw size={10} /> 重新分析
        </button>
        {confirming ? (
          <button
            className="flex items-center gap-1 rounded-md border border-err/50 px-2 py-0.5 text-xs text-err"
            onClick={() => {
              onRemove()
              setConfirming(false)
            }}
          >
            确认删除
          </button>
        ) : (
          <button
            className="flex items-center gap-1 rounded-md border border-edge px-2 py-0.5 text-xs text-dim hover:text-err"
            onClick={() => setConfirming(true)}
            title={repo.origin === 'local' ? '取消登记（不会删除磁盘文件）' : '删除仓库'}
          >
            <Trash2 size={10} /> 删除
          </button>
        )}
      </div>
    </div>
  )
}

export function WorkspaceView({
  initialRepoId = null,
  initialPath = null,
  initialTab = 'code',
  embedded = false,
  onClose,
}: {
  initialRepoId?: string | null
  initialPath?: string | null
  initialTab?: WorkspaceTab
  /** 抽屉内嵌：隐藏左侧项目列表，只保留文件树与主区，顶部返回按钮关闭抽屉。 */
  embedded?: boolean
  onClose?: () => void
} = {}) {
  const { repos, refresh, remove, reindex, clearError } = useRepos()
  const localMode = useMode((s) => s.mode?.local ?? false)
  const [localOpen, setLocalOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(initialRepoId)
  const [tree, setTree] = useState<FileNode[]>([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [selectedPath, setSelectedPath] = useState<string | null>(initialPath)
  const [treeError, setTreeError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>(initialTab)
  const [moreOpen, setMoreOpen] = useState(false)
  const [projectMenuOpen, setProjectMenuOpen] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [projectBusy, setProjectBusy] = useState<'reindex' | 'remove' | null>(null)
  const [projectMessage, setProjectMessage] = useState<{ tone: 'ok' | 'err'; text: string } | null>(null)
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null)
  const [verifyBusy, setVerifyBusy] = useState(false)
  const [verifyError, setVerifyError] = useState<string | null>(null)
  const [verifyOpen, setVerifyOpen] = useState(false)
  const [verifyJobId, setVerifyJobId] = useState<string | null>(null)
  const [verifyJob, setVerifyJob] = useState<Job | null>(null)

  // 本地模式不提供预览部署；模式异步加载完成后清掉可能残留的页签。
  useEffect(() => {
    if (localMode && tab === 'deploy') setTab('code')
  }, [localMode, tab])

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const busy = repos.some((r) =>
      ['pending', 'indexing', 'planning', 'generating'].includes(r.status),
    )
    if (!busy) return
    const timer = setInterval(() => void refresh(), 3000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repos])

  const selected = repos.find((r) => r.id === selectedId) ?? null

  // 抽屉可以直接以 Git 页签打开；项目尚未就绪时没有该页签，退回代码视图。
  useEffect(() => {
    if (tab === 'git' && selected && selected.status !== 'ready') setTab('code')
  }, [selected, tab])

  useEffect(() => {
    if (!selected || selected.status !== 'ready') {
      setTree([])
      return
    }
    let cancelled = false
    setTreeLoading(true)
    setTreeError(null)
    api.repos
      .tree(selected.id)
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
  }, [selected])

  useEffect(() => {
    if (!selected || selected.status !== 'ready') {
      setVerifyResult(null)
      setVerifyJob(null)
      setVerifyJobId(null)
      setVerifyBusy(false)
      return
    }
    let cancelled = false
    api.repos
      .lastVerify(selected.id)
      .then((result) => {
        if (!cancelled) setVerifyResult(result && result.status ? result : null)
      })
      .catch(() => {
        /* no previous verification */
      })
    return () => {
      cancelled = true
    }
  }, [selected])

  useEffect(() => {
    if (!verifyJobId || !selected) return
    let cancelled = false
    const tick = async () => {
      try {
        const job = await api.jobs.get(verifyJobId)
        if (cancelled) return
        setVerifyJob(job)
        if (!['succeeded', 'failed', 'canceled'].includes(job.status)) return
        setVerifyBusy(false)
        setVerifyJobId(null)
        if (job.status === 'failed') setVerifyError(job.error || '验证未通过')
        if (job.status === 'canceled') setVerifyError('验证已取消')
        const result = await api.repos.lastVerify(selected.id)
        if (!cancelled && result && result.status) {
          setVerifyResult(result)
          setVerifyOpen(job.status !== 'succeeded' || result.status !== 'passed')
        }
        void refresh()
      } catch (err) {
        if (cancelled) return
        setVerifyError(err instanceof ApiError ? err.message : '验证状态获取失败')
        setVerifyBusy(false)
        setVerifyJobId(null)
      }
    }
    void tick()
    const timer = setInterval(tick, 1500)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [verifyJobId, selected?.id])

  const runVerify = async () => {
    if (!selected || verifyBusy) return
    setVerifyBusy(true)
    setVerifyError(null)
    setVerifyJob(null)
    try {
      const queued = await api.repos.verify(selected.id)
      setVerifyJobId(queued.job_id)
    } catch (err) {
      setVerifyError(err instanceof ApiError ? err.message : '验证失败')
      setVerifyBusy(false)
    }
  }

  const cancelVerify = async () => {
    if (!verifyJobId) return
    try {
      await api.jobs.cancel(verifyJobId)
    } catch (err) {
      setVerifyError(err instanceof ApiError ? err.message : '取消失败')
    }
  }

  const moreItems: { key: Tab; label: string; icon: ReactNode }[] = [
    { key: 'brain', label: '项目地图', icon: <Waypoints size={12} /> },
    { key: 'impact', label: '影响分析', icon: <Radar size={12} /> },
    { key: 'debt', label: '技术债', icon: <Activity size={12} /> },
    { key: 'contract', label: '契约对齐', icon: <GitCompare size={12} /> },
  ]
  if (!localMode) {
    moreItems.push({ key: 'deploy', label: '预览部署', icon: <Rocket size={12} /> })
  }

  const closeProjectMenu = () => {
    setProjectMenuOpen(false)
    setConfirmRemove(false)
  }

  // 内嵌抽屉隐藏了左侧项目列表，重建索引改从这里发起；store 已处理并记录错误。
  const reindexProject = async () => {
    if (!selected || projectBusy) return
    setProjectBusy('reindex')
    setProjectMessage(null)
    clearError()
    await reindex(selected.id)
    const failure = useRepos.getState().error
    setProjectBusy(null)
    if (failure) {
      // 失败提示在菜单下方显示；先收起菜单，避免错误横幅被挡住。
      closeProjectMenu()
      setProjectMessage({ tone: 'err', text: failure })
      return
    }
    setProjectMessage({ tone: 'ok', text: '已开始重建索引' })
    closeProjectMenu()
  }

  // 移除成功后关闭抽屉；失败时保持抽屉打开并展示原因。
  const removeProject = async () => {
    if (!selected || projectBusy) return
    const repoId = selected.id
    setProjectBusy('remove')
    setProjectMessage(null)
    clearError()
    await remove(repoId)
    const stillExists = useRepos.getState().repos.some((repo) => repo.id === repoId)
    setProjectBusy(null)
    if (stillExists) {
      closeProjectMenu()
      setProjectMessage({ tone: 'err', text: useRepos.getState().error ?? '移除项目失败' })
      return
    }
    closeProjectMenu()
    setSelectedId(null)
    setSelectedPath(null)
    onClose?.()
  }

  return (
    <div className="flex h-full min-h-0">
      {!embedded && (
      <aside className="hidden w-80 shrink-0 flex-col border-r border-edge bg-panel lg:flex">
        <div className="flex items-center justify-between px-3 py-2.5">
          <div className="flex items-center gap-1.5">
            {onClose && (
              <button
                onClick={onClose}
                className="flex h-7 w-7 items-center justify-center rounded-md text-dim transition-colors hover:bg-raised hover:text-ink"
                title="返回对话"
                aria-label="返回对话"
              >
                <ArrowLeft size={14} />
              </button>
            )}
            <span className="text-sm font-medium uppercase tracking-wide text-dim">工作区</span>
          </div>
          <div className="flex items-center gap-1">
            {localMode && (
              <Button size="sm" variant="ghost" onClick={() => setLocalOpen(true)}>
                <FolderOpen size={12} /> 本地文件夹
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setNewProjectOpen(true)}>
              <Sparkles size={12} /> 新建项目
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setImportOpen(true)}>
              <FilePlus2 size={12} /> 导入
            </Button>
          </div>
        </div>
        <div className="flex-1 space-y-2 overflow-y-auto px-3 pb-3">
          {repos.length === 0 && (
            <p className="py-4 text-base leading-relaxed text-dim">
              导入你的项目后，Nova 就能回答「X 在哪实现」、定位报错到具体文件行号，并在沙箱里跑代码验证。
            </p>
          )}
          {repos.map((repo) => (
            <RepoCard
              key={repo.id}
              repo={repo}
              active={repo.id === selectedId}
              onSelect={() => {
                setSelectedId(repo.id)
                setSelectedPath(null)
                setTab(repo.kind === 'builder' && repo.status !== 'ready' ? 'builder' : 'code')
              }}
              onReindex={() => void reindex(repo.id)}
              onRemove={() => {
                if (repo.id === selectedId) {
                  setSelectedId(null)
                  setSelectedPath(null)
                }
                void remove(repo.id)
              }}
            />
          ))}
        </div>
      </aside>
      )}

      {selected ? (
        <>
          <aside
            className={clsx(
              'flex shrink-0 flex-col border-r border-edge bg-panel/50',
              // 375px 下项目操作菜单会挤占下拉框；内嵌时给小屏更宽的文件树列。
              embedded ? 'w-48 sm:w-56 lg:w-72' : 'w-64 lg:w-72',
            )}
          >
            <div className="flex items-center gap-2 px-3 py-2.5">
              <select
                className={clsx(
                  selectClass,
                  'min-w-0 flex-1',
                  !embedded && 'lg:hidden',
                )}
                value={selected.id}
                onChange={(e) => {
                  setSelectedId(e.target.value)
                  setSelectedPath(null)
                  const repo = repos.find((r) => r.id === e.target.value)
                  setTab(repo?.kind === 'builder' && repo.status !== 'ready' ? 'builder' : 'code')
                }}
                aria-label="切换仓库"
              >
                {repos.map((repo) => (
                  <option key={repo.id} value={repo.id}>
                    {repo.name}
                  </option>
                ))}
              </select>
              <p
                className={clsx(
                  'min-w-0 flex-1 truncate text-sm font-medium uppercase tracking-wide text-dim',
                  embedded ? 'hidden' : 'hidden lg:block',
                )}
                title={selected.name}
              >
                {selected.name}
              </p>
              {embedded && (
                <div className="relative shrink-0">
                  <button
                    onClick={() => {
                      setProjectMenuOpen((value) => !value)
                      setConfirmRemove(false)
                    }}
                    className="flex h-7 w-7 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
                    title={`项目操作 · ${selected.name}`}
                    aria-label="项目操作"
                    aria-haspopup="menu"
                    aria-expanded={projectMenuOpen}
                  >
                    <MoreHorizontal size={14} />
                  </button>
                  {projectMenuOpen && (
                    <>
                      <div className="fixed inset-0 z-10" onClick={closeProjectMenu} aria-hidden="true" />
                      <div
                        role="menu"
                        aria-label="项目操作"
                        className="absolute left-0 top-full z-20 mt-1 w-48 rounded-lg border border-edge bg-panel p-1 shadow-pop"
                      >
                        <p
                          className="truncate px-2 py-1 font-mono text-2xs uppercase tracking-[0.12em] text-faint"
                          title={selected.name}
                        >
                          {selected.name}
                        </p>
                        {confirmRemove ? (
                          <div className="rounded-md border border-err/40 bg-err/5 p-2">
                            <p className="text-xs leading-relaxed text-err">
                              确认移除项目？索引会被删除，此操作不可撤销。
                            </p>
                            <div className="mt-1.5 flex items-center gap-1.5">
                              <button
                                role="menuitem"
                                onClick={() => void removeProject()}
                                disabled={projectBusy != null}
                                className="flex h-6 flex-1 items-center justify-center gap-1 rounded-sm border border-err/50 px-1.5 text-2xs text-err transition-colors duration-150 hover:bg-err/10 disabled:opacity-50"
                              >
                                {projectBusy === 'remove' && <Spinner className="h-3 w-3" />}
                                确认移除
                              </button>
                              <button
                                onClick={() => setConfirmRemove(false)}
                                disabled={projectBusy != null}
                                className="flex h-6 flex-1 items-center justify-center rounded-sm border border-edge px-1.5 text-2xs text-dim transition-colors duration-150 hover:text-ink disabled:opacity-50"
                              >
                                取消
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <button
                              role="menuitem"
                              onClick={() => void reindexProject()}
                              disabled={projectBusy != null}
                              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-xs text-dim transition-colors duration-150 hover:bg-raised hover:text-ink disabled:opacity-50"
                            >
                              {projectBusy === 'reindex' ? <Spinner className="h-3 w-3" /> : <RefreshCw size={12} />}
                              重建索引
                            </button>
                            <button
                              role="menuitem"
                              onClick={() => setConfirmRemove(true)}
                              disabled={projectBusy != null}
                              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-xs text-dim transition-colors duration-150 hover:bg-raised hover:text-err disabled:opacity-50"
                            >
                              <Trash2 size={12} /> 移除项目
                            </button>
                          </>
                        )}
                      </div>
                    </>
                  )}
                </div>
              )}
              <button
                className="shrink-0 text-xs text-dim hover:text-ink lg:hidden"
                onClick={() => setImportOpen(true)}
                title="导入仓库"
              >
                <FilePlus2 size={13} />
              </button>
              <button
                className="shrink-0 text-xs text-dim hover:text-accent lg:hidden"
                onClick={() => setNewProjectOpen(true)}
                title="新建项目"
              >
                <Sparkles size={13} />
              </button>
            </div>
            {embedded && projectMessage && (
              <div
                className={clsx(
                  'shrink-0 border-b border-edge/70 px-3 py-1.5 text-xs leading-relaxed',
                  projectMessage.tone === 'ok' ? 'text-ok' : 'text-err',
                )}
                role="status"
              >
                {projectMessage.text}
              </div>
            )}
            <div className="flex-1 overflow-y-auto px-1">
              {treeLoading && (
                <p className="flex items-center gap-2 px-3 py-3 text-base text-dim">
                  <Spinner /> 加载文件树…
                </p>
              )}
              {treeError && <p className="px-3 py-3 text-base text-err">{treeError}</p>}
              {!treeLoading && !treeError && (
                <FileTree nodes={tree} selectedPath={selectedPath} onSelect={setSelectedPath} />
              )}
            </div>
          </aside>
          <main className="flex min-w-0 flex-1 flex-col bg-base">
            <div className="flex shrink-0 items-center gap-2 border-b border-edge px-2 py-1.5">
              {embedded && onClose && (
                <button
                  onClick={onClose}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-dim transition-colors hover:bg-raised hover:text-ink"
                  title="关闭工作区 · Esc"
                  aria-label="关闭工作区"
                >
                  <ArrowLeft size={14} />
                </button>
              )}
              <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
                {(
                  [
                    ...(selected.kind === 'builder' ? ([['builder', '项目构建']] as const) : []),
                    ['code', '代码'],
                    ...(selected.status === 'ready' ? ([['git', 'Git 交付']] as const) : []),
                  ] as const
                ).map(([key, label]) => (
                  <button
                    key={key}
                    onClick={() => setTab(key)}
                    className={clsx(
                      'flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-2.5 py-1 text-sm transition-colors',
                      tab === key ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
                    )}
                  >
                    {key === 'builder' && <Sparkles size={12} />}
                    {key === 'git' && <GitBranch size={12} />}
                    {label}
                  </button>
                ))}
                {selected.status === 'ready' && (
                  <div className="relative shrink-0">
                    <button
                      onClick={() => setMoreOpen((value) => !value)}
                      className={clsx(
                        'flex shrink-0 items-center gap-1 whitespace-nowrap rounded-md px-2.5 py-1 text-sm transition-colors',
                        moreItems.some((item) => item.key === tab)
                          ? 'bg-accentSoft/50 text-ink'
                          : 'text-dim hover:bg-raised hover:text-ink',
                      )}
                    >
                      <ChevronDown size={12} />
                      {MORE_LABEL[tab as keyof typeof MORE_LABEL] ?? '更多'}
                    </button>
                    {moreOpen && (
                      <>
                        <div className="fixed inset-0 z-10" onClick={() => setMoreOpen(false)} />
                        <div className="absolute left-0 top-full z-20 mt-1 w-40 overflow-hidden rounded-lg border border-edge bg-panel py-1 shadow-lg">
                          {moreItems.map(({ key, label, icon }) => (
                            <button
                              key={key}
                              onClick={() => {
                                setTab(key)
                                setMoreOpen(false)
                              }}
                              className={clsx(
                                'flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors',
                                tab === key ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
                              )}
                            >
                              {icon}
                              {label}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
              {selected.status === 'ready' && (
                <div className="flex shrink-0 items-center gap-2">
                  {verifyBusy && verifyJob && (
                    <span className="flex items-center gap-1 text-xs text-dim">
                      <Spinner />
                      验证中 {Math.round((verifyJob.progress || 0) * 100)}%
                      {verifyJob.step ? ` · ${verifyJob.step}` : ''}
                    </span>
                  )}
                  {verifyResult && !verifyBusy && (
                    <span
                      className={clsx(
                        'flex items-center gap-1 text-xs',
                        verifyResult.status === 'passed' && 'text-ok',
                        verifyResult.status === 'failed' && 'text-err',
                        verifyResult.status === 'unsupported' && 'text-dim',
                      )}
                    >
                      {verifyResult.status === 'passed' ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
                      验证{verifyResult.status === 'passed' ? '通过' : verifyResult.status === 'unsupported' ? '不支持' : '失败'}
                      <span className="text-dim">exit {verifyResult.exit_code}</span>
                    </span>
                  )}
                  {verifyBusy && (
                    <Button size="sm" variant="danger" onClick={() => void cancelVerify()}>
                      取消
                    </Button>
                  )}
                  <Button size="sm" onClick={() => void runVerify()} disabled={verifyBusy}>
                    {verifyBusy ? <Spinner /> : <FlaskConical size={12} />} 验证
                  </Button>
                </div>
              )}
            </div>
            {(verifyError || verifyResult) && (
              <div
                className={clsx(
                  'shrink-0 border-b px-3 py-1.5 text-sm',
                  verifyResult?.status === 'passed' ? 'border-ok/30 bg-ok/5' : 'border-err/30 bg-err/5',
                )}
              >
                {verifyError ? (
                  <span className="text-err">{verifyError}</span>
                ) : (
                  <button className="w-full text-left" onClick={() => setVerifyOpen(!verifyOpen)}>
                    <span
                      className={clsx(
                        verifyResult?.status === 'passed' && 'text-ok',
                        verifyResult?.status === 'failed' && 'text-err',
                        verifyResult?.status === 'unsupported' && 'text-dim',
                      )}
                    >
                      验证 {verifyResult?.status === 'passed' ? '通过' : verifyResult?.status === 'unsupported' ? '不支持' : '失败'}
                    </span>
                    <span className="ml-2 text-dim">
                      {verifyResult?.stack ? `${verifyResult.stack} · ` : ''}
                      exit {verifyResult?.exit_code} · {verifyResult?.image || '—'} ·{' '}
                      {verifyResult?.at ? new Date(verifyResult.at).toLocaleString() : ''}（点击{verifyOpen ? '收起' : '查看细节'}）
                    </span>
                  </button>
                )}
                {verifyOpen && verifyResult && (
                  <div className="mt-1.5 space-y-1">
                    {verifyResult.steps?.map((step) => (
                      <div key={step.name} className="flex items-center gap-2 text-xs">
                        <span
                          className={clsx(
                            'h-1.5 w-1.5 rounded-full',
                            step.status === 'passed' && 'bg-ok',
                            step.status === 'failed' && 'bg-err',
                            step.status === 'skipped' && 'bg-dim',
                          )}
                        />
                        <span className="w-28 shrink-0 text-dim">{step.name}</span>
                        <code className="min-w-0 flex-1 truncate text-dim">{step.command}</code>
                        <span className={step.status === 'failed' ? 'text-err' : 'text-dim'}>
                          exit {step.exit_code}
                        </span>
                      </div>
                    ))}
                    {verifyResult.notes?.length ? (
                      <p className="text-xs text-dim">{verifyResult.notes.join('；')}</p>
                    ) : null}
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-xs text-dim">
                      {(verifyResult.stdout || verifyResult.stderr || '（无输出）').slice(-3000)}
                    </pre>
                  </div>
                )}
              </div>
            )}
            <div className="min-h-0 flex-1">
              {tab === 'builder' && (
                <BuilderPanel repoId={selected.id} status={selected.status} onChanged={() => void refresh()} />
              )}
              {tab === 'code' && <CodeViewer repoId={selected.id} path={selectedPath} />}
              {tab === 'brain' && (
                <BrainPanel
                  repoId={selected.id}
                  onOpenFile={(path) => {
                    setSelectedPath(path)
                    setTab('code')
                  }}
                />
              )}
              {tab === 'impact' && (
                <ImpactPanel
                  repoId={selected.id}
                  onOpenFile={(path) => {
                    setSelectedPath(path)
                    setTab('code')
                  }}
                />
              )}
              {tab === 'debt' && <DebtPanel repoId={selected.id} />}
              {tab === 'contract' && (
                <ContractPanel
                  repoId={selected.id}
                  refreshToken={verifyResult?.at ?? ''}
                  onRunVerify={() => void runVerify()}
                />
              )}
              {!localMode && tab === 'deploy' && <DeployPanel repoId={selected.id} />}
              {tab === 'git' && (
                <GitPanel
                  repoId={selected.id}
                  repoName={selected.name}
                  onChanged={() => void refresh()}
                />
              )}
            </div>
          </main>
        </>
      ) : (
        <main className="min-w-0 flex-1">
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
            <p className="text-md text-ink">选择一个仓库，或从 0 新建一个项目</p>
            <p className="max-w-md text-base leading-relaxed text-dim">
              导入已有项目可以浏览代码、分析影响、让 Nova 修 bug；「新建项目」则会先给出方案，确认后生成完整代码提案，批准后写入并建立索引。
            </p>
            {repos.length > 0 && (
              <select
                className={clsx(
                  'rounded-lg border border-edge bg-raised px-3 py-1.5 text-base text-ink outline-none',
                  !embedded && 'lg:hidden',
                )}
                defaultValue=""
                onChange={(e) => {
                  if (e.target.value) {
                    setSelectedId(e.target.value)
                    setSelectedPath(null)
                    const repo = repos.find((r) => r.id === e.target.value)
                    setTab(repo?.kind === 'builder' && repo.status !== 'ready' ? 'builder' : 'code')
                  }
                }}
                aria-label="选择仓库"
              >
                <option value="" disabled>
                  选择仓库…
                </option>
                {repos.map((repo) => (
                  <option key={repo.id} value={repo.id}>
                    {repo.name}（{repo.status}）
                  </option>
                ))}
              </select>
            )}
            <div className="mt-1 flex items-center gap-2">
              <Button variant="primary" onClick={() => setNewProjectOpen(true)}>
                <Sparkles size={13} /> 新建项目
              </Button>
              <Button onClick={() => setImportOpen(true)}>
                <FilePlus2 size={13} /> 导入仓库
              </Button>
            </div>
          </div>
        </main>
      )}

      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={(repoId) => {
          void refresh()
          if (repoId) setSelectedId(repoId)
        }}
      />

      <LocalFolderDialog
        open={localOpen}
        onClose={() => setLocalOpen(false)}
        onOpened={(repo) => {
          void refresh()
          setSelectedId(repo.id)
          setSelectedPath(null)
          setTab('code')
          setLocalOpen(false)
        }}
      />

      <NewProjectDialog
        open={newProjectOpen}
        onClose={() => setNewProjectOpen(false)}
        onCreated={(repoId) => {
          void refresh()
          setSelectedId(repoId)
          setTab('builder')
        }}
      />
    </div>
  )
}