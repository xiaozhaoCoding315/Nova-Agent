import clsx from 'clsx'
import {
  CheckCircle2, ChevronDown, ClipboardList, FileDiff, FlaskConical, GitPullRequest, ListTodo,
  Moon, Play, Plus, RefreshCw, ShieldCheck, XCircle, XOctagon,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { DiffView } from '../components/DiffView'
import { NightQueuePanel } from '../components/NightQueuePanel'
import { ReviewPanel } from '../components/ReviewPanel'
import { Badge, Button, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { Change, ChangeListItem, Job, Task, TaskListItem, TaskStep } from '../lib/types'
import { useRepos } from '../stores/repos'

/**
 * 统一任务视图：修复任务（红-绿）与变更（方案→计划→验证）共用一个列表与详情，
 * 用户只描述「要做什么」，不用先理解两条流水线的差别。
 */

type Bucket = 'running' | 'review' | 'done' | 'closed' | 'failed'

const CHANGE_BUCKET: Record<string, Bucket> = {
  drafting: 'running', planning: 'running', executing: 'running',
  draft: 'review', plan_ready: 'review', plan_approved: 'review', review: 'review',
  applied: 'done', rejected: 'closed', canceled: 'closed', failed: 'failed',
}

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

const CHANGE_ACTIVE = new Set(['drafting', 'planning', 'executing'])

/** 自动分流：命中关键词走修复（红-绿），否则走变更（方案→计划）。 */
const FIX_RE = /报错|错误|异常|修复|修好|修一下|崩溃|挂了|崩了|bug|traceback|exception|stack ?trace|复现/i

type Kind = 'auto' | 'fix' | 'change'

const KIND_OPTIONS: { key: Kind; label: string; hint: string }[] = [
  { key: 'auto', label: '自动', hint: '根据描述选择' },
  { key: 'fix', label: '修 Bug', hint: '失败测试复现 → 最小补丁 → 跑绿' },
  { key: 'change', label: '新功能 / 重构', hint: '方案与计划 → 逐任务真实验证 → 统一 diff' },
]

type UnifiedItem = {
  key: string
  kind: 'change' | 'task'
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

function mergeItems(changes: ChangeListItem[], tasks: TaskListItem[]): UnifiedItem[] {
  const items: UnifiedItem[] = [
    ...changes.map((c) => ({
      key: `change-${c.id}`,
      kind: 'change' as const,
      id: c.id,
      title: c.title,
      bucket: CHANGE_BUCKET[c.status] ?? 'running',
      repoName: c.repo_name,
      time: c.updated_at ?? c.created_at ?? '',
      meta: `v${c.version} · ${c.task_count} 个任务`,
      error: c.error,
    })),
    ...tasks.map((t) => ({
      key: `task-${t.id}`,
      kind: 'task' as const,
      id: t.id,
      title: t.title,
      bucket: TASK_BUCKET[t.status] ?? 'running',
      repoName: t.repo_name,
      time: t.created_at ?? '',
      meta: '修复任务',
    })),
  ]
  return items.sort((a, b) => timestamp(b.time) - timestamp(a.time))
}

function BucketBadge({ bucket }: { bucket: Bucket }) {
  const meta = BUCKET_META[bucket]
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

function Section({
  title, icon, right, defaultOpen = false, children,
}: {
  title: string
  icon?: React.ReactNode
  right?: React.ReactNode
  defaultOpen?: boolean
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="rounded-xl border border-edge bg-panel/60">
      <button
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left"
        onClick={() => setOpen((value) => !value)}
      >
        {icon}
        <h3 className="text-[13px] font-semibold">{title}</h3>
        <div className="ml-auto flex items-center gap-2" onClick={(e) => e.stopPropagation()}>{right}</div>
        <ChevronDown size={14} className={clsx('shrink-0 text-dim transition-transform', open && 'rotate-180')} />
      </button>
      {open && <div className="space-y-3 border-t border-edge px-4 py-3">{children}</div>}
    </section>
  )
}

function JobBar({ job, onCancel }: { job: Job | null; onCancel: () => void }) {
  if (!job) return null
  const pct = Math.round((job.progress || 0) * 100)
  const running = job.status === 'running' || job.status === 'queued'
  return (
    <div className="rounded-lg border border-edge bg-base/60 px-3 py-2">
      <div className="flex items-center gap-2 text-[11.5px]">
        {running ? <Spinner /> : job.status === 'succeeded'
          ? <CheckCircle2 size={13} className="text-ok" />
          : <XCircle size={13} className="text-err" />}
        <span className="font-mono text-dim">{job.kind}</span>
        <span className="text-dim">{job.step || job.status}</span>
        <span className="ml-auto font-mono text-dim">{pct}%</span>
        {running && <Button size="sm" variant="danger" onClick={onCancel}>取消</Button>}
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded bg-raised">
        <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
      </div>
      {job.error && <p className="mt-1 text-[11px] text-err">{job.error}</p>}
    </div>
  )
}

/* ---------------- SPEC（方案）编辑 ---------------- */

const FIELD = 'w-full rounded-md border border-edge bg-base px-2.5 py-1.5 text-[12px] outline-none focus:border-accent'

function asLines(items: string[] | undefined): string {
  return (items ?? []).join('\n')
}

function fromLines(value: string): string[] {
  return value.split('\n').map((item) => item.trim()).filter(Boolean)
}

function SpecEditor({
  change, busy, onSave, onCommit,
}: {
  change: Change
  busy: string
  onSave: (patch: Record<string, unknown>) => void
  onCommit: (patch: Record<string, unknown>) => void
}) {
  const [title, setTitle] = useState(change.title)
  const [goal, setGoal] = useState(change.goal)
  const [acceptance, setAcceptance] = useState(asLines(change.acceptance_cases))
  const [advanced, setAdvanced] = useState(false)
  const [inScope, setInScope] = useState(asLines(change.in_scope))
  const [outScope, setOutScope] = useState(asLines(change.out_scope))
  const [interfaces, setInterfaces] = useState(asLines(change.interfaces))
  const [nfr, setNfr] = useState(asLines(change.nfr))
  const [questions, setQuestions] = useState(asLines(change.open_questions))

  useEffect(() => {
    setTitle(change.title)
    setGoal(change.goal)
    setAcceptance(asLines(change.acceptance_cases))
    setInScope(asLines(change.in_scope))
    setOutScope(asLines(change.out_scope))
    setInterfaces(asLines(change.interfaces))
    setNfr(asLines(change.nfr))
    setQuestions(asLines(change.open_questions))
  }, [change])

  const editing = change.status === 'draft' || change.status === 'failed'
  const specPatch = () => ({
    title, goal,
    in_scope: fromLines(inScope), out_scope: fromLines(outScope),
    interfaces: fromLines(interfaces), acceptance_cases: fromLines(acceptance),
    nfr: fromLines(nfr), open_questions: fromLines(questions),
  })
  return (
    <div className="space-y-3">
      {change.status === 'drafting' ? (
        <p className="flex items-center gap-2 text-[12.5px] text-dim">
          <Spinner /> 正在根据你的描述起草方案，稍等片刻即可编辑…
        </p>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="space-y-1 text-[11.5px] text-dim">
              标题
              <input className={FIELD} value={title} onChange={(e) => setTitle(e.target.value)} disabled={!editing} />
            </label>
            <label className="space-y-1 text-[11.5px] text-dim">
              验收用例（每行一条，必须可判定）
              <textarea className={clsx(FIELD, 'min-h-20')} value={acceptance} onChange={(e) => setAcceptance(e.target.value)} disabled={!editing} />
            </label>
          </div>
          <label className="block space-y-1 text-[11.5px] text-dim">
            目标
            <textarea className={clsx(FIELD, 'min-h-16')} value={goal} onChange={(e) => setGoal(e.target.value)} disabled={!editing} />
          </label>
          <button
            className="text-[11.5px] text-dim underline-offset-2 hover:text-ink hover:underline"
            onClick={() => setAdvanced(!advanced)}
          >
            {advanced ? '收起高级字段' : '展开高级字段（范围 / 接口 / 待澄清）'}
          </button>
          {advanced && (
            <div className="grid gap-3 md:grid-cols-2">
              <label className="space-y-1 text-[11.5px] text-dim">
                In 范围（每行一条路径或前缀）
                <textarea className={clsx(FIELD, 'min-h-16 font-mono')} value={inScope} onChange={(e) => setInScope(e.target.value)} disabled={!editing} />
              </label>
              <label className="space-y-1 text-[11.5px] text-dim">
                Out 范围
                <textarea className={clsx(FIELD, 'min-h-16 font-mono')} value={outScope} onChange={(e) => setOutScope(e.target.value)} disabled={!editing} />
              </label>
              <label className="space-y-1 text-[11.5px] text-dim">
                接口 / 契约
                <textarea className={clsx(FIELD, 'min-h-16')} value={interfaces} onChange={(e) => setInterfaces(e.target.value)} disabled={!editing} />
              </label>
              <label className="space-y-1 text-[11.5px] text-dim">
                非功能要求
                <textarea className={clsx(FIELD, 'min-h-16')} value={nfr} onChange={(e) => setNfr(e.target.value)} disabled={!editing} />
              </label>
              <label className="space-y-1 text-[11.5px] text-dim md:col-span-2">
                待澄清问题（必须清空才能冻结方案）
                <textarea className={clsx(FIELD, 'min-h-16')} value={questions} onChange={(e) => setQuestions(e.target.value)} disabled={!editing} />
              </label>
            </div>
          )}
          {editing && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => onSave(specPatch())} disabled={Boolean(busy)}>
                保存修改
              </Button>
              <Button size="sm" variant="primary" onClick={() => onCommit(specPatch())} disabled={Boolean(busy) || questions.trim().length > 0}>
                <ShieldCheck size={12} /> 冻结方案并生成计划
              </Button>
              {questions.trim().length > 0 && (
                <span className="self-center text-[11px] text-dim">还有待澄清问题未清空</span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

/* ---------------- 变更详情 ---------------- */

function ChangeDetail({
  changeId, onError, onChanged,
}: {
  changeId: string
  onError: (message: string | null) => void
  onChanged: () => void
}) {
  const [detail, setDetail] = useState<Change | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [busy, setBusy] = useState('')

  const load = async () => {
    try {
      const next = await api.changes.get(changeId)
      setDetail(next)
      onError(null)
    } catch (err) {
      onError(err instanceof ApiError ? err.message : '加载变更失败')
    }
  }

  useEffect(() => {
    let alive = true
    void load()
    // 仅在后台任务执行中轮询；草稿态轮询会覆盖用户正在编辑的方案。
    if (!detail || !CHANGE_ACTIVE.has(detail.status)) {
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
  }, [changeId, detail?.status])

  useEffect(() => {
    if (!detail?.job_id) {
      setJob(null)
      return
    }
    let alive = true
    const poll = async () => {
      try {
        const next = await api.jobs.get(detail.job_id as string)
        if (alive) setJob(next)
      } catch {
        /* job may be gone */
      }
    }
    void poll()
    const timer = setInterval(poll, 1500)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [detail?.job_id])

  const run = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label)
    onError(null)
    try {
      await action()
      await load()
      onChanged()
    } catch (err) {
      onError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setBusy('')
    }
  }

  if (!detail) {
    return (
      <div className="flex h-full items-center justify-center text-[12.5px] text-dim">
        <Spinner /> 加载中…
      </div>
    )
  }

  const status = detail.status
  const active = CHANGE_ACTIVE.has(status)
  const proposal = detail.proposal

  return (
    <div className="mx-auto max-w-4xl space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <GitPullRequest size={15} className="shrink-0 text-accent" />
        <h2 className="min-w-0 flex-1 truncate text-[16px] font-semibold">{detail.title}</h2>
        <BucketBadge bucket={CHANGE_BUCKET[status] ?? 'running'} />
        <span className="text-[11px] text-dim">v{detail.version} · {detail.repo_name}</span>
        {active && (
          <Button size="sm" variant="danger" onClick={() => void run('cancel', () => api.changes.cancel(detail.id))}>
            取消
          </Button>
        )}
        <Button size="sm" onClick={() => void load()}>
          <RefreshCw size={12} /> 刷新
        </Button>
      </div>
      {detail.error && (
        <div className="rounded-lg border border-err/30 bg-err/10 px-3 py-2 text-[12px] text-err">{detail.error}</div>
      )}
      <JobBar job={job} onCancel={() => void run('cancel', () => api.changes.cancel(detail.id))} />

      <Section
        title="方案"
        icon={<ClipboardList size={13} className="text-accent" />}
        defaultOpen={['drafting', 'draft', 'failed'].includes(status)}
        right={<Badge tone={['drafting', 'draft', 'failed'].includes(status) ? 'warn' : 'ok'}>{['drafting', 'draft', 'failed'].includes(status) ? '可编辑' : '已冻结'}</Badge>}
      >
        {['drafting', 'draft', 'failed'].includes(status) ? (
          <SpecEditor
            change={detail}
            busy={busy}
            onSave={(patch) => void run('save', () => api.changes.update(detail.id, patch))}
            onCommit={(patch) => void run('approve', async () => {
              await api.changes.update(detail.id, patch)
              await api.changes.approve(detail.id)
              await api.changes.plan(detail.id)
            })}
          />
        ) : (
          <div className="space-y-2 text-[12px]">
            <p><span className="text-dim">目标：</span>{detail.goal || '—'}</p>
            <div className="grid gap-2 md:grid-cols-2">
              <div><p className="text-dim">In 范围</p><p className="font-mono">{detail.in_scope.join('，') || '—'}</p></div>
              <div><p className="text-dim">Out 范围</p><p className="font-mono">{detail.out_scope.join('，') || '—'}</p></div>
            </div>
            <div>
              <p className="text-dim">验收</p>
              <ul className="list-disc pl-4">{detail.acceptance_cases.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          </div>
        )}
        {status === 'approved' && (
          <Button size="sm" variant="primary" onClick={() => void run('plan', () => api.changes.plan(detail.id))} disabled={Boolean(busy)}>
            {busy === 'plan' ? <Spinner /> : <ListTodo size={12} />} 生成执行计划
          </Button>
        )}
        {status === 'planning' && <p className="flex items-center gap-2 text-[12px] text-dim"><Spinner /> 正在生成计划…</p>}
      </Section>

      {detail.tasks.length > 0 && (
        <Section
          title={`执行计划 · ${detail.tasks.length} 个任务`}
          icon={<ListTodo size={13} className="text-accent" />}
          defaultOpen={['plan_ready', 'plan_approved', 'executing'].includes(status)}
          right={<span className="text-[11px] text-dim">每个任务都要跑过真实验证门</span>}
        >
          {detail.plan_notes && <p className="text-[12px] text-dim">{detail.plan_notes}</p>}
          <div className="space-y-1.5">
            {detail.tasks.map((task) => (
              <div key={task.id} className="rounded-lg border border-edge bg-base/50 px-2.5 py-2">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] text-dim">#{task.seq}</span>
                  <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium">{task.title}</span>
                  {task.status === 'ready'
                    ? <CheckCircle2 size={12} className="text-ok" />
                    : task.status === 'running'
                      ? <Spinner />
                      : <XCircle size={12} className={task.status === 'failed' ? 'text-err' : 'text-dim/50'} />}
                  {task.attempts > 0 && <span className="text-[10.5px] text-dim">重试 {task.attempts}</span>}
                </div>
                <p className="mt-1 text-[11.5px] text-dim">{task.acceptance}</p>
                {task.result?.files?.length ? (
                  <p className="mt-0.5 truncate font-mono text-[10.5px] text-dim">改动：{task.result.files.join('，')}</p>
                ) : null}
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {status === 'plan_ready' && (
              <Button
                size="sm"
                variant="primary"
                onClick={() => void run('plan-approve', async () => {
                  await api.changes.approvePlan(detail.id)
                  await api.changes.execute(detail.id)
                })}
                disabled={Boolean(busy)}
              >
                {busy === 'plan-approve' ? <Spinner /> : <Play size={12} />} 批准并开始执行
              </Button>
            )}
            {status === 'plan_approved' && (
              <Button size="sm" variant="primary" onClick={() => void run('execute', () => api.changes.execute(detail.id))} disabled={Boolean(busy)}>
                <Play size={12} /> 开始执行
              </Button>
            )}
            {status === 'failed' && detail.tasks.length > 0 && (
              <Button size="sm" onClick={() => void run('execute', () => api.changes.execute(detail.id))} disabled={Boolean(busy)}>
                <RefreshCw size={12} /> 从失败处重试
              </Button>
            )}
            {status === 'executing' && <span className="flex items-center gap-2 text-[12px] text-dim"><Spinner /> 正在执行，进度见上方…</span>}
          </div>
        </Section>
      )}

      {proposal?.edit_id && (
        <Section
          title="变更与验证"
          icon={<FileDiff size={13} className="text-accent" />}
          defaultOpen={status === 'review'}
          right={
            <>
              {proposal.gate && (
                <Badge tone={proposal.gate.status === 'passed' ? 'ok' : 'warn'}>
                  验证{proposal.gate.status === 'passed' ? '通过' : '未通过'}
                </Badge>
              )}
              <Badge tone="dim">{proposal.files?.length ?? 0} 个文件</Badge>
            </>
          }
        >
          <ReviewPanel review={proposal.review} />
          {proposal.gate?.steps?.length ? (
            <div className="space-y-1">
              {proposal.gate.steps.map((step, index) => (
                <div key={`${step.name}-${index}`} className="flex items-center gap-2 text-[11.5px]">
                  {step.status === 'passed'
                    ? <CheckCircle2 size={12} className="text-ok" />
                    : <XCircle size={12} className="text-err" />}
                  <span className="font-mono">{step.name}</span>
                  <span className="min-w-0 flex-1 truncate text-dim">{step.command}</span>
                  <span className="ml-auto font-mono text-dim">exit {step.exit_code}</span>
                </div>
              ))}
            </div>
          ) : null}
          <p className="flex items-center gap-2 text-[11.5px] text-dim"><FileDiff size={13} /> 统一 diff</p>
          <DiffView diff={proposal.diff || ''} maxHeight="max-h-80" />
          {status === 'review' && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="primary" onClick={() => void run('apply', () => api.changes.apply(detail.id))} disabled={Boolean(busy)}>
                {busy === 'apply' ? <Spinner /> : <CheckCircle2 size={12} />} 批准并写入仓库
              </Button>
              <Button size="sm" variant="danger" onClick={() => void run('reject', () => api.changes.reject(detail.id))} disabled={Boolean(busy)}>
                <XOctagon size={12} /> 拒绝
              </Button>
            </div>
          )}
        </Section>
      )}

      {detail.evidence?.summary && (
        <Section
          title="交付证据"
          defaultOpen={status === 'applied'}
          right={<Badge tone={status === 'applied' ? 'ok' : 'warn'}>{BUCKET_META[CHANGE_BUCKET[status] ?? 'running'].label}</Badge>}
        >
          <p className="text-[12px]">{detail.evidence.summary}</p>
          {detail.evidence.unverified?.length ? (
            <p className="text-[11.5px] text-warn">未验证：{detail.evidence.unverified.join('；')}</p>
          ) : null}
          {detail.evidence.commit && <p className="font-mono text-[11px] text-dim">commit {detail.evidence.commit}</p>}
          {detail.evidence.branch && <p className="font-mono text-[11px] text-dim">分支 {detail.evidence.branch}</p>}
        </Section>
      )}
    </div>
  )
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
  const [changes, setChanges] = useState<ChangeListItem[]>([])
  const [tasks, setTasks] = useState<TaskListItem[]>([])
  const [filter, setFilter] = useState<'all' | Bucket>('all')
  const [selected, setSelected] = useState<UnifiedItem | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [repoId, setRepoId] = useState(initialRepoId ?? '')
  const [description, setDescription] = useState('')
  const [kind, setKind] = useState<Kind>('auto')
  const [creating, setCreating] = useState(false)
  const [nightOpen, setNightOpen] = useState(false)

  const readyRepos = repos.filter((repo) => repo.status === 'ready')

  const items = useMemo(() => mergeItems(changes, tasks), [changes, tasks])
  const filtered = filter === 'all' ? items : items.filter((item) => item.bucket === filter)
  const counts = useMemo(() => {
    const map: Record<string, number> = { all: items.length }
    for (const item of items) map[item.bucket] = (map[item.bucket] ?? 0) + 1
    return map
  }, [items])

  const loadLists = async () => {
    const [changeList, taskList] = await Promise.all([
      api.changes.list().catch(() => [] as ChangeListItem[]),
      api.tasks.list().catch(() => [] as TaskListItem[]),
    ])
    setChanges(changeList)
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

  const detected: 'fix' | 'change' = kind === 'auto'
    ? (FIX_RE.test(description) ? 'fix' : 'change')
    : kind === 'fix' ? 'fix' : 'change'

  const create = async () => {
    if (!repoId || description.trim().length < 5) {
      setError('请选择项目，并描述至少 5 个字')
      return
    }
    setCreating(true)
    setError(null)
    try {
      if (detected === 'fix') {
        const task = await api.tasks.create(repoId, description.trim())
        setSelected({
          key: `task-${task.id}`, kind: 'task', id: task.id, title: task.title,
          bucket: 'running', repoName: task.repo_name, time: task.created_at ?? '', meta: '修复任务',
        })
      } else {
        const change = await api.changes.create(repoId, description.trim())
        setSelected({
          key: `change-${change.id}`, kind: 'change', id: change.id, title: change.title,
          bucket: 'running', repoName: change.repo_name, time: change.created_at ?? '', meta: `v${change.version}`,
        })
      }
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
          <span className="text-[12.5px] font-medium">把一件事交给 Nova 完成，过程中的验证与写入都由你确认</span>
          <span className="hidden text-[11px] text-dim md:inline">
            修 Bug 会先写失败测试复现（红）再修复跑到通过（绿）；新功能 / 重构会先给方案与计划，逐任务过真实验证，最后统一 diff 等你批准。
          </span>
          {onBackToChat && (
            <button
              onClick={onBackToChat}
              className="ml-auto flex items-center gap-1 rounded-lg border border-edge/80 px-2.5 py-1.5 text-[11px] text-dim transition-colors hover:text-ink"
            >
              回到对话
            </button>
          )}
          <button
            onClick={() => setNightOpen(!nightOpen)}
            className={clsx(
              'flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] transition-colors',
              nightOpen ? 'border-accent/60 bg-accentSoft/30 text-ink' : 'border-edge/80 text-dim hover:text-ink',
            )}
            title="睡前排队，夜间窗口内自动执行，早上看报告批准"
          >
            <Moon size={12} className={nightOpen ? 'text-accent' : ''} /> 夜间队列
          </button>
        </div>
      </div>

      {nightOpen && (
        <div className="max-h-[45%] shrink-0 overflow-y-auto px-4 py-3">
          <NightQueuePanel repos={repos} />
        </div>
      )}

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
              placeholder="描述要做的事：例如「结算时折扣超过 100% 会把总价算成负数」或「给用户列表加分页和筛选」"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
            <div className="flex items-center gap-1.5">
              <div className="flex flex-1 rounded-lg border border-edge/80 bg-base/40 p-0.5">
                {KIND_OPTIONS.map(({ key, label }) => (
                  <button
                    key={key}
                    onClick={() => setKind(key)}
                    className={clsx(
                      'flex-1 rounded-md px-1.5 py-1 text-[11px] transition-colors',
                      kind === key ? 'bg-accentSoft/45 text-ink' : 'text-dim hover:text-ink',
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <Button size="sm" variant="primary" onClick={() => void create()} disabled={creating || !repoId || description.trim().length < 5}>
                {creating ? <Spinner /> : <Plus size={12} />} 创建
              </Button>
            </div>
            <p className="text-[10.5px] leading-relaxed text-dim/80">
              {KIND_OPTIONS.find((option) => option.key === kind)?.hint}
              {kind === 'auto' && description.trim().length > 3 && (
                <span className="ml-1 text-accent/80">（当前将创建：{detected === 'fix' ? '修复任务' : '变更'}）</span>
              )}
            </p>
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
                还没有任务。在上方描述一件事，创建后 Nova 会自动推进，关键节点停下来等你确认。
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
                  {item.kind === 'task'
                    ? <FlaskConical size={11} className="shrink-0 text-dim" />
                    : <GitPullRequest size={11} className="shrink-0 text-dim" />}
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
          {selected?.kind === 'change' && (
            <ChangeDetail
              key={selected.key}
              changeId={selected.id}
              onError={setError}
              onChanged={() => void loadLists()}
            />
          )}
          {selected?.kind === 'task' && (
            <FixDetail
              key={selected.key}
              taskId={selected.id}
              onError={setError}
              onChanged={() => void loadLists()}
            />
          )}
          {!selected && (
            <div className="flex h-full items-center justify-center px-6 text-center text-[12.5px] leading-relaxed text-dim">
              从左侧选择一个任务，或在上方描述一件要做的事。<br />
              小改动和问答直接回「对话」即可，不用建任务。
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
