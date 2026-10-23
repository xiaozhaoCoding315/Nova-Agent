import clsx from 'clsx'
import { FilePlus2, RefreshCw, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { CodeViewer } from '../components/CodeViewer'
import { FileTree } from '../components/FileTree'
import { ImportDialog } from '../components/ImportDialog'
import { Badge, Button, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { FileNode, Repo, RepoStatus } from '../lib/types'
import { useRepos } from '../stores/repos'

const STATUS_META: Record<RepoStatus, { label: string; tone: 'dim' | 'ok' | 'warn' | 'err' }> = {
  pending: { label: '排队中', tone: 'dim' },
  indexing: { label: '索引中', tone: 'warn' },
  ready: { label: '就绪', tone: 'ok' },
  failed: { label: '失败', tone: 'err' },
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
        {repo.status === 'indexing' && <Spinner />}
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
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [tree, setTree] = useState<FileNode[]>([])
  const [treeLoading, setTreeLoading] = useState(false)
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [treeError, setTreeError] = useState<string | null>(null)

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const busy = repos.some((r) => r.status === 'pending' || r.status === 'indexing')
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

  return (
    <div className="flex h-full min-h-0">
      <aside className="hidden w-80 shrink-0 flex-col border-r border-edge bg-panel lg:flex">
        <div className="flex items-center justify-between px-3 py-2.5">
          <span className="text-[12px] font-medium uppercase tracking-wide text-dim">工作区仓库</span>
          <Button size="sm" variant="ghost" onClick={() => setImportOpen(true)}>
            <FilePlus2 size={12} /> 导入
          </Button>
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
          <main className="min-w-0 flex-1 bg-base">
            <CodeViewer repoId={selected.id} path={selectedPath} />
          </main>
        </>
      ) : (
        <main className="min-w-0 flex-1">
          <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
            <p className="text-[14px] text-ink">选择一个仓库查看代码</p>
            <p className="max-w-md text-[12.5px] leading-relaxed text-dim">
              左侧是已导入的仓库列表。选中「就绪」状态的仓库可以浏览文件树与源码；聊天时也可以把仓库关联给 Nova
              作为上下文。
            </p>
            {repos.length > 0 && (
              <select
                className="rounded-lg border border-edge bg-raised px-3 py-1.5 text-[13px] outline-none lg:hidden"
                defaultValue=""
                onChange={(e) => {
                  if (e.target.value) {
                    setSelectedId(e.target.value)
                    setSelectedPath(null)
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
            <Button variant="primary" className="mt-1" onClick={() => setImportOpen(true)}>
              <FilePlus2 size={13} /> 导入仓库
            </Button>
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
    </div>
  )
}