import clsx from 'clsx'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { X } from 'lucide-react'

export function Button({
  variant = 'ghost',
  size = 'md',
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
}) {
  return (
    <button
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        size === 'sm' ? 'px-2.5 py-1 text-[12px]' : 'px-3.5 py-1.5 text-[13px]',
        variant === 'primary' && 'bg-accent text-white hover:bg-accent/85',
        variant === 'ghost' && 'border border-edge bg-raised text-ink hover:border-accentSoft hover:bg-panel',
        variant === 'danger' && 'border border-err/40 text-err hover:bg-err/10',
        className,
      )}
      {...rest}
    />
  )
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={clsx(
        'inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-dim/40 border-t-accent',
        className,
      )}
    />
  )
}

export function Badge({ tone = 'dim', children }: { tone?: 'dim' | 'ok' | 'warn' | 'err' | 'accent'; children: ReactNode }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium',
        tone === 'dim' && 'bg-raised text-dim',
        tone === 'ok' && 'bg-ok/15 text-ok',
        tone === 'warn' && 'bg-warn/15 text-warn',
        tone === 'err' && 'bg-err/15 text-err',
        tone === 'accent' && 'bg-accentSoft/60 text-accent',
      )}
    >
      {children}
    </span>
  )
}

export function StatusDot({ state }: { state: 'ok' | 'warn' | 'err' | 'idle' }) {
  return (
    <span
      className={clsx(
        'inline-block h-2 w-2 rounded-full',
        state === 'ok' && 'bg-ok',
        state === 'warn' && 'bg-warn',
        state === 'err' && 'bg-err',
        state === 'idle' && 'bg-dim/50',
      )}
    />
  )
}

export function Modal({
  open,
  onClose,
  title,
  children,
  width = 'max-w-lg',
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  width?: string
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        className={clsx('w-full rounded-xl border border-edge bg-panel shadow-2xl', width)}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-edge px-4 py-3">
          <h3 className="text-[14px] font-semibold">{title}</h3>
          <button className="text-dim hover:text-ink" onClick={onClose} aria-label="关闭">
            <X size={16} />
          </button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  )
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
      <p className="text-[14px] text-ink">{title}</p>
      {hint && <p className="max-w-md text-[12.5px] leading-relaxed text-dim">{hint}</p>}
      {action}
    </div>
  )
}