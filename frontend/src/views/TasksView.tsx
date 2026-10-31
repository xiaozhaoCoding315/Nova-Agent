import clsx from 'clsx'
import {
  CheckCircle2, ClipboardList, FlaskConical, Plus, RefreshCw, ShieldCheck, XCircle, XOctagon,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { DiffView } from '../components/DiffView'
import { ReviewPanel } from '../components/ReviewPanel'
import { Badge, Button, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { Task, TaskListItem, TaskStep } from '../lib/types'
import { useRepos } from '../stores/repos'

/**
 * 修复任务视图（红-绿）：描述问题，Nova 先写失败测试复现，再生成最小补丁并跑到测试通过，
 * 写入仓库前由用户确认。
 */

type Bucket = 'running' | 'review' | 'done' | 'closed' | 'failed'

const TASK_BUCKET: Record<string, Bucket> = {
  running: 'running', ready: 'review', applied: 'done', rejected: 'closed', failed: 'failed',
}

const BUCKET_META: Record<Bucket, { label: string; tone: 'dim' | 'ok' | 'warn' | 'err' | 'accent' }> = {
  running: { label: '进行中', tone: 'warn' },
  review: { label: '待确认', tone: 'accent' },
  done: { label: '已完成', tone: 'ok' },
  closed: { label: '已关闭', tone: 'dim' },
  failed: { label: '失败', tone: 'err' },
}

type UnifiedItem = {
  key: string
  id: string
  title: string
  bucket: Bucket
  repoName: string
  time: string
  meta: string
  error?: string | null
}

function timestamp(value?: string | null): number {
  if (!value) return 0
  const t = new Date(value).getTime()
  return Number.isNaN(t) ? 0 : t
}

function mergeItems(tasks: TaskListItem[]): UnifiedItem[] {
  const items: UnifiedItem[] = tasks.map((t) => ({
    key: `task-${t.id}`,
    id: t.id,
    title: t.title,
    bucket: TASK_BUCKET[t.status] ?? 'running',
    repoName: t.repo_name,
    time: t.created_at ?? '',
    meta: '修复任务',
  }))
  return items.sort((a, b) => timestamp(b.time) - timestamp(a.time))
}

function BucketBadge({ bucket }: { bucket: Bucket }) {
  const meta = BUCKET_META[bucket]
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

/* ---------------- 修复任务详情 ---------------- */

const STEP_LABEL: Record<string, string> = {
  locate: '定位相关代码',
  analyze: '生成复现测试与修复',
  red: '红 · 修复前测试应失败',
  green: '绿 · 修复后测试应通过',
  error: '执行出错',
  running: '执行中',
  done: '完成',
}

function StepRow({ step }: { step: TaskStep }) {
  const [open, setOpen] = useState(step.step === 'red' || step.step === 'green')
  const running = step.status === 'running'
  const failed = step.status === 'failed' || step.status === 'warn'
  return (
    <div className="rounded-lg border border-edge bg-panel/50">
      <button className="flex w-full items-center gap-2 px-3 py-2 text-left" onClick={() => setOpen(!open)}>
        {running && <Spinner />}
        {!running && !failed && <CheckCircle2 size={13} className="text-ok" />}
        {failed && <XCircle size={13} className="text-err" />}
        <span className="text-[12.5px] font-medium text-ink">{STEP_LABEL[step.step] ?? step.step}</span>
        {typeof step.exit_code === 'number' && <span className="font-mono text-[11px] text-dim">exit {step.exit_code}</span>}
        {step.detail && <span className="ml-auto truncate text-[11.5px] text-dim">{step.detail}</span>}
      </button>
      {open && (
        <div className="space-y-1.5 border-t border-edge px-3 py-2 text-[11.5px] text-dim">
          {step.analysis && <p className="whitespace-pre-wrap">{step.analysis}</p>}
          {step.test_files && step.test_files.length > 0 && <p className="font-mono">测试文件：{step.test_files.join('，')}</p>}
          {step.fix_files && step.fix_files.length > 0 && <p className="font-mono">修改文件：{step.fix_files.join('，')}</p>}
          {step.command && <p className="break-all font-mono">命令：{step.command}</p>}
          {step.stdout && (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11px]">{step.stdout}</pre>
          )}
          {step.stderr && (
            <pre className="max-h-24 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11px] text-err">{step.stderr}</pre>
          )}
        </div>
      )}
    </div>
  )
}

function FixDetail({
  taskId, onError, onChanged,
}: {
  taskId: string
  onError: (message: string | null) => void
  onChanged: () => void
}) {
  const [detail, setDetail] = useState<Task | null>(null)
  const [busy, setBusy] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const load = async () => {
    try {
      const next = await api.tasks.get(taskId)
      setDetail(next)
      onError(null)
    } catch (err) {
      onError(err instanceof ApiError ? err.message : '加载任务失败')
    }
  }

  useEffect(() => {
    let alive = true
    void load()
    if (!detail || detail.status !== 'running') {
      return () => {
        alive = false
      }
    }
    const timer = setInterval(() => {
      if (alive) void load()
    }, 2500)
    return () => {
      alive = false
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId, detail?.status])

  const act = async (kind: 'apply' | 'reject') => {
    if (!detail) return
    setBusy(true)
    onError(null)
    try {
      if (kind === 'apply') {
        const res = await api.tasks.apply(detail.id)
        setNotice(`已写入 ${res.applied.length} 个文件，正在重建索引`)
      } else {
        await api.tasks.reject(detail.id)
        setNotice('已拒绝该修复')
      }
      setDetail(await api.tasks.get(detail.id))
      onChanged()
    } catch (err) {
      onError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setBusy(false)
    }
  }

  const runReview = async () => {
    if (!detail) return
    setReviewing(true)
    onError(null)
    try {
      await api.tasks.review(detail.id)
      setDetail(await api.tasks.get(detail.id))
    } catch (err) {
      onError(err instanceof ApiError ? err.message : '审查失败')
    } finally {
      setReviewing(false)
    }
  }

  if (!detail) {
    return (
      <div className="flex h-full items-center justify-center text-[12.5px] text-dim">
        <Spinner /> 加载中…
      </div>
    )
  }

  const result = detail.result ?? {}
  // 引擎会为同一阶段先写 running 再写 done，去重后时间线更干净。
  const latestSteps = Object.values(
    detail.steps.reduce<Record<string, TaskStep>>((acc, step) => {
      acc[step.step] = step
      return acc
    }, {}),
  )

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <FlaskConical size={15} className="shrink-0 text-accent" />
        <h2 className="min-w-0 flex-1 truncate text-[16px] font-semibold" title={detail.title}>{detail.title}</h2>
        <BucketBadge bucket={TASK_BUCKET[detail.status] ?? 'running'} />
        <button
          className="flex items-center gap-1 rounded-md border border-edge px-2 py-0.5 text-[11px] text-dim hover:text-ink disabled:opacity-40"
          onClick={() => void runReview()}
          disabled={reviewing || !['ready', 'failed'].includes(detail.status)}
          title="只读审查当前 diff，不会修改文件"
        >
          {reviewing ? <Spinner /> : <ShieldCheck size={11} />} 审查
        </button>
        <button className="text-dim hover:text-ink" onClick={() => void load()} title="刷新">
          <RefreshCw size={13} />
        </button>
      </div>
      <p className="text-[11.5px] text-dim">
        {detail.repo_name} · {detail.created_at ? new Date(detail.created_at).toLocaleString() : ''}
      </p>

      <section className="rounded-lg border border-edge bg-panel/50 p-3">
        <p className="mb-1 text-[11.5px] uppercase tracking-wide text-dim">问题描述</p>
        <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed">{detail.bug_report}</p>
      </section>

      {notice && <p className="text-[12.5px] text-ok">{notice}</p>}

      <section className="space-y-2">
        {latestSteps.map((step, i) => (
          <StepRow key={`${step.step}-${i}`} step={step} />
        ))}
        {detail.status === 'running' && (
          <p className="flex items-center gap-2 px-1 text-[12px] text-dim"><Spinner /> 正在沙箱中执行，请稍候…</p>
        )}
      </section>

      {result.error && (
        <p className="rounded-lg border border-err/40 bg-err/5 p-3 text-[12.5px] text-err">{result.error}</p>
      )}

      {result.analysis && (
        <section>
          <h3 className="mb-1 text-[13px] font-medium">根因分析</h3>
          <p className="whitespace-pre-wrap rounded-lg border border-edge bg-panel/40 p-3 text-[12.5px] leading-relaxed text-dim">
            {result.analysis}
          </p>
        </section>
      )}

      {result.diff && (
        <section>
          <h3 className="mb-1 flex items-center gap-2 text-[13px] font-medium">
            <ClipboardList size={13} /> 变更预览{result.applied ? '（已应用）' : '（未应用）'}
          </h3>
          <DiffView diff={result.diff} />
        </section>
      )}

      <ReviewPanel review={result.review} />

      {(result.red || result.green) && (
        <section className="grid gap-3 md:grid-cols-2">
          {result.red && (
            <div className="rounded-lg border border-edge bg-panel/40 p-3">
              <p className="mb-1 text-[12px] text-err">红 · 修复前测试失败（exit {result.red.exit_code}）</p>
              <pre className="max-h-32 overflow-auto whitespace-pre-wrap font-mono text-[10.5px] text-dim">
                {(result.red.stdout || result.red.stderr || '').slice(-1200)}
              </pre>
            </div>
          )}
          {result.green && (
            <div className="rounded-lg border border-edge bg-panel/40 p-3">
              <p className="mb-1 text-[12px] text-ok">绿 · 修复后测试通过（exit {result.green.exit_code}）</p>
              <pre className="max-h-32 overflow-auto whitespace-pre-wrap font-mono text-[10.5px] text-dim">
                {(result.green.stdout || result.green.stderr || '').slice(-1200)}
              </pre>
            </div>
          )}
        </section>
      )}

      {detail.status === 'ready' && (
        <section className="flex flex-wrap items-center gap-2">
          <Button variant="primary" onClick={() => void act('apply')} disabled={busy}>
            {busy ? <Spinner /> : <CheckCircle2 size={13} />} 批准并写入仓库
          </Button>
          <Button variant="danger" onClick={() => void act('reject')} disabled={busy}>
            <XOctagon size={13} /> 拒绝
          </Button>
          <span className="text-[11.5px] text-dim">批准后自动更新项目分析</span>
        </section>
      )}

      {detail.status === 'applied' && (
        <p className="flex items-center gap-2 text-[12.5px] text-ok">
          <CheckCircle2 size={13} /> 已写入项目，代码阅读正在更新。
        </p>
      )}
    </div>
  )
}

/* ---------------- 统一入口 ---------------- */

export function TasksView({
  initialRepoId,
  onBackToChat,
}: {
  initialRepoId?: string
  onBackToChat?: () => void
} = {}) {
  const { repos, refresh: refreshRepos } = useRepos()
  const [tasks, setTasks] = useState<TaskListItem[]>([])
  const [filter, setFilter] = useState<'all' | Bucket>('all')
  const [selected, setSelected] = useState<UnifiedItem | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [repoId, setRepoId] = useState(initialRepoId ?? '')
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)

  const readyRepos = repos.filter((repo) => repo.status === 'ready')

  const items = useMemo(() => mergeItems(tasks), [tasks])
  const filtered = filter === 'all' ? items : items.filter((item) => item.bucket === filter)
  const counts = useMemo(() => {
    const map: Record<string, number> = { all: items.length }
    for (const item of items) map[item.bucket] = (map[item.bucket] ?? 0) + 1
    return map
  }, [items])

  const loadLists = async () => {
    const taskList = await api.tasks.list().catch(() => [] as TaskListItem[])
    setTasks(taskList)
  }

  useEffect(() => {
    void refreshRepos()
    void loadLists()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (repoId || readyRepos.length === 0) return
    setRepoId(initialRepoId ?? readyRepos[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readyRepos])

  useEffect(() => {
    if (!items.some((item) => item.bucket === 'running')) return
    const timer = setInterval(() => void loadLists(), 5000)
    return () => clearInterval(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items])

  // 保持选中项与列表同步（状态变化后仍指向同一条任务）。
  useEffect(() => {
    if (!selected) return
    const next = items.find((item) => item.key === selected.key)
    if (next && next !== selected) setSelected(next)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [items])

  const create = async () => {
    if (!repoId || description.trim().length < 5) {
      setError('请选择项目，并描述至少 5 个字')
      return
    }
    setCreating(true)
    setError(null)
    try {
      const task = await api.tasks.create(repoId, description.trim())
      setSelected({
        key: `task-${task.id}`, id: task.id, title: task.title,
        bucket: 'running', repoName: task.repo_name, time: task.created_at ?? '', meta: '修复任务',
      })
      setDescription('')
      await loadLists()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建任务失败')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b border-edge/80 bg-panel/25 px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12.5px] font-medium">把一个问题交给 Nova 修复，过程中的验证与写入都由你确认</span>
          <span className="hidden text-[11px] text-dim md:inline">
            修复任务会先写失败测试复现（红），再生成最小补丁并跑到测试通过（绿），最后等你批准写入。
          </span>
          {onBackToChat && (
            <button
              onClick={onBackToChat}
              className="ml-auto flex items-center gap-1 rounded-lg border border-edge/80 px-2.5 py-1.5 text-[11px] text-dim transition-colors hover:text-ink"
            >
              回到对话
            </button>
          )}
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-80 shrink-0 flex-col border-r border-edge bg-panel/40">
          <div className="space-y-2 border-b border-edge p-3">
            <select
              className="w-full rounded-md border border-edge bg-base px-2 py-1.5 text-[12px]"
              value={repoId}
              onChange={(e) => setRepoId(e.target.value)}
            >
              <option value="">{readyRepos.length === 0 ? '暂无可用项目' : '选择项目'}</option>
              {readyRepos.map((repo) => (
                <option key={repo.id} value={repo.id}>{repo.name}</option>
              ))}
            </select>
            <textarea
              className="min-h-20 w-full rounded-md border border-edge bg-base px-2 py-1.5 text-[12px]"
              placeholder="描述要修复的问题：例如「结算时折扣超过 100% 会把总价算成负数」"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <div className="flex items-center justify-end">
              <Button size="sm" variant="primary" onClick={() => void create()} disabled={creating || !repoId || description.trim().length < 5}>
                {creating ? <Spinner /> : <Plus size={12} />} 创建
              </Button>
            </div>
          </div>

          <div className="flex gap-1 border-b border-edge/70 px-2 py-1.5">
            {(['all', 'running', 'review', 'done'] as const).map((key) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={clsx(
                  'rounded-md px-2 py-0.5 text-[11px] transition-colors',
                  filter === key ? 'bg-accentSoft/40 text-ink' : 'text-dim hover:text-ink',
                )}
              >
                {key === 'all' ? '全部' : BUCKET_META[key].label}
                <span className="ml-1 text-[9.5px] text-dim/60">{counts[key] ?? 0}</span>
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-auto p-2">
            {items.length === 0 && (
              <p className="px-2 py-4 text-[12px] leading-relaxed text-dim">
                还没有修复任务。在上方描述一个问题，创建后 Nova 会自动推进，关键节点停下来等你确认。
              </p>
            )}
            {filtered.map((item) => (
              <button
                key={item.key}
                onClick={() => {
                  setSelected(item)
                  setError(null)
                }}
                className={clsx(
                  'mb-1 w-full rounded-lg border px-2.5 py-2 text-left transition-colors',
                  selected?.key === item.key
                    ? 'border-accentSoft bg-accentSoft/20'
                    : 'border-transparent hover:border-edge hover:bg-raised',
                )}
              >
                <div className="flex items-center gap-2">
                  <FlaskConical size={11} className="shrink-0 text-dim" />
                  <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium">{item.title}</span>
                  <BucketBadge bucket={item.bucket} />
                </div>
                <p className="mt-0.5 truncate text-[11px] text-dim">
                  {item.repoName} · {item.meta}
                  {item.time ? ` · ${new Date(item.time).toLocaleString()}` : ''}
                </p>
                {item.error && <p className="mt-0.5 truncate text-[11px] text-err">{item.error}</p>}
              </button>
            ))}
          </div>
        </aside>

        <main className="min-w-0 flex-1 overflow-y-auto">
          {error && (
            <div className="mx-4 mt-3 rounded-lg border border-err/30 bg-err/10 px-3 py-2 text-[12px] text-err">{error}</div>
          )}
          {selected && (
            <FixDetail
              key={selected.key}
              taskId={selected.id}
              onError={setError}
              onChanged={() => void loadLists()}
            />
          )}
          {!selected && (
            <div className="flex h-full items-center justify-center px-6 text-center text-[12.5px] leading-relaxed text-dim">
              从左侧选择一个修复任务，或在上方描述一个问题。<br />
              小改动和问答直接回「对话」即可，不用建任务。
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
