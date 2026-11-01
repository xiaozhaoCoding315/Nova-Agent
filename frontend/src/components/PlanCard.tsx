import clsx from 'clsx'
import type { PlanState } from '../lib/types'

/** 终端任务清单：步骤前缀 `[x] [~] [ ]`，完成项删除线。 */
export function PlanCard({ plan }: { plan: PlanState }) {
  if (!plan.steps?.length) return null
  const completed = plan.steps.filter((step) => step.status === 'completed').length

  return (
    <div className="overflow-hidden rounded-md border border-edge bg-panel/60">
      <div className="flex h-8 items-center gap-2 px-2.5">
        <span className="text-sm text-ink">计划</span>
        <span className="ml-auto font-mono text-2xs text-faint">
          {completed}/{plan.steps.length}
        </span>
      </div>
      <div className="border-t border-edge/60 px-2.5 py-2">
        {plan.explanation && (
          <p className="mb-1.5 text-xs leading-relaxed text-dim">{plan.explanation}</p>
        )}
        <ul className="space-y-1 font-mono text-xs leading-relaxed">
          {plan.steps.map((step, index) => (
            <li key={`${index}-${step.title}`} className="flex items-start gap-2">
              <span
                className={clsx(
                  'shrink-0',
                  step.status === 'completed' && 'text-faint',
                  step.status === 'in_progress' && 'text-accent',
                  step.status === 'pending' && 'text-faint',
                )}
              >
                {step.status === 'completed' ? '[x]' : step.status === 'in_progress' ? '[~]' : '[ ]'}
              </span>
              <span
                className={clsx(
                  'min-w-0',
                  step.status === 'completed'
                    ? 'text-faint line-through'
                    : step.status === 'in_progress'
                      ? 'text-ink'
                      : 'text-dim',
                )}
              >
                {step.title}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
