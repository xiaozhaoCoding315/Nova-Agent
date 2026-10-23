import clsx from 'clsx'
import {
  ArrowRight, CheckCircle2, FileDiff, GitPullRequest, ListChecks, Play, Plus,
  RefreshCw, ShieldCheck, XCircle,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { DiffView } from '../components/DiffView'
import { ReviewPanel } from '../components/ReviewPanel'
import { Badge, Button, Spinner } from '../components/common'
import { api, ApiError } from '../lib/api'
import type { Change, ChangeListItem, Job } from '../lib/types'
import { useRepos } from '../stores/repos'

const STATUS_META: Record<string, { label: string; tone: 'dim' | 'ok' | 'warn' | 'err' | 'accent' }> = {
  drafting: { label: '起草 SPEC', tone: 'warn' },
  draft: { label: '待确认 SPEC', tone: 'accent' },
  approved: { label: 'SPEC 已冻结', tone: 'accent' },
  planning: { label: '规划中', tone: 'warn' },
  plan_ready: { label: '待批准计划', tone: 'accent' },
  plan_approved: { label: '计划已批准', tone: 'accent' },
  executing: { label: '执行中', tone: 'warn' },
  review: { label: '待审阅提案', tone: 'accent' },
  applied: { label: '已应用', tone: 'ok' },
  rejected: { label: '已拒绝', tone: 'dim' },
  failed: { label: '失败', tone: 'err' },
  canceled: { label: '已取消', tone: 'dim' },
}

const ACTIVE = new Set(['drafting', 'planning', 'executing'])

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { label: status, tone: 'dim' as const }
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

function asLines(items: string[] | undefined): string {
  return (items ?? []).join('\n')
}

function fromLines(value: string): string[] {
  return value.split('\n').map((item) => item.trim()).filter(Boolean)
}

function Panel({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-edge bg-panel/60">
      <div className="flex items-center gap-2 border-b border-edge px-4 py-2.5">
        <h3 className="text-[13px] font-semibold">{title}</h3>
        <div className="ml-auto flex items-center gap-2">{right}</div>
      </div>
      <div className="space-y-3 px-4 py-3">{children}</div>
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
        {running && (
          <Button size="sm" variant="danger" onClick={onCancel}>取消</Button>
        )}
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded bg-raised">
        <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
      </div>
      {job.error && <p className="mt-1 text-[11px] text-err">{job.error}</p>}
    </div>
  )
}

function SpecEditor({
  change, busy, onSave, onApprove,
}: {
  change: Change
  busy: string
  onSave: (patch: Record<string, unknown>) => void
  onApprove: () => void
}) {
  const [title, setTitle] = useState(change.title)
  const [goal, setGoal] = useState(change.goal)
  const [inScope, setInScope] = useState(asLines(change.in_scope))
  const [outScope, setOutScope] = useState(asLines(change.out_scope))
  const [interfaces, setInterfaces] = useState(asLines(change.interfaces))
  const [acceptance, setAcceptance] = useState(asLines(change.acceptance_cases))
  const [nfr, setNfr] = useState(asLines(change.nfr))
  const [questions, setQuestions] = useState(asLines(change.open_questions))

  useEffect(() => {
    setTitle(change.title)
    setGoal(change.goal)
    setInScope(asLines(change.in_scope))
    setOutScope(asLines(change.out_scope))
    setInterfaces(asLines(change.interfaces))
    setAcceptance(asLines(change.acceptance_cases))
    setNfr(asLines(change.nfr))
    setQuestions(asLines(change.open_questions))
  }, [change])

  const field = 'w-full rounded-md border border-edge bg-base px-2.5 py-1.5 text-[12px] outline-none focus:border-accent'

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-2">
        <label className="space-y-1 text-[11.5px] text-dim">
          标题
          <input className={field} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="space-y-1 text-[11.5px] text-dim">
          验收用例（每行一条，必须可判定）
          <textarea className={clsx(field, 'min-h-20')} value={acceptance} onChange={(e) => setAcceptance(e.target.value)} />
        </label>
      </div>
      <label className="block space-y-1 text-[11.5px] text-dim">
        目标
        <textarea className={clsx(field, 'min-h-20')} value={goal} onChange={(e) => setGoal(e.target.value)} />
      </label>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="space-y-1 text-[11.5px] text-dim">
          In 范围（每行一条路径或前缀）
          <textarea className={clsx(field, 'min-h-20 font-mono')} value={inScope} onChange={(e) => setInScope(e.target.value)} />
        </label>
        <label className="space-y-1 text-[11.5px] text-dim">
          Out 范围
          <textarea className={clsx(field, 'min-h-20 font-mono')} value={outScope} onChange={(e) => setOutScope(e.target.value)} />
        </label>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="space-y-1 text-[11.5px] text-dim">
          接口 / 契约
          <textarea className={clsx(field, 'min-h-16')} value={interfaces} onChange={(e) => setInterfaces(e.target.value)} />
        </label>
        <label className="space-y-1 text-[11.5px] text-dim">
          非功能要求
          <textarea className={clsx(field, 'min-h-16')} value={nfr} onChange={(e) => setNfr(e.target.value)} />
        </label>
      </div>
      <label className="block space-y-1 text-[11.5px] text-dim">
        待澄清问题（必须清空才能冻结 SPEC）
        <textarea className={clsx(field, 'min-h-16')} value={questions} onChange={(e) => setQuestions(e.target.value)} />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button
          size="sm"
          onClick={() => onSave({
            title, goal,
            in_scope: fromLines(inScope), out_scope: fromLines(outScope),
            interfaces: fromLines(interfaces), acceptance_cases: fromLines(acceptance),
            nfr: fromLines(nfr), open_questions: fromLines(questions),
          })}
          disabled={Boolean(busy)}
        >
          保存 SPEC
        </Button>
        <Button size="sm" variant="primary" onClick={onApprove} disabled={Boolean(busy)}>
          <ShieldCheck size={12} /> 冻结 SPEC
        </Button>
      </div>
    </div>
  )
}

export function ChangesView({ initialRepoId }: { initialRepoId?: string } = {}) {
  const { repos, refresh: refreshRepos } = useRepos()
  const [items, setItems] = useState<ChangeListItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<Change | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [repoId, setRepoId] = useState(initialRepoId ?? '')
  const [title, setTitle] = useState('')
  const [requirements, setRequirements] = useState('')

  const readyRepos = repos.filter((repo) => repo.status === 'ready')

  const loadList = async () => {
    try {
      const list = await api.changes.list()
      setItems(list)
      if (!selectedId && list.length > 0) setSelectedId(list[0].id)
    } catch {
      /* non-fatal */
    }
  }

  const loadDetail = async (id: string) => {
    try {
      const next = await api.changes.get(id)
      setDetail(next)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载变更失败')
    }
  }

  useEffect(() => {
    void refreshRepos()
    void loadList()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!detail) return
    setRepoId(detail.repo_id)
  }, [detail])

  useEffect(() => {
    if (repoId || readyRepos.length === 0) return
    setRepoId(readyRepos[0].id)
  }, [readyRepos, repoId])

  useEffect(() => {
    if (!selectedId) return
    let alive = true
    const tick = async () => {
      if (!alive) return
      await loadDetail(selectedId)
    }
    void tick()
    // Only poll while a background job is active; polling a draft would
    // overwrite the user's in-progress SPEC edits.
    if (!detail || !ACTIVE.has(detail.status)) {
      return () => {
        alive = false
      }
    }
    const timer = setInterval(tick, 2500)
    return () => {
      alive = false
      clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, detail?.status])

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
    setError(null)
    try {
      await action()
      if (selectedId) await loadDetail(selectedId)
      await loadList()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失败')
    } finally {
      setBusy('')
    }
  }

  const create = async () => {
    if (!repoId || requirements.trim().length < 10) {
      setError('请选择已就绪仓库，并填写至少 10 个字的需求')
      return
    }
    await run('create', async () => {
      const change = await api.changes.create(repoId, requirements.trim(), title.trim() || undefined)
      setSelectedId(change.id)
      setDetail(change)
      setRequirements('')
      setTitle('')
    })
  }

  const active = detail ? ACTIVE.has(detail.status) : false

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-80 shrink-0 flex-col border-r border-edge bg-panel/40">
        <div className="space-y-2 border-b border-edge p-3">
          <div className="flex items-center gap-2">
            <GitPullRequest size={14} className="text-accent" />
            <span className="text-[13px] font-semibold">新建变更</span>
          </div>
          <select
            className="w-full rounded-md border border-edge bg-base px-2 py-1.5 text-[12px]"
            value={repoId}
            onChange={(e) => setRepoId(e.target.value)}
          >
            <option value="">选择已就绪仓库</option>
            {readyRepos.map((repo) => (
              <option key={repo.id} value={repo.id}>{repo.name}</option>
            ))}
          </select>
          <input
            className="w-full rounded-md border border-edge bg-base px-2 py-1.5 text-[12px]"
            placeholder="标题（可选）"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            className="min-h-24 w-full rounded-md border border-edge bg-base px-2 py-1.5 text-[12px]"
            placeholder="描述需求：目标、输入输出、异常分支、验收方式…"
            value={requirements}
            onChange={(e) => setRequirements(e.target.value)}
          />
          <Button size="sm" variant="primary" onClick={() => void create()} disabled={Boolean(busy)}>
            {busy === 'create' ? <Spinner /> : <Plus size={12} />} 创建并起草 SPEC
          </Button>
        </div>

        <div className="flex-1 overflow-auto p-2">
          {items.length === 0 && <p className="px-2 py-4 text-[12px] text-dim">还没有变更。</p>}
          {items.map((item) => (
            <button
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              className={clsx(
                'mb-1 w-full rounded-lg border px-2.5 py-2 text-left transition-colors',
                selectedId === item.id
                  ? 'border-accentSoft bg-accentSoft/20'
                  : 'border-transparent hover:border-edge hover:bg-raised',
              )}
            >
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium">{item.title}</span>
                <StatusBadge status={item.status} />
              </div>
              <p className="mt-0.5 truncate text-[11px] text-dim">
                {item.repo_name} · v{item.version} · {item.task_count} 个任务
              </p>
              {item.error && <p className="mt-0.5 truncate text-[11px] text-err">{item.error}</p>}
            </button>
          ))}
        </div>
      </aside>

      <div className="min-w-0 flex-1 overflow-auto p-4">
        {error && (
          <div className="mb-3 rounded-lg border border-err/30 bg-err/10 px-3 py-2 text-[12px] text-err">
            {error}
          </div>
        )}
        {!detail ? (
          <div className="flex h-full items-center justify-center text-[12.5px] text-dim">
            创建一个变更，或从左侧选择已有变更。
          </div>
        ) : (
          <div className="mx-auto max-w-4xl space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[16px] font-semibold">{detail.title}</h2>
              <StatusBadge status={detail.status} />
              <span className="text-[11px] text-dim">v{detail.version} · {detail.repo_name}</span>
              <div className="ml-auto flex gap-2">
                {active && (
                  <Button size="sm" variant="danger" onClick={() => void run('cancel', () => api.changes.cancel(detail.id))}>
                    取消任务
                  </Button>
                )}
                <Button size="sm" onClick={() => void loadDetail(detail.id)}>
                  <RefreshCw size={12} /> 刷新
                </Button>
              </div>
            </div>
            {detail.error && (
              <div className="rounded-lg border border-err/30 bg-err/10 px-3 py-2 text-[12px] text-err">
                {detail.error}
              </div>
            )}
            <JobBar
              job={job}
              onCancel={() => void run('cancel', () => api.changes.cancel(detail.id))}
            />

            <Panel
              title="1 · SPEC"
              right={<StatusBadge status={detail.status === 'drafting' ? 'drafting' : detail.status === 'draft' ? 'draft' : 'approved'} />}
            >
              {detail.status === 'draft' || detail.status === 'failed' || detail.status === 'drafting' ? (
                <SpecEditor
                  change={detail}
                  busy={busy}
                  onSave={(patch) => void run('save', () => api.changes.update(detail.id, patch))}
                  onApprove={() => void run('approve', () => api.changes.approve(detail.id))}
                />
              ) : (
                <div className="space-y-2 text-[12px]">
                  <p><span className="text-dim">目标：</span>{detail.goal}</p>
                  <div className="grid gap-2 md:grid-cols-2">
                    <div><p className="text-dim">In</p><p className="font-mono">{detail.in_scope.join('，') || '—'}</p></div>
                    <div><p className="text-dim">Out</p><p className="font-mono">{detail.out_scope.join('，') || '—'}</p></div>
                  </div>
                  <div><p className="text-dim">验收</p><ul className="list-disc pl-4">{detail.acceptance_cases.map((item) => <li key={item}>{item}</li>)}</ul></div>
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                {detail.status === 'approved' && (
                  <Button size="sm" variant="primary" onClick={() => void run('plan', () => api.changes.plan(detail.id))}>
                    <ListChecks size={12} /> 生成计划
                  </Button>
                )}
                {(detail.status === 'planning') && <span className="text-[12px] text-dim">正在生成计划…</span>}
              </div>
            </Panel>

            {detail.tasks.length > 0 && (
              <Panel
                title="2 · 计划与验收"
                right={<span className="text-[11px] text-dim">{detail.tasks.length} 个任务 · 串行</span>}
              >
                {detail.plan_notes && <p className="text-[12px] text-dim">{detail.plan_notes}</p>}
                <div className="space-y-1.5">
                  {detail.tasks.map((task) => (
                    <div key={task.id} className="rounded-lg border border-edge bg-base/50 px-2.5 py-2">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px] text-dim">#{task.seq}</span>
                        <span className="text-[12.5px] font-medium">{task.title}</span>
                        <Badge tone="dim">{task.kind}</Badge>
                        <Badge
                          tone={task.status === 'ready' ? 'ok' : task.status === 'failed' ? 'err' : task.status === 'running' ? 'warn' : 'dim'}
                        >
                          {task.status}
                        </Badge>
                        {task.attempts > 0 && <span className="text-[10.5px] text-dim">尝试 {task.attempts}</span>}
                      </div>
                      <p className="mt-1 text-[11.5px] text-dim">验收：{task.acceptance}</p>
                      {task.result?.files?.length ? (
                        <p className="mt-0.5 font-mono text-[10.5px] text-dim">改动：{task.result.files.join('，')}</p>
                      ) : null}
                      {task.result?.gate?.status && (
                        <p className={clsx(
                          'mt-0.5 text-[10.5px]',
                          task.result.gate.status === 'passed' ? 'text-ok' : 'text-warn',
                        )}>
                          Gate：{task.result.gate.status}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2">
                  {detail.status === 'plan_ready' && (
                    <Button size="sm" variant="primary" onClick={() => void run('plan-approve', () => api.changes.approvePlan(detail.id))}>
                      <CheckCircle2 size={12} /> 批准计划
                    </Button>
                  )}
                  {detail.status === 'plan_approved' && (
                    <Button size="sm" variant="primary" onClick={() => void run('execute', () => api.changes.execute(detail.id))}>
                      <Play size={12} /> 执行计划
                    </Button>
                  )}
                  {detail.status === 'failed' && detail.tasks.length > 0 && (
                    <Button size="sm" onClick={() => void run('execute', () => api.changes.execute(detail.id))}>
                      <RefreshCw size={12} /> 重新执行
                    </Button>
                  )}
                  {detail.status === 'executing' && <span className="text-[12px] text-dim">正在执行，见上方进度…</span>}
                </div>
              </Panel>
            )}

            {detail.proposal?.edit_id && (
              <Panel
                title="3 · Gate / 审查 / 提案"
                right={
                  <>
                    {detail.proposal.gate && (
                      <Badge tone={detail.proposal.gate.status === 'passed' ? 'ok' : 'warn'}>
                        Gate {detail.proposal.gate.status}
                      </Badge>
                    )}
                    <Badge tone="dim">{detail.proposal.files?.length ?? 0} 个文件</Badge>
                  </>
                }
              >
                <ReviewPanel review={detail.proposal.review} />
                {detail.proposal.gate?.steps?.length ? (
                  <div className="space-y-1">
                    {detail.proposal.gate.steps.map((step, index) => (
                      <div key={`${step.name}-${index}`} className="flex items-center gap-2 text-[11.5px]">
                        {step.status === 'passed'
                          ? <CheckCircle2 size={12} className="text-ok" />
                          : <XCircle size={12} className="text-err" />}
                        <span className="font-mono">{step.name}</span>
                        <span className="text-dim">{step.command}</span>
                        <span className="ml-auto font-mono text-dim">exit {step.exit_code}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="flex items-center gap-2 text-[11.5px] text-dim">
                  <FileDiff size={13} /> 统一 diff
                </div>
                <DiffView diff={detail.proposal.diff || ''} maxHeight="max-h-80" />
                <div className="flex flex-wrap gap-2">
                  {detail.status === 'review' && (
                    <>
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={() => void run('apply', () => api.changes.apply(detail.id))}
                      >
                        批准并应用
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => void run('reject', () => api.changes.reject(detail.id))}
                      >
                        拒绝
                      </Button>
                    </>
                  )}
                </div>
              </Panel>
            )}

            {detail.evidence?.summary && (
              <Panel title="4 · 交付证据" right={<Badge tone={detail.status === 'applied' ? 'ok' : 'warn'}>{detail.status}</Badge>}>
                <p className="text-[12px]">{detail.evidence.summary}</p>
                {detail.evidence.unverified?.length ? (
                  <p className="text-[11.5px] text-warn">未验证：{detail.evidence.unverified.join('；')}</p>
                ) : null}
                {detail.evidence.commit && (
                  <p className="font-mono text-[11px] text-dim">commit {detail.evidence.commit}</p>
                )}
                {detail.evidence.branch && (
                  <p className="font-mono text-[11px] text-dim">分支 {detail.evidence.branch}</p>
                )}
                <div className="flex items-center gap-1.5 text-[11.5px] text-dim">
                  <ArrowRight size={12} />
                  {detail.evidence.applied ? '已写入仓库并触发重新索引' : '等待批准后写入仓库'}
                </div>
              </Panel>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
