import clsx from 'clsx'
import {
  AlertCircle, CheckCircle2, ChevronDown, ChevronRight, FlaskConical, X, XOctagon,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { DiffView } from '../components/DiffView'
import { ReviewPanel } from '../components/ReviewPanel'
import { Badge, Button, Spinner, StatusDot } from '../components/common'
import type { TaskResult, TaskStep } from '../lib/types'
import { RUN_STATUS } from '../lib/ui'
import { useChat } from '../stores/chat'
import { useRun } from '../stores/run'

const STEP_LABEL: Record<string, string> = {
  locate: '定位相关代码',
  analyze: '生成复现测试与修复',
  red: '红 · 修复前测试应失败',
  green: '绿 · 修复后测试应通过',
  error: '执行出错',
  running: '执行中',
  done: '完成',
  canceled: '已取消',
}

type StepState = 'ok' | 'warn' | 'err' | 'idle'

function stepState(step: TaskStep): StepState {
  if (step.status === 'failed') return 'err'
  if (step.status === 'warn' || step.status === 'running') return 'warn'
  if (step.status === 'done' || step.status === 'ok' || step.status === 'passed') return 'ok'
  return 'idle'
}

function StepRow({ step }: { step: TaskStep }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-edge bg-panel/40 px-2.5 py-2">
      <span className="mt-1.5">
        <StatusDot state={stepState(step)} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm text-ink">{STEP_LABEL[step.step] ?? step.step}</span>
          {step.status === 'running' && <Spinner className="h-3 w-3" />}
          {typeof step.exit_code === 'number' && (
            <code className="ml-auto shrink-0 font-mono text-2xs text-dim">exit {step.exit_code}</code>
          )}
        </div>
        {step.detail && (
          <p className="truncate text-xs text-dim" title={step.detail}>{step.detail}</p>
        )}
        {step.command && (
          <p className="break-all font-mono text-2xs text-faint" title={step.command}>$ {step.command}</p>
        )}
      </div>
    </div>
  )
}

type CommandOutput = Pick<
  NonNullable<TaskResult['red']>,
  'command' | 'exit_code' | 'stdout' | 'stderr'
> & {
  detail?: string
}

function OutputSection({
  label, tone, output,
}: {
  label: string
  tone: 'err' | 'ok'
  output: CommandOutput
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className={clsx('rounded-lg border bg-panel/40', tone === 'err' ? 'border-err/30' : 'border-ok/30')}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-2.5 py-2 text-left"
        aria-expanded={open}
      >
        {open ? <ChevronDown size={12} className="shrink-0 text-dim" /> : <ChevronRight size={12} className="shrink-0 text-dim" />}
        <span className={clsx('min-w-0 flex-1 truncate text-sm', tone === 'err' ? 'text-err' : 'text-ok')}>
          {label}
        </span>
        {typeof output.exit_code === 'number' && (
          <span className="shrink-0 font-mono text-xs text-dim">exit {output.exit_code}</span>
        )}
      </button>
      {open && (
        <div className="space-y-1 border-t border-edge/70 px-2.5 py-2">
          {output.command && (
            <p className="break-all font-mono text-2xs text-dim">$ {output.command}</p>
          )}
          {output.stdout && (
            <pre className="max-h-40 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-xs leading-relaxed text-dim">
              {output.stdout}
            </pre>
          )}
          {output.stderr && (
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-base p-2 font-mono text-xs leading-relaxed text-err">
              {output.stderr}
            </pre>
          )}
          {!output.stdout && !output.stderr && (
            <p className="text-xs text-dim">
              {output.detail || '没有输出。'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

function RecentMenu({
  open, onSelect, onClose,
}: {
  open: boolean
  onSelect: (taskId: string) => void
  onClose: () => void
}) {
  const recent = useRun((state) => state.recent)
  if (!open) return null
  return (
    <>
      <div className="fixed inset-0 z-20" onClick={onClose} aria-hidden="true" />
      <div
        role="menu"
        aria-label="最近任务"
        className="absolute right-0 top-full z-30 mt-1 max-h-72 w-64 overflow-y-auto rounded-lg border border-edge bg-panel p-1 shadow-pop"
      >
        {recent.length === 0 ? (
          <p className="px-2 py-2 text-sm leading-relaxed text-dim">这个项目还没有修复任务。</p>
        ) : (
          recent.map((item) => {
            const meta = RUN_STATUS[item.status] ?? { label: item.status, tone: 'dim' as const }
            return (
              <button
                key={item.id}
                type="button"
                role="menuitem"
                onClick={() => onSelect(item.id)}
                className="block w-full rounded-sm px-2 py-1.5 text-left transition-colors hover:bg-raised"
              >
                <span className="flex items-center gap-1.5">
                  <span className="min-w-0 flex-1 truncate text-sm text-ink">{item.title}</span>
                  <Badge tone={meta.tone}>{meta.label}</Badge>
                </span>
                <span className="mt-0.5 block truncate text-2xs text-dim">
                  {item.repo_name}
                  {item.created_at ? ` · ${new Date(item.created_at).toLocaleString()}` : ''}
                </span>
              </button>
            )
          })
        )}
      </div>
    </>
  )
}

/**
 * `/fix` 运行面板：轮询任务进度，展示红-绿验证、diff、审查与最终写入确认。
 * Task 3 临时挂在 ChatView 右栏，Task 5 会迁移到 ContextRail。
 */
export function RunPanel() {
  const task = useRun((state) => state.task)
  const error = useRun((state) => state.error)
  const close = useRun((state) => state.close)
  const selectedRepoId = useChat((state) => state.selectedRepoIds[0] ?? null)
  const [recentOpen, setRecentOpen] = useState(false)
  const [confirmReject, setConfirmReject] = useState(false)
  const [busy, setBusy] = useState<'apply' | 'reject' | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)

  const repoId = task?.repo_id ?? selectedRepoId

  useEffect(() => {
    void useRun.getState().loadRecent(repoId)
    // 打开面板或任务切换仓库时刷新「最近任务」
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId])

  useEffect(() => {
    setRecentOpen(false)
    setConfirmReject(false)
    setBusy(null)
  }, [task?.id])

  // Esc 逐层收起：最近任务 → 拒绝确认 → 面板（窄屏覆盖层或焦点在面板内时）。
  // 外层 ModelPicker / 斜杠菜单 / 对话框会先 preventDefault，不会被这里误关。
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      if (recentOpen) {
        event.preventDefault()
        setRecentOpen(false)
        return
      }
      if (confirmReject) {
        event.preventDefault()
        setConfirmReject(false)
        return
      }
      const overlay = !window.matchMedia('(min-width: 1024px)').matches
      if (overlay || rootRef.current?.contains(document.activeElement)) {
        event.preventDefault()
        useRun.getState().close()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [recentOpen, confirmReject])

  const act = async (kind: 'apply' | 'reject') => {
    if (busy) return
    setBusy(kind)
    setConfirmReject(false)
    if (kind === 'apply') await useRun.getState().apply()
    else await useRun.getState().reject()
    setBusy(null)
  }

  const restoreTask = (taskId: string) => {
    setRecentOpen(false)
    void useRun.getState().restore(taskId)
  }

  const meta = task ? RUN_STATUS[task.status] ?? { label: task.status, tone: 'dim' as const } : null
  const result: TaskResult = task?.result ?? {}
  // 引擎会为同一阶段先写 running 再写 done，只展示最后一次状态。
  const steps = task
    ? Object.values(task.steps.reduce<Record<string, TaskStep>>((acc, step) => {
        acc[step.step] = step
        return acc
      }, {}))
    : []
  const errorText = error ?? result.error ?? null

  return (
    <div ref={rootRef} className="flex h-full min-h-0 flex-col" aria-label="运行面板">
      <header className="flex h-10 shrink-0 items-center gap-2 border-b border-edge/70 px-3 font-mono">
        <FlaskConical size={13} className="shrink-0 text-accent" />
        <span className="shrink-0 text-sm text-ink">运行 · /fix</span>
        {meta && <Badge tone={meta.tone}>{meta.label}</Badge>}
        <div className="relative ml-auto shrink-0">
          <button
            type="button"
            onClick={() => setRecentOpen((value) => !value)}
            className="flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-dim transition-colors hover:bg-raised hover:text-ink"
            aria-haspopup="menu"
            aria-expanded={recentOpen}
          >
            最近任务 <ChevronDown size={10} />
          </button>
          <RecentMenu open={recentOpen} onSelect={restoreTask} onClose={() => setRecentOpen(false)} />
        </div>
        <button
          type="button"
          onClick={close}
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-dim/70 transition-colors hover:bg-raised hover:text-ink"
          title="关闭运行面板"
          aria-label="关闭运行面板"
        >
          <X size={13} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {errorText && (
          <div className="mb-3 flex items-start gap-2 rounded-lg border border-err/40 bg-err/10 px-2.5 py-2 text-sm text-err">
            <AlertCircle size={12} className="mt-0.5 shrink-0" />
            <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{errorText}</span>
          </div>
        )}

        {!task ? (
          <div className="px-2 py-10 text-center">
            <FlaskConical size={18} className="mx-auto text-dim" />
            <p className="mt-2 text-base text-ink">还没有运行中的任务</p>
            <p className="mx-auto mt-1 max-w-[260px] text-xs leading-relaxed text-dim">
              在输入框输入 <code className="font-mono text-accent">/fix 描述问题</code>，
              Nova 会先写失败测试复现，再修复到测试通过。
            </p>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <h2 className="text-base font-medium leading-snug text-ink" title={task.title}>{task.title}</h2>
              <p className="mt-0.5 text-xs text-dim">
                {task.repo_name}
                {task.created_at ? ` · ${new Date(task.created_at).toLocaleString()}` : ''}
              </p>
            </div>

            {(steps.length > 0 || task.status === 'running' || task.status === 'queued') && (
              <section className="space-y-1.5">
                {steps.length > 0 && (
                  <h3 className="text-xs uppercase tracking-[0.12em] text-dim">步骤</h3>
                )}
                {steps.map((step, index) => <StepRow key={`${step.step}-${index}`} step={step} />)}
                {(task.status === 'running' || task.status === 'queued') && (
                  <p className="flex items-center gap-2 px-1 pt-0.5 text-xs text-dim">
                    <Spinner /> 正在沙箱中执行，请稍候…
                  </p>
                )}
              </section>
            )}

            {(result.red || result.green) && (
              <section className="space-y-1.5">
                <h3 className="text-xs uppercase tracking-[0.12em] text-dim">红-绿验证</h3>
                {result.red && (
                  <OutputSection label="红 · 修复前测试失败" tone="err" output={result.red} />
                )}
                {result.green && (
                  <OutputSection label="绿 · 修复后测试通过" tone="ok" output={result.green} />
                )}
              </section>
            )}

            {result.diff && (
              <section>
                <h3 className="mb-1 text-xs uppercase tracking-[0.12em] text-dim">
                  变更预览{result.applied ? '（已应用）' : ''}
                </h3>
                <DiffView diff={result.diff} maxHeight="max-h-64" />
              </section>
            )}

            {result.review && <ReviewPanel review={result.review} />}

            {task.status === 'ready' && (
              <section className="space-y-2 border-t border-edge/70 pt-3">
                {!confirmReject ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button variant="primary" onClick={() => void act('apply')} disabled={busy != null}>
                      {busy === 'apply' ? <Spinner /> : <CheckCircle2 size={13} />} 应用补丁
                    </Button>
                    <Button variant="danger" onClick={() => setConfirmReject(true)} disabled={busy != null}>
                      <XOctagon size={13} /> 拒绝
                    </Button>
                    <span className="text-xs text-dim">应用后自动更新项目分析</span>
                  </div>
                ) : (
                  <div className="rounded-lg border border-err/40 bg-err/5 p-2.5">
                    <p className="text-sm leading-relaxed text-err">确认拒绝这次修复？不会写入任何文件。</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Button variant="danger" onClick={() => void act('reject')} disabled={busy != null}>
                        {busy === 'reject' ? <Spinner /> : <XOctagon size={13} />} 确认拒绝
                      </Button>
                      <Button onClick={() => setConfirmReject(false)} disabled={busy != null}>取消</Button>
                    </div>
                  </div>
                )}
              </section>
            )}

            {task.status === 'applied' && (
              <p className="flex items-center gap-2 text-sm text-ok">
                <CheckCircle2 size={13} /> 已写入项目，代码阅读正在更新。
              </p>
            )}
            {task.status === 'rejected' && (
              <p className="flex items-center gap-2 text-sm text-dim">
                <XOctagon size={13} /> 已拒绝该修复，仓库未改动。
              </p>
            )}
            {task.status === 'failed' && !errorText && (
              <p className="flex items-center gap-2 text-sm text-err">
                <AlertCircle size={13} /> 任务失败，请重新发起或查看最近任务。
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
