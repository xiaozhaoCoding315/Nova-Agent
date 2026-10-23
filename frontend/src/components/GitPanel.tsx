import clsx from 'clsx'
import {
  CheckCircle2, Download, FileCode2, GitBranch, GitCommitHorizontal, History, RotateCcw,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import type { GitInfo } from '../lib/types'
import { Badge, Button, Spinner } from './common'
import { DiffView } from './DiffView'

export function GitPanel({
  repoId,
  repoName,
  onChanged,
}: {
  repoId: string
  repoName: string
  onChanged: () => void
}) {
  const [info, setInfo] = useState<GitInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [diff, setDiff] = useState<string | null>(null)
  const [confirmHash, setConfirmHash] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const load = async () => {
    try {
      setInfo(await api.git.status(repoId))
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载 Git 状态失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    setDiff(null)
    setNotice(null)
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId])

  const act = async (kind: 'init' | 'commit' | 'diff' | 'rollback', commitHash?: string) => {
    setBusy(kind)
    setError(null)
    setNotice(null)
    try {
      if (kind === 'init') {
        setInfo(await api.git.init(repoId))
        setNotice('Git 仓库已初始化，并创建了首个快照提交')
      } else if (kind === 'commit') {
        setInfo(await api.git.commit(repoId, message.trim() || undefined))
        setMessage('')
        setNotice('已提交')
      } else if (kind === 'diff') {
        const result = await api.git.diff(repoId)
        setDiff(result.diff || '')
      } else if (kind === 'rollback' && commitHash) {
        setInfo(await api.git.rollback(repoId, commitHash))
        setConfirmHash(null)
        setDiff(null)
        setNotice('已回滚到该提交，并开始重建索引')
        onChanged()
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setBusy(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 p-4 text-[13px] text-dim">
        <Spinner /> 加载 Git 状态…
      </div>
    )
  }

  if (!info) {
    return <p className="p-4 text-[13px] text-err">{error ?? 'Git 不可用'}</p>
  }

  if (!info.available) {
    return (
      <div className="p-4 text-[13px] text-dim">
        服务器未安装 git，Git 交付不可用。安装 git 后重启服务即可。
      </div>
    )
  }

  if (!info.initialized) {
    return (
      <div className="p-4">
        <h3 className="flex items-center gap-2 text-[14px] font-medium">
          <GitBranch size={15} className="text-accent" /> 为工作区启用 Git
        </h3>
        <p className="mt-1 max-w-lg text-[12.5px] leading-relaxed text-dim">
          初始化后会创建首个快照提交。之后对话编辑、任务修复、Builder 写入都会在已初始化的仓库里自动提交，便于回滚与导出。
        </p>
        {error && <p className="mt-2 text-[12.5px] text-err">{error}</p>}
        <Button variant="primary" className="mt-3" onClick={() => void act('init')} disabled={busy !== null}>
          {busy === 'init' ? <Spinner /> : <GitBranch size={13} />} 初始化 Git
        </Button>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="flex items-center gap-2 text-[14px] font-medium">
          <GitBranch size={15} className="text-accent" /> {info.branch}
        </h3>
        {info.dirty ? (
          <Badge tone="warn">{info.changed_files ?? 0} 个未提交改动</Badge>
        ) : (
          <Badge tone="ok">工作区干净</Badge>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" onClick={() => void act('diff')} disabled={busy !== null}>
            {busy === 'diff' ? <Spinner /> : <FileCode2 size={12} />} 查看 diff
          </Button>
          <a
            href={api.repos.exportUrl(repoId)}
            className="inline-flex items-center gap-1 rounded-md border border-edge bg-raised px-2.5 py-1 text-[12px] text-ink hover:border-accentSoft"
          >
            <Download size={12} /> 导出 zip
          </a>
        </div>
      </div>

      {error && <p className="mt-3 text-[12.5px] text-err">{error}</p>}
      {notice && <p className="mt-3 text-[12.5px] text-ok">{notice}</p>}

      <div className="mt-4 flex items-center gap-2">
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && void act('commit')}
          placeholder="提交说明（可选），例如：feat: 完成健康检查接口"
          className="min-w-0 flex-1 rounded-lg border border-edge bg-raised px-3 py-1.5 text-[12.5px] outline-none placeholder:text-dim/60 focus:border-accentSoft"
        />
        <Button variant="primary" size="sm" onClick={() => void act('commit')} disabled={busy !== null}>
          {busy === 'commit' ? <Spinner /> : <GitCommitHorizontal size={12} />} 提交
        </Button>
      </div>

      {diff !== null && (
        <div className="mt-3">
          <h4 className="mb-1 text-[12.5px] font-medium">未提交改动</h4>
          <DiffView diff={diff} maxHeight="max-h-72" />
        </div>
      )}

      <h4 className="mb-2 mt-5 flex items-center gap-1.5 text-[12.5px] font-medium">
        <History size={12} /> 提交历史（{info.commits.length}）
      </h4>
      <div className="space-y-1">
        {info.commits.map((commit) => (
          <div
            key={commit.hash}
            className="flex items-center gap-2 rounded-lg border border-edge bg-panel/40 px-2.5 py-1.5"
          >
            <span className="font-mono text-[11px] text-accent">{commit.hash.slice(0, 8)}</span>
            <span className="min-w-0 flex-1 truncate text-[12px]">{commit.message}</span>
            <span className="hidden text-[10.5px] text-dim md:inline">{commit.date}</span>
            {confirmHash === commit.hash ? (
              <div className="flex items-center gap-1">
                <button
                  className="rounded border border-err/50 px-1.5 py-0.5 text-[10.5px] text-err"
                  onClick={() => void act('rollback', commit.hash)}
                >
                  确认回滚
                </button>
                <button
                  className="text-[10.5px] text-dim hover:text-ink"
                  onClick={() => setConfirmHash(null)}
                >
                  取消
                </button>
              </div>
            ) : (
              <button
                className={clsx('rounded px-1.5 py-0.5 text-[10.5px]', 'text-dim hover:text-warn')}
                onClick={() => setConfirmHash(commit.hash)}
                title="回滚会丢弃未提交改动"
              >
                <RotateCcw size={11} />
              </button>
            )}
          </div>
        ))}
        {info.commits.length === 0 && <p className="text-[12px] text-dim">还没有提交。</p>}
      </div>

      <p className="mt-4 text-[11px] leading-relaxed text-dim">
        提示：回滚使用 <code className="rounded bg-raised px-1">git reset --hard</code>，会丢弃未提交改动；回滚后自动重建索引。
        {repoName ? ` 当前工作区：${repoName}` : ''}
      </p>
      <p className="mt-1 flex items-center gap-1 text-[11px] text-dim">
        <CheckCircle2 size={11} className="text-ok" /> 已初始化的仓库在编辑/任务/Builder 写入后会自动提交
      </p>
    </div>
  )
}