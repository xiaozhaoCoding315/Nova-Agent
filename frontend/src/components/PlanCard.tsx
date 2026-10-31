import { CheckCircle2, Circle, ListTodo, Loader2 } from 'lucide-react'
import type { PlanState } from '../lib/types'

export function PlanCard({ plan }: { plan: PlanState }) {
  if (!plan.steps?.length) return null
  const completed = plan.steps.filter((step) => step.status === 'completed').length

  return (
    <div className="my-2 rounded-xl border border-edge bg-panel/70 p-3">
      <div className="flex items-center gap-1.5 text-[12px] font-medium text-ink">
        <ListTodo size={13} className="text-accent" />
        <span>执行计划</span>
        <span className="ml-auto font-mono text-[10.5px] text-dim">
          {completed}/{plan.steps.length}
        </span>
      </div>
      {plan.explanation && (
        <p className="mt-1 text-[11.5px] leading-relaxed text-dim">{plan.explanation}</p>
      )}
      <ul className="mt-2 space-y-1.5">
        {plan.steps.map((step, index) => (
          <li key={`${index}-${step.title}`} className="flex items-start gap-2 text-[12px]">
            {step.status === 'completed' ? (
              <CheckCircle2 size={12} className="mt-0.5 shrink-0 text-ok" />
            ) : step.status === 'in_progress' ? (
              <Loader2 size={12} className="mt-0.5 shrink-0 animate-spin text-accent" />
            ) : (
              <Circle size={12} className="mt-0.5 shrink-0 text-dim/60" />
            )}
            <span
              className={
                step.status === 'completed'
                  ? 'text-dim line-through'
                  : step.status === 'in_progress'
                    ? 'text-ink'
                    : 'text-dim'
              }
            >
              {step.title}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
