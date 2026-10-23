import clsx from 'clsx'
import {
  CheckCircle2, FilePlus2, FlaskConical, GitBranch, Radar, RefreshCw, Sparkles, Trash2, Waypoints, XCircle,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { BrainPanel } from '../components/BrainPanel'
import { BuilderPanel } from '../components/BuilderPanel'
import { CodeViewer } from '../components/CodeViewer'
import { FileTree } from '../components/FileTree'
import { GitPanel } from '../components/GitPanel'
import { ImpactPanel } from '../components/ImpactPanel'
import { ImportDialog } from '../components/ImportDialog'
import { NewProjectDialog } from '../components/NewProjectDialog'
import { Badge, Button, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { FileNode, Repo, RepoStatus, VerifyResult } from '../lib/types'
import { useRepos } from '../stores/repos'

const STATUS_META: Record<RepoStatus, { label: string; tone: 'dim' | 'ok' | 'warn' | 'err' | 'accent' }> = {
  pending: { label: '排队中', tone: 'dim' },
  indexing: { label: '索引中', tone: 'warn' },
  ready: { label: '就绪', tone: 'ok' },
  failed: { label: '失败', tone: 'err' },
  planning: { label: '规划中', tone: 'warn' },
  plan_ready: { label: '待确认方案', tone: 'accent' },
  approved: { label: '已确认方案', tone: 'accent' },
  generating: { label: '生成中', tone: 'warn' },
  review: { label: '待审阅代码', tone: 'accent' },
}

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
  const meta = STATUS_META[repo.status]

  return (
    <div
      className={clsx(
        'cursor-pointer rounded-xl border p-3 transition-colors',
        active ? 'border-accent bg-accentSoft/25' : 'border-edge bg-panel/60 hover:border-accentSoft',
      )}
      onClick={onSelect}
    >
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{repo.name}</span>
        {['indexing', 'pending', 'planning', 'generating'].includes(repo.status) && <Spinner />}
        {repo.kind === 'builder' && <Badge tone="accent">Builder</Badge>}
        <Badge tone={meta.tone}>{meta.label}</Badge>
      </div>
      <p className="mt-1 truncate font-mono text-[11px] text-dim" title={repo.source}>
        {repo.source}
      </p>
      {repo.status === 'ready' && repo.stats && (
        <p className="mt-1.5 text-[11.5px] text-dim">
          {repo.stats.files ?? 0} 文件 · {repo.stats.chunks ?? 0} 分块 · {repo.stats.symbols ?? 0} 符号
          {repo.stats.embedded ? ` · ${repo.stats.embedded} 向量` : ''}
        </p>
      )}
      {repo.status === 'failed' && repo.error && (
        <p className="mt-1.5 line-clamp-3 text-[11.5px] text-err" title={repo.error}>
          {repo.error}
        </p>
      )}
      <div className="mt-2 flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
        <button
          className="flex items-center gap-1 rounded-md border border-edge px-2 py-0.5 text-[11px] text-dim hover:text-ink"
          onClick={onReindex}
          title="重建索引"
        >
          <RefreshCw size={10} /> 重建索引
        </button>
        {confirming ? (
          <button
            className="flex items-center gap-1 rounded-md border border-err/50 px-2 py-0.5 text-[11px] text-err"
            onClick={() => {
              onRemove()
              setConfirming(false)
            }}
          >
            确认删除
          </button>
        ) : (
          <button
            className="flex items-center gap-1 rounded-md border border-edge px-2 py-0.5 text-[11px] text-dim hover:text-err"
            onClick={() => setConfirming(true)}
            title="删除仓库"
          >
            <Trash2 size={10} /> 删除
          </button>
        )}
      </div>
    </div>
  )
}

export function WorkspaceView() {
  const { repos, refresh, remove, reindex } = useRepos()
  const [importOpen, setImportOpen] = useState(false)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tree, setTree] = useState<FileNode[]>([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [treeError, setTreeError] = useState<string | null>(null)
  const [tab, setTab] = useState<'builder' | 'code' | 'brain' | 'impact' | 'git'>('code')
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null)
  const [verifyBusy, setVerifyBusy] = useState(false)
  const [verifyError, setVerifyError] = useState<string | null>(null)
  const [verifyOpen, setVerifyOpen] = useState(false)

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
      return
    }
    let cancelled = false
    api.repos
      .lastVerify(selected.id)
      .then((result) => {
        if (!cancelled && result && result.status) setVerifyResult(result as VerifyResult)
      })
      .catch(() => {
        /* no previous verification */
      })
    return () => {
      cancelled = true
    }
  }, [selected])

  const runVerify = async () => {
    if (!selected) return
    setVerifyBusy(true)
    setVerifyError(null)
    try {
      const result = await api.repos.verify(selected.id)
      setVerifyResult(result)
      setVerifyOpen(result.status !== 'passed')
      void refresh()
    } catch (err) {
      setVerifyError(err instanceof ApiError ? err.message : '验证失败')
    } finally {
      setVerifyBusy(false)
    }
  }

  return (
    <div className="flex h-full min-h-0">
      <aside className="hidden w-80 shrink-0 flex-col border-r border-edge bg-panel lg:flex">
        <div className="flex items-center justify-between px-3 py-2.5">
          <span className="text-[12px] font-medium uppercase tracking-wide text-dim">工作区</span>
          <div className="flex items-center gap-1">
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
            <p className="py-4 text-[12.5px] leading-relaxed text-dim">
              导入一个代码仓库后，Nova 就能回答「X 在哪实现」、定位报错到具体文件行号，并在沙箱里跑代码验证。
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

      {selected ? (
        <>
          <aside className="flex w-64 shrink-0 flex-col border-r border-edge bg-panel/50 lg:w-72">
            <div className="flex items-center gap-2 px-3 py-2.5">
              <select
                className="min-w-0 flex-1 rounded-md border border-edge bg-raised px-2 py-1 text-[12px] outline-none lg:hidden"
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
                className="hidden min-w-0 flex-1 truncate text-[12px] font-medium uppercase tracking-wide text-dim lg:block"
                title={selected.name}
              >
                {selected.name}
              </p>
              <button
                className="shrink-0 text-[11px] text-dim hover:text-ink lg:hidden"
                onClick={() => setImportOpen(true)}
                title="导入仓库"
              >
                <FilePlus2 size={13} />
              </button>
              <button
                className="shrink-0 text-[11px] text-dim hover:text-accent lg:hidden"
                onClick={() => setNewProjectOpen(true)}
                title="新建项目"
              >
                <Sparkles size={13} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-1">
              {treeLoading && (
                <p className="flex items-center gap-2 px-3 py-3 text-[12.5px] text-dim">
                  <Spinner /> 加载文件树…
                </p>
              )}
              {treeError && <p className="px-3 py-3 text-[12.5px] text-err">{treeError}</p>}
              {!treeLoading && !treeError && (
                <FileTree nodes={tree} selectedPath={selectedPath} onSelect={setSelectedPath} />
              )}
            </div>
          </aside>
          <main className="flex min-w-0 flex-1 flex-col bg-base">
            <div className="flex shrink-0 items-center gap-1 border-b border-edge px-2 py-1.5">
              {(
                [
                  ...(selected.kind === 'builder' ? ([['builder', '项目构建']] as const) : []),
                  ['code', '代码'],
                  ['brain', '项目地图'],
                  ['impact', '影响分析'],
                  ...(selected.status === 'ready' ? ([['git', 'Git 交付']] as const) : []),
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  onClick={() => setTab(key)}
                  className={clsx(
                    'flex items-center gap-1 rounded-md px-2.5 py-1 text-[12px] transition-colors',
                    tab === key ? 'bg-accentSoft/50 text-ink' : 'text-dim hover:bg-raised hover:text-ink',
                  )}
                >
                  {key === 'builder' && <Sparkles size={12} />}
                  {key === 'brain' && <Waypoints size={12} />}
                  {key === 'impact' && <Radar size={12} />}
                  {key === 'git' && <GitBranch size={12} />}
                  {label}
                </button>
              ))}
              {selected.status === 'ready' && (
                <div className="ml-auto flex items-center gap-2">
                  {verifyResult && (
                    <span
                      className={clsx(
                        'flex items-center gap-1 text-[11px]',
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
                  <Button size="sm" onClick={() => void runVerify()} disabled={verifyBusy}>
                    {verifyBusy ? <Spinner /> : <FlaskConical size={12} />} 验证
                  </Button>
                </div>
              )}
            </div>
            {(verifyError || verifyResult) && (
              <div
                className={clsx(
                  'shrink-0 border-b px-3 py-1.5 text-[11.5px]',
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
                      <div key={step.name} className="flex items-center gap-2 text-[11px]">
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
                      <p className="text-[11px] text-dim">{verifyResult.notes.join('；')}</p>
                    ) : null}
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[10.5px] text-dim">
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
            <p className="text-[14px] text-ink">选择一个仓库，或从 0 新建一个项目</p>
            <p className="max-w-md text-[12.5px] leading-relaxed text-dim">
              导入已有仓库可以浏览代码、分析影响、让 Nova 修 bug；「新建项目」则会先给出方案，确认后生成完整代码提案，批准后写入并建立索引。
            </p>
            {repos.length > 0 && (
              <select
                className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-[13px] outline-none lg:hidden"
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