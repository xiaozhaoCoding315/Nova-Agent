import clsx from 'clsx'
import {
  AlertTriangle, Check, ChevronRight, ClipboardCopy, GitBranch, Github, RefreshCw,
  ShieldCheck,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, Modal, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type {
  GitHubConnectionStatus, GitHubPullRequest, GitHubPullRequestStatus, GitHubRemote,
} from '../lib/types'
import { useRepos } from '../stores/repos'

const CHECK_TONE: Record<string, 'ok' | 'warn' | 'err' | 'dim'> = {
  success: 'ok',
  neutral: 'dim',
  skipped: 'dim',
  failure: 'err',
  timed_out: 'err',
  cancelled: 'err',
  action_required: 'err',
  pending: 'warn',
}

const REVIEW_LABEL: Record<string, { label: string; tone: 'ok' | 'warn' | 'err' | 'dim' }> = {
  APPROVED: { label: '已批准', tone: 'ok' },
  CHANGES_REQUESTED: { label: '要求修改', tone: 'err' },
  COMMENTED: { label: '有评论', tone: 'dim' },
  PENDING: { label: '待评审', tone: 'warn' },
}

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

function checkLabel(check: { status: string; conclusion: string }): string {
  if (check.status !== 'completed') return check.status === 'queued' ? '排队中' : '进行中'
  return check.conclusion || '完成'
}

export function GitHubPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const repos = useRepos((state) => state.repos)
  const readyRepos = repos.filter((repo) => repo.status === 'ready')

  const [repoId, setRepoId] = useState('')
  const [connection, setConnection] = useState<GitHubConnectionStatus | null>(null)
  const [remote, setRemote] = useState<GitHubRemote | null>(null)
  const [pullRequests, setPullRequests] = useState<GitHubPullRequest[]>([])
  const [selected, setSelected] = useState<GitHubPullRequestStatus | null>(null)

  const [token, setToken] = useState('')
  const [title, setTitle] = useState('')
  const [base, setBase] = useState('')
  const [body, setBody] = useState('')
  const [authorized, setAuthorized] = useState(false)
  const [copied, setCopied] = useState(false)

  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => {
    if (!repoId && readyRepos.length > 0) setRepoId(readyRepos[0].id)
  }, [readyRepos, repoId])

  const loadRepo = useCallback(async (id: string) => {
    if (!id) return
    setLoading(true)
    setError('')
    setRemote(null)
    setPullRequests([])
    setSelected(null)
    try {
      const [remoteData, prData] = await Promise.all([
        api.github.remote(id).catch(() => null),
        api.github.pullRequests(id),
      ])
      setRemote(remoteData)
      setPullRequests(prData.pull_requests)
    } catch (err) {
      setError(messageOf(err, '读取仓库的 GitHub 信息失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    setError('')
    setNotice('')
    void api.github
      .status()
      .then(setConnection)
      .catch((err) => setError(messageOf(err, '读取 GitHub 连接失败')))
  }, [open])

  useEffect(() => {
    if (open && repoId) void loadRepo(repoId)
  }, [open, repoId, loadRepo])

  const connect = async () => {
    if (!token.trim()) return
    setBusy(true)
    setError('')
    try {
      const status = await api.github.connect(token.trim())
      setConnection(status)
      setToken('')
      setNotice(`已连接 GitHub：${status.login}`)
    } catch (err) {
      setError(messageOf(err, '连接 GitHub 失败'))
    } finally {
      setBusy(false)
    }
  }

  const disconnect = async () => {
    if (!window.confirm('断开 GitHub？本机保存的 token 会被删除，已创建的 PR 不受影响。')) return
    setBusy(true)
    try {
      setConnection(await api.github.disconnect())
      setPullRequests([])
      setSelected(null)
      setNotice('已断开 GitHub')
    } catch (err) {
      setError(messageOf(err, '断开 GitHub 失败'))
    } finally {
      setBusy(false)
    }
  }

  const createPullRequest = async () => {
    if (!repoId || !authorized) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const created = await api.github.createPullRequest(repoId, {
        title: title.trim(),
        body: body.trim(),
        base: base.trim(),
        authorization: 'create-draft-pr',
      })
      setTitle('')
      setBody('')
      setBase('')
      setAuthorized(false)
      setNotice(`已创建 draft PR #${created.number}`)
      await loadRepo(repoId)
      await openPullRequest(created.number)
    } catch (err) {
      setError(messageOf(err, '创建 draft PR 失败'))
    } finally {
      setBusy(false)
    }
  }

  const openPullRequest = async (number: number) => {
    if (!repoId) return
    setBusy(true)
    setError('')
    try {
      setSelected(await api.github.pullRequest(repoId, number))
    } catch (err) {
      setError(messageOf(err, '读取 PR 状态失败'))
    } finally {
      setBusy(false)
    }
  }

  const copyReview = async () => {
    if (!selected) return
    const lines = [`来自 PR #${selected.number} 的评审意见：`]
    for (const review of selected.reviews) {
      if (review.body.trim()) lines.push(`- @${review.user}（${review.state}）：${review.body.trim()}`)
    }
    for (const comment of selected.comments) {
      const where = comment.path ? `（${comment.path}${comment.line ? `:${comment.line}` : ''}）` : ''
      if (comment.body.trim()) lines.push(`- @${comment.user}${where}：${comment.body.trim()}`)
    }
    if (lines.length === 1) {
      setNotice('这个 PR 还没有文字评审意见')
      return
    }
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      setCopied(true)
      setNotice('评审意见已复制，可以贴进对话继续修')
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setError('浏览器不允许读取剪贴板')
    }
  }

  const failing = selected?.checks.filter((check) => (
    check.status === 'completed' && !['success', 'neutral', 'skipped'].includes(check.conclusion)
  )) ?? []
  const running = selected?.checks.filter((check) => check.status !== 'completed') ?? []

  return (
    <Modal open={open} onClose={onClose} title="GitHub 交付" width="max-w-2xl">
      <div className="space-y-4">
        <div className="flex items-start gap-2 rounded-md border border-edge bg-panel/40 px-3 py-2">
          <Github size={15} className="mt-0.5 shrink-0 text-accent" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">draft PR、CI 与评审意见</p>
            <p className="mt-0.5 text-2xs leading-relaxed text-dim">
              只有在勾选授权后才会创建 draft PR。不会合并、不会推送主分支，也不会自动处理评审；
              合并仍由你在 GitHub 上决定。
            </p>
          </div>
          {connection?.connected && <Badge tone="ok">@{connection.login}</Badge>}
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-sm border border-err/30 bg-err/10 px-2.5 py-2 text-xs text-err">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span className="min-w-0 flex-1">{error}</span>
            <button onClick={() => setError('')} className="underline">关闭</button>
          </div>
        )}
        {notice && (
          <p className="flex items-center gap-1.5 rounded-sm border border-ok/30 bg-ok/10 px-2.5 py-2 text-xs text-ok">
            <Check size={12} /> {notice}
          </p>
        )}

        <section className="space-y-2">
          <p className="text-xs font-medium text-ink">连接</p>
          {!connection ? (
            <p className="text-2xs text-faint">读取中…</p>
          ) : connection.connected ? (
            <div className="flex flex-wrap items-center gap-2 rounded-sm border border-edge bg-panel/40 px-2.5 py-2">
              <span className="text-xs text-ink">@{connection.login}</span>
              <span className="font-mono text-2xs text-faint">
                权限：{connection.scopes || '未返回（fine-grained token 可能为空）'}
              </span>
              <button
                onClick={() => void disconnect()}
                disabled={busy}
                className="ml-auto text-2xs text-dim underline underline-offset-2 hover:text-err"
              >
                断开
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-1.5">
              <input
                type="password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="GitHub token（repo 权限）"
                className="min-w-0 flex-1 rounded-sm border border-edge bg-base px-2 py-1.5 font-mono text-xs text-ink outline-none focus:border-accent"
                autoComplete="off"
              />
              <Button size="sm" variant="primary" onClick={() => void connect()} disabled={busy || !token.trim()}>
                {busy ? <Spinner /> : <ShieldCheck size={12} />} 连接
              </Button>
            </div>
          )}
          <p className="text-2xs leading-relaxed text-faint">
            token 加密保存在服务器；接口只返回用户名和权限，不会回传 token。
          </p>
        </section>

        <section className="space-y-2">
          <div className="flex items-center gap-2">
            <p className="text-xs font-medium text-ink">仓库</p>
            <select
              value={repoId}
              onChange={(event) => setRepoId(event.target.value)}
              className="min-w-0 flex-1 rounded-sm border border-edge bg-base px-1.5 py-1 text-xs text-dim outline-none focus:border-accent"
            >
              {readyRepos.length === 0 && <option value="">还没有就绪的仓库</option>}
              {readyRepos.map((repo) => (
                <option key={repo.id} value={repo.id}>{repo.name}</option>
              ))}
            </select>
          </div>
          {remote && (
            <p className="flex flex-wrap items-center gap-1.5 font-mono text-2xs text-faint">
              <Github size={11} /> {remote.full_name}
              <GitBranch size={11} /> {remote.branch || 'detached'}
            </p>
          )}
          {loading && <p className="flex items-center gap-1.5 text-2xs text-faint"><Spinner /> 读取…</p>}
        </section>

        {connection?.connected && repoId && (
          <section className="space-y-2">
            <p className="text-xs font-medium text-ink">新建 draft PR</p>
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="标题"
              maxLength={200}
              className="w-full rounded-sm border border-edge bg-base px-2 py-1.5 text-xs text-ink outline-none focus:border-accent"
            />
            <div className="flex gap-1.5">
              <input
                value={base}
                onChange={(event) => setBase(event.target.value)}
                placeholder={`base 分支（默认 ${remote ? '仓库默认分支' : 'main'}）`}
                className="min-w-0 flex-1 rounded-sm border border-edge bg-base px-2 py-1.5 font-mono text-xs text-ink outline-none focus:border-accent"
              />
            </div>
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder="说明改了什么、怎么验证的；不写未验证的结论。"
              className="h-20 w-full resize-none rounded-sm border border-edge bg-base px-2 py-1.5 text-xs text-ink outline-none focus:border-accent"
            />
            <label className="flex items-start gap-1.5 text-2xs leading-relaxed text-dim">
              <input
                type="checkbox"
                checked={authorized}
                onChange={(event) => setAuthorized(event.target.checked)}
                className="mt-0.5 accent-current"
              />
              我确认已推送当前分支，并授权在 {remote?.full_name || '这个仓库'} 创建 draft PR。
            </label>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void createPullRequest()}
              disabled={busy || !authorized || !title.trim()}
            >
              {busy ? <Spinner /> : <Github size={12} />} 创建 draft PR
            </Button>
          </section>
        )}

        <section className="space-y-1.5">
          <p className="text-xs font-medium text-ink">本机记录的 PR</p>
          {pullRequests.length === 0 ? (
            <p className="text-2xs text-faint">这个仓库还没有从这里创建过 PR。</p>
          ) : (
            <ul className="space-y-1">
              {pullRequests.map((pr) => (
                <li key={pr.number}>
                  <button
                    onClick={() => void openPullRequest(pr.number)}
                    className={clsx(
                      'flex w-full items-center gap-2 rounded-sm border px-2 py-1.5 text-left transition-colors',
                      selected?.number === pr.number
                        ? 'border-accent/40 bg-accentSoft/20'
                        : 'border-edge bg-panel/40 hover:bg-raised',
                    )}
                  >
                    <span className="font-mono text-2xs text-faint">#{pr.number}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-ink">{pr.title}</span>
                    <Badge tone={pr.state === 'open' ? (pr.draft ? 'warn' : 'ok') : 'dim'}>
                      {pr.state === 'open' ? (pr.draft ? 'draft' : 'open') : pr.state}
                    </Badge>
                    <ChevronRight size={12} className="shrink-0 text-faint" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {selected && (
          <section className="space-y-2 rounded-md border border-edge bg-panel/40 p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-2xs text-faint">#{selected.number}</span>
              <span className="min-w-0 flex-1 truncate text-xs text-ink">{selected.title}</span>
              <Badge tone={selected.draft ? 'warn' : selected.state === 'open' ? 'ok' : 'dim'}>
                {selected.draft ? 'draft' : selected.state}
              </Badge>
              <button
                onClick={() => void openPullRequest(selected.number)}
                disabled={busy}
                className="rounded-sm p-1 text-dim hover:text-ink"
                title="刷新 CI 与评审"
                aria-label="刷新 PR 状态"
              >
                {busy ? <Spinner /> : <RefreshCw size={12} />}
              </button>
              <a
                href={selected.url}
                target="_blank"
                rel="noreferrer"
                className="text-2xs text-accent underline underline-offset-2"
              >
                在 GitHub 打开
              </a>
            </div>
            <p className="font-mono text-2xs text-faint">
              {selected.head} → {selected.base} · {selected.head_sha.slice(0, 8)}
            </p>

            <div>
              <p className="text-2xs text-dim">
                CI：{selected.checks.length === 0
                  ? '还没有检查结果'
                  : `${selected.checks.length} 项，${failing.length} 失败，${running.length} 进行中`}
              </p>
              {selected.checks.length > 0 && (
                <ul className="mt-1 space-y-0.5">
                  {selected.checks.map((check, index) => (
                    <li key={`${check.name}-${index}`} className="flex items-center gap-1.5 text-2xs">
                      <Badge tone={CHECK_TONE[check.conclusion] ?? 'warn'}>{checkLabel(check)}</Badge>
                      <span className="min-w-0 flex-1 truncate text-dim">{check.name}</span>
                      {check.url && (
                        <a href={check.url} target="_blank" rel="noreferrer" className="text-accent underline">
                          日志
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div>
              <div className="flex items-center justify-between">
                <p className="text-2xs text-dim">评审意见（{selected.reviews.length + selected.comments.length}）</p>
                <button
                  onClick={() => void copyReview()}
                  className="flex items-center gap-1 text-2xs text-accent underline underline-offset-2"
                >
                  {copied ? <Check size={11} /> : <ClipboardCopy size={11} />} 复制意见
                </button>
              </div>
              {selected.reviews.length === 0 && selected.comments.length === 0 ? (
                <p className="mt-1 text-2xs text-faint">还没有评审意见。</p>
              ) : (
                <ul className="mt-1 space-y-1">
                  {selected.reviews.map((review) => {
                    const label = REVIEW_LABEL[review.state] ?? { label: review.state, tone: 'dim' as const }
                    return (
                      <li key={`review-${review.id}`} className="rounded-sm border border-edge bg-base/60 px-2 py-1.5">
                        <div className="flex items-center gap-1.5">
                          <Badge tone={label.tone}>{label.label}</Badge>
                          <span className="text-2xs text-faint">@{review.user}</span>
                        </div>
                        {review.body && <p className="mt-0.5 whitespace-pre-wrap text-xs leading-relaxed">{review.body}</p>}
                      </li>
                    )
                  })}
                  {selected.comments.map((comment) => (
                    <li key={`comment-${comment.id}`} className="rounded-sm border border-edge bg-base/60 px-2 py-1.5">
                      <p className="font-mono text-2xs text-faint">
                        @{comment.user}
                        {comment.path ? ` · ${comment.path}${comment.line ? `:${comment.line}` : ''}` : ''}
                      </p>
                      <p className="mt-0.5 whitespace-pre-wrap text-xs leading-relaxed">{comment.body}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <p className="text-2xs leading-relaxed text-faint">{selected.note}</p>
          </section>
        )}
      </div>
    </Modal>
  )
}
