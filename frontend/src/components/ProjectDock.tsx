import clsx from 'clsx'
import {
  Check, FilePlus2, FlaskConical, FolderTree, GitPullRequest, Sparkles, Trash2, X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { FileNode, Repo } from '../lib/types'
import { useRepos } from '../stores/repos'
import { FileTree } from './FileTree'
import { ImportDialog } from './ImportDialog'
import { NewProjectDialog } from './NewProjectDialog'
import { Badge, Button, Spinner } from './common'

const STATUS_LABEL: Record<string, string> = {
  pending: '排队中',
  indexing: '索引中',
  ready: '就绪',
  failed: '失败',
  planning: '规划中',
  plan_ready: '待确认方案',
  approved: '已确认方案',
  generating: '生成中',
  review: '待审阅',
}

function statusTone(status: string): 'ok' | 'warn' | 'err' | 'accent' | 'dim' {
  if (status === 'ready') return 'ok'
  if (status === 'failed') return 'err'
  if (['pending', 'indexing', 'planning', 'generating'].includes(status)) return 'warn'
  if (['plan_ready', 'approved', 'review'].includes(status)) return 'accent'
  return 'dim'
}

function RepoRow({
  repo,
  active,
  selected,
  onSelect,
}: {
  repo: Repo
  active: boolean
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      onClick={onSelect}
      className={clsx(
        'mb-0.5 flex w-full items-center gap-2 rounded-lg border px-2 py-1.5 text-left transition-colors',
        active
          ? 'border-accent/60 bg-accentSoft/30'
          : 'border-transparent hover:border-edge/80 hover:bg-raised/70',
      )}
      title={selected ? '已在对话上下文中，点击切换当前仓库' : '点击加入对话上下文'}
    >
      <span
        className={clsx(
          'flex h-4 w-4 shrink-0 items-center justify-center rounded border',
          selected ? 'border-accent bg-accent text-white' : 'border-edge text-transparent',
        )}
      >
        <Check size={10} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[12px] text-ink">{repo.name}</span>
        <span className="block truncate font-mono text-[9.5px] text-dim/70">{repo.source}</span>
      </span>
      {['pending', 'indexing', 'planning', 'generating'].includes(repo.status)
        ? <Spinner />
        : <Badge tone={statusTone(repo.status)}>{STATUS_LABEL[repo.status] ?? repo.status}</Badge>}
    </button>
  )
}

export function ProjectDock({
  selectedRepos,
  onToggleRepo,
  onOpenWorkspace,
  onOpenWorkflow,
}: {
  selectedRepos: string[]
  onToggleRepo: (id: string) => void
  onOpenWorkspace: (repoId?: string, path?: string) => void
  onOpenWorkflow: (tab: 'changes' | 'tasks', repoId?: string) => void
}) {
  const { repos, refresh, remove } = useRepos()
  const [importOpen, setImportOpen] = useState(false)
  const [newProjectOpen, setNewProjectOpen] = useState(false)
  const [activeId, setActiveId] = useState<string | null>(selectedRepos[0] ?? null)
  const [tree, setTree] = useState<FileNode[]>([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [treeError, setTreeError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    setConfirmDelete(false)
  }, [activeId])

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (activeId && selectedRepos.includes(activeId)) return
    setActiveId(selectedRepos[0] ?? null)
  }, [selectedRepos, activeId])

  useEffect(() => {
    const busy = repos.some((repo) => ['pending', 'indexing', 'planning', 'generating'].includes(repo.status))
    if (!busy) return
    const timer = setInterval(() => void refresh(), 3000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repos])

  const active = repos.find((repo) => repo.id === activeId) ?? null

  useEffect(() => {
    if (!active || active.status !== 'ready') {
      setTree([])
      return
    }
    let cancelled = false
    setTreeLoading(true)
    setTreeError(null)
    api.repos
      .tree(active.id)
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
  }, [active?.id, active?.status])

  const selectRepo = (repo: Repo) => {
    setActiveId(repo.id)
    if (!selectedRepos.includes(repo.id)) onToggleRepo(repo.id)
  }

  const deleteActive = async () => {
    if (!active) return
    setDeleting(true)
    try {
      await remove(active.id)
      setActiveId(null)
      setConfirmDelete(false)
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b border-edge/70 px-3 py-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-dim">项目</span>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setNewProjectOpen(true)}
            className="flex h-7 items-center gap-1 rounded-md px-1.5 text-[10.5px] text-dim transition-colors hover:bg-raised hover:text-ink"
            title="从 0 新建项目"
          >
            <Sparkles size={11} /> 新建
          </button>
          <button
            onClick={() => setImportOpen(true)}
            className="flex h-7 items-center gap-1 rounded-md px-1.5 text-[10.5px] text-dim transition-colors hover:bg-raised hover:text-ink"
            title="导入 ZIP / Git 仓库"
          >
            <FilePlus2 size={11} /> 导入
          </button>
        </div>
      </div>

      <div className="max-h-[38%] shrink-0 overflow-y-auto px-2 py-2">
        {repos.length === 0 ? (
          <p className="px-1 py-2 text-[11.5px] leading-relaxed text-dim">
            还没有仓库。导入 ZIP / Git 仓库，或从 0 新建一个项目。
          </p>
        ) : (
          repos.map((repo) => (
            <RepoRow
              key={repo.id}
              repo={repo}
              active={repo.id === activeId}
              selected={selectedRepos.includes(repo.id)}
              onSelect={() => selectRepo(repo)}
            />
          ))
        )}
        {selectedRepos.length > 1 && (
          <p className="px-1 pt-1.5 text-[10px] leading-relaxed text-dim/60">
            对话会同时使用已选的 {selectedRepos.length} 个仓库；文件树显示当前仓库。
          </p>
        )}
      </div>

      <div className="flex min-h-0 flex-1 flex-col border-t border-edge/70">
        {active ? (
          <>
            <div className="flex items-center gap-2 px-3 py-2">
              <span className="min-w-0 flex-1 truncate text-[12px] font-medium" title={active.name}>
                {active.name}
              </span>
              {active.status === 'ready' && active.stats && (
                <span className="shrink-0 text-[9.5px] text-dim/70">
                  {active.stats.files ?? 0} 文件
                </span>
              )}
              <button
                onClick={() => onOpenWorkspace(active.id)}
                className="flex shrink-0 items-center gap-1 rounded-md border border-edge/80 px-1.5 py-0.5 text-[10px] text-dim transition-colors hover:text-ink"
                title="打开完整工作区"
              >
                <FolderTree size={10} /> 展开
              </button>
              {!confirmDelete ? (
                <button
                  onClick={() => setConfirmDelete(true)}
                  className="flex shrink-0 items-center rounded-md p-1 text-dim/70 transition-colors hover:bg-err/10 hover:text-err"
                  title="删除仓库（文件、索引与向量一并清理）"
                >
                  <Trash2 size={10} />
                </button>
              ) : (
                <span className="flex shrink-0 items-center gap-1">
                  <button
                    onClick={() => void deleteActive()}
                    disabled={deleting}
                    className="flex items-center gap-1 rounded-md border border-err/50 px-1.5 py-0.5 text-[10px] text-err transition-colors hover:bg-err/10 disabled:opacity-50"
                    title="确认删除：会清理文件、索引、向量与预览"
                  >
                    {deleting ? <Spinner /> : null} 确认删除
                  </button>
                  <button
                    onClick={() => setConfirmDelete(false)}
                    className="text-dim/70 transition-colors hover:text-ink"
                    title="取消"
                  >
                    <X size={10} />
                  </button>
                </span>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-1">
              {active.status !== 'ready' ? (
                <p className="px-3 py-3 text-[11.5px] leading-relaxed text-dim">
                  {STATUS_LABEL[active.status] ?? active.status}。索引完成后可浏览文件树。
                </p>
              ) : treeLoading ? (
                <p className="flex items-center gap-2 px-3 py-3 text-[11.5px] text-dim">
                  <Spinner /> 加载文件树…
                </p>
              ) : treeError ? (
                <p className="px-3 py-3 text-[11.5px] text-err">{treeError}</p>
              ) : (
                <FileTree
                  nodes={tree}
                  selectedPath={null}
                  onSelect={(path) => onOpenWorkspace(active.id, path)}
                />
              )}
            </div>
          </>
        ) : (
          <div className="px-3 py-4 text-[11.5px] leading-relaxed text-dim">
            选择上方仓库加入对话上下文，即可浏览文件并打开完整工作区。
          </div>
        )}
      </div>

      <div className="shrink-0 space-y-1.5 border-t border-edge/70 p-2">
        <div className="grid grid-cols-2 gap-1.5">
          <Button size="sm" onClick={() => onOpenWorkflow('changes', active?.id)}>
            <GitPullRequest size={11} /> 变更
          </Button>
          <Button size="sm" onClick={() => onOpenWorkflow('tasks', active?.id)}>
            <FlaskConical size={11} /> 修复任务
          </Button>
        </div>
        <button
          onClick={() => onOpenWorkspace(active?.id)}
          className="flex w-full items-center justify-center gap-1 rounded-md px-2 py-1 text-[10.5px] text-dim/70 transition-colors hover:text-ink"
        >
          <FolderTree size={11} /> 打开完整工作区
        </button>
      </div>

      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={(repoId) => {
          void refresh()
          if (repoId) {
            setActiveId(repoId)
            if (!selectedRepos.includes(repoId)) onToggleRepo(repoId)
          }
        }}
      />
      <NewProjectDialog
        open={newProjectOpen}
        onClose={() => setNewProjectOpen(false)}
        onCreated={(repoId) => {
          void refresh()
          setActiveId(repoId)
          if (!selectedRepos.includes(repoId)) onToggleRepo(repoId)
        }}
      />
    </div>
  )
}
