import clsx from 'clsx'
import {
  CheckCircle2, ClipboardList, FlaskConical, Plus, RefreshCw, ShieldCheck, XCircle, XOctagon,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { DiffView } from '../components/DiffView'
import { Badge, Button, Spinner } from '../components/common'
import { ReviewPanel } from '../components/ReviewPanel'
import { api, ApiError } from '../lib/api'
import type { Task, TaskListItem, TaskStep } from '../lib/types'
import { useRepos } from '../stores/repos'

const STATUS_META: Record<string, { label: string; tone: 'dim' | 'ok' | 'warn' | 'err' | 'accent' }> = {
  running: { label: '运行中', tone: 'warn' },
  ready: { label: '待审阅', tone: 'accent' },
  applied: { label: '已应用', tone: 'ok' },
  rejected: { label: '已拒绝', tone: 'dim' },
  failed: { label: '失败', tone: 'err' },
}

const STEP_LABEL: Record<string, string> = {
  locate: '定位相关代码',
  analyze: '生成复现测试与修复',
  red: '红阶段 · 修复前测试应失败',
  green: '绿阶段 · 修复后测试应通过',
  error: '执行出错',
}

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { label: status, tone: 'dim' as const }
  return <Badge tone={meta.tone}>{meta.label}</Badge>
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
        {typeof step.exit_code === 'number' && (
          <span className="font-mono text-[11px] text-dim">exit {step.exit_code}</span>
        )}
        {step.detail && <span className="ml-auto truncate text-[11.5px] text-dim">{step.detail}</span>}
      </button>
      {open && (
        <div className="space-y-1.5 border-t border-edge px-3 py-2 text-[11.5px] text-dim">
          {step.files && step.files.length > 0 && (
            <p className="font-mono">读取文件：{step.files.join('，')}</p>
          )}
          {step.root_prefix && <p className="font-mono">顶层目录：{step.root_prefix}</p>}
          {step.analysis && <p className="whitespace-pre-wrap">{step.analysis}</p>}
          {step.test_files && step.test_files.length > 0 && (
            <p className="font-mono">测试文件：{step.test_files.join('，')}</p>
          )}
          {step.fix_files && step.fix_files.length > 0 && (
            <p className="font-mono">修改文件：{step.fix_files.join('，')}</p>
          )}
          {step.command && <p className="break-all font-mono">命令：{step.command}</p>}
          {step.stdout && (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11px]">
              {step.stdout}
            </pre>
          )}
          {step.stderr && (
            <pre className="max-h-24 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-[11px] text-err">
              {step.stderr}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

export function TasksView({ initialRepoId }: { initialRepoId?: string } = {}) {
  const { repos, refresh: refreshRepos } = useRepos()
  const [tasks, setTasks] = useState<TaskListItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<Task | null>(null)
  const [creating, setCreating] = useState(false)
  const [repoId, setRepoId] = useState(initialRepoId ?? '')
  const [bug, setBug] = useState('')
  const [busy, setBusy] = useState(false)
  const [reviewing, setReviewing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const readyRepos = repos.filter((r) => r.status === 'ready')

  const loadList = async () => {
    try {
      setTasks(await api.tasks.list())
    } catch {
      /* non-fatal */
    }
  }

  useEffect(() => {
    void refreshRepos()
    void loadList()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!readyRepos.length) return
    if (!repoId) setRepoId(readyRepos[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repos])

  useEffect(() => {
    if (!tasks.some((t) => t.status === 'running')) return
    const timer = setInterval(() => void loadList(), 3000)
    return () => clearInterval(timer)
  }, [tasks])

  useEffect(() => {
    if (!selectedId) {
      setDetail(null)
      return
    }
    let cancelled = false
    const load = async () => {
      try {
        const task = await api.tasks.get(selectedId)
        if (!cancelled) setDetail(task)
        if (task.status !== 'running') void loadList()
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : '加载任务失败')
      }
    }
    void load()
    const timer = setInterval(() => {
      if (detail?.status === 'running' || !detail) void load()
    }, 2500)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, detail?.status])

  const create = async () => {
    if (!repoId || bug.trim().length < 5) return
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const task = await api.tasks.create(repoId, bug.trim())
      setDetail(task)
      setSelectedId(task.id)
      setCreating(false)
      setBug('')
      void loadList()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '创建任务失败')
    } finally {
      setBusy(false)
    }
  }

  const act = async (kind: 'apply' | 'reject') => {
    if (!detail) return
    setBusy(true)
    setError(null)
    try {
      if (kind === 'apply') {
        const res = await api.tasks.apply(detail.id)
        setNotice(`已写入 ${res.applied.length} 个文件，正在重建索引`)
      } else {
        await api.tasks.reject(detail.id)
        setNotice('已拒绝该修复')
      }
      setDetail(await api.tasks.get(detail.id))
      void loadList()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setBusy(false)
    }
  }

  const runReview = async () => {
    if (!detail) return
    setReviewing(true)
    setError(null)
    try {
      await api.tasks.review(detail.id)
      setDetail(await api.tasks.get(detail.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '审查失败')
    } finally {
      setReviewing(false)
    }
  }

  const status = detail?.status ?? ''
  const result = detail?.result ?? {}
  // The engine appends a "running" step and later a "done" step for the same
  // phase — keep only the latest entry per phase so the timeline reads cleanly.
  const latestSteps = detail
    ? Object.values(
        detail.steps.reduce<Record<string, TaskStep>>((acc, step) => {
          acc[step.step] = step
          return acc
        }, {}),
      )
    : []

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-72 shrink-0 flex-col border-r border-edge bg-panel">
        <div className="flex items-center justify-between px-3 py-2.5">
          <span className="text-[12px] font-medium uppercase tracking-wide text-dim">修复任务</span>
          <Button size="sm" variant="ghost" onClick={() => { setCreating(true); setSelectedId(null) }}>
            <Plus size={12} /> 新建
          </Button>
        </div>
        <div className="flex-1 space-y-1.5 overflow-y-auto px-2 pb-2">
          {tasks.length === 0 && (
            <p className="px-1 py-3 text-[12.5px] leading-relaxed text-dim">
              还没有任务。新建一个：贴 bug 描述，Nova 会先生成失败测试复现（红），再给补丁并跑到通过（绿），你批准后才写入仓库。
            </p>
          )}
          {tasks.map((task) => (
            <button
              key={task.id}
              onClick={() => { setSelectedId(task.id); setCreating(false); setNotice(null); setError(null) }}
              className={clsx(
                'w-full rounded-lg border px-2.5 py-2 text-left transition-colors',
                selectedId === task.id
                  ? 'border-accent bg-accentSoft/25'
                  : 'border-edge bg-panel/60 hover:border-accentSoft',
              )}
            >
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-[12.5px]">{task.title}</span>
                <StatusBadge status={task.status} />
              </div>
              <p className="mt-0.5 truncate text-[11px] text-dim">{task.repo_name}</p>
            </button>
          ))}
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto">
        {creating || (!detail && tasks.length === 0) ? (
          <div className="mx-auto max-w-2xl p-6">
            <h2 className="flex items-center gap-2 text-[16px] font-semibold">
              <FlaskConical size={16} className="text-accent" /> 新建修复任务
            </h2>
            <p className="mt-1 text-[12.5px] leading-relaxed text-dim">
              描述现象与期望。Nova 会在沙箱里先复现（测试必须失败），再给出最小修复并跑到通过，最后等你批准。
            </p>
            <div className="mt-4 space-y-3">
              <div>
                <label className="mb-1 block text-[12px] text-dim">选择仓库（需已就绪）</label>
                <select
                  value={repoId}
                  onChange={(e) => setRepoId(e.target.value)}
                  className="w-full rounded-lg border border-edge bg-raised px-3 py-2 text-[13px] outline-none"
                >
                  {readyRepos.length === 0 && <option value="">暂无就绪仓库，请先去工作区导入</option>}
                  {readyRepos.map((repo) => (
                    <option key={repo.id} value={repo.id}>
                      {repo.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[12px] text-dim">Bug 描述</label>
                <textarea
                  value={bug}
                  onChange={(e) => setBug(e.target.value)}
                  rows={8}
                  placeholder={'例如：结算时折扣超过 100% 会把总价算成负数，期望总价下限为 0 且保留两位小数。\n复现：apply_discount({"price": 100}, 150) 返回 -50，期望 0.0。'}
                  className="w-full resize-y rounded-lg border border-edge bg-raised px-3 py-2 text-[13px] outline-none placeholder:text-dim/50 focus:border-accentSoft"
                />
              </div>
              {error && <p className="text-[12.5px] text-err">{error}</p>}
              <Button variant="primary" onClick={() => void create()} disabled={busy || !repoId || bug.trim().length < 5}>
                {busy ? <Spinner /> : <FlaskConical size={13} />} 开始复现与修复
              </Button>
            </div>
          </div>
        ) : detail ? (
          <div className="mx-auto max-w-3xl p-5">
            <div className="flex items-center gap-2">
              <h2 className="min-w-0 flex-1 truncate text-[15px] font-semibold" title={detail.title}>
                {detail.title}
              </h2>
              <StatusBadge status={detail.status} />
              <button
                className="flex items-center gap-1 rounded-md border border-edge px-2 py-0.5 text-[11px] text-dim hover:text-ink disabled:opacity-40"
                onClick={() => void runReview()}
                disabled={reviewing || !['ready', 'failed'].includes(detail.status)}
                title="只读审查当前 diff，不会修改文件"
              >
                {reviewing ? <Spinner /> : <ShieldCheck size={11} />} 审查
              </button>
              <button className="text-dim hover:text-ink" onClick={() => setSelectedId(detail.id)} title="刷新">
                <RefreshCw size={13} />
              </button>
            </div>
            <p className="mt-0.5 text-[11.5px] text-dim">
              {detail.repo_name} · {detail.created_at ? new Date(detail.created_at).toLocaleString() : ''}
            </p>

            <section className="mt-3 rounded-lg border border-edge bg-panel/50 p-3">
              <p className="mb-1 text-[11.5px] uppercase tracking-wide text-dim">Bug 描述</p>
              <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed">{detail.bug_report}</p>
            </section>

            {error && <p className="mt-3 text-[12.5px] text-err">{error}</p>}
            {notice && <p className="mt-3 text-[12.5px] text-ok">{notice}</p>}

            <section className="mt-4 space-y-2">
              {latestSteps.map((step, i) => (
                <StepRow key={`${step.step}-${i}`} step={step} />
              ))}
              {detail.status === 'running' && (
                <p className="flex items-center gap-2 px-1 text-[12px] text-dim">
                  <Spinner /> 正在沙箱中执行，请稍候…
                </p>
              )}
            </section>

            {result.error && (
              <p className="mt-3 rounded-lg border border-err/40 bg-err/5 p-3 text-[12.5px] text-err">
                {result.error}
              </p>
            )}

            {result.analysis && (
              <section className="mt-4">
                <h3 className="mb-1 text-[13px] font-medium">根因分析</h3>
                <p className="whitespace-pre-wrap rounded-lg border border-edge bg-panel/40 p-3 text-[12.5px] leading-relaxed text-dim">
                  {result.analysis}
                </p>
              </section>
            )}

            {result.diff && (
              <section className="mt-4">
                <h3 className="mb-1 flex items-center gap-2 text-[13px] font-medium">
                  <ClipboardList size={13} /> 变更预览{result.applied ? '（已应用）' : '（未应用）'}
                </h3>
                <DiffView diff={result.diff} />
              </section>
            )}

            <ReviewPanel review={result.review} />

            {(result.red || result.green) && (
              <section className="mt-4 grid gap-3 md:grid-cols-2">
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

            {status === 'ready' && (
              <section className="mt-4 flex items-center gap-2">
                <Button variant="primary" onClick={() => void act('apply')} disabled={busy}>
                  {busy ? <Spinner /> : <CheckCircle2 size={13} />} 批准并写入仓库
                </Button>
                <Button variant="danger" onClick={() => void act('reject')} disabled={busy}>
                  <XOctagon size={13} /> 拒绝
                </Button>
                <span className="text-[11.5px] text-dim">写入后会自动重建索引</span>
              </section>
            )}

            {status === 'applied' && (
              <p className="mt-4 flex items-center gap-2 text-[12.5px] text-ok">
                <CheckCircle2 size={13} /> 已应用到仓库，索引已开始重建。
              </p>
            )}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-[13px] text-dim">
            选择左侧任务查看详情
          </div>
        )}
      </main>
    </div>
  )
}