import { X } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef } from 'react'
import { useRepos } from '../stores/repos'
import type { WorkspaceTab } from '../views/WorkspaceView'

const WorkspaceView = lazy(() =>
  import('../views/WorkspaceView').then((module) => ({ default: module.WorkspaceView })))

/** 右侧工作区抽屉：懒加载 WorkspaceView，Escape / 背景点击关闭，并把焦点还给触发按钮。 */
export function WorkspaceDrawer({
  open,
  repoId,
  path,
  tab = 'code',
  onClose,
}: {
  open: boolean
  repoId?: string
  path?: string
  tab?: WorkspaceTab
  onClose: () => void
}) {
  const repoName = useRepos((state) => state.repos.find((repo) => repo.id === repoId)?.name)
  const closeRef = useRef<HTMLButtonElement>(null)
  const triggerRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (open) {
      triggerRef.current = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
      closeRef.current?.focus()
      return
    }
    const trigger = triggerRef.current
    triggerRef.current = null
    if (trigger && document.contains(trigger)) trigger.focus()
  }, [open])

  // 捕获阶段并检查 defaultPrevented：与 AppShell 的分层 Escape 配合，一次只关一层。
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return
      event.preventDefault()
      onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-black/50"
      onMouseDown={onClose}
      role="presentation"
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-label="工作区"
        className="flex h-full w-[min(1100px,92vw)] flex-col border-l border-edge bg-base shadow-pop"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex h-10 shrink-0 items-center gap-2 border-b border-edge px-2 font-mono">
          <button
            ref={closeRef}
            onClick={onClose}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-dim transition-colors duration-150 hover:bg-raised hover:text-ink"
            title="关闭工作区 · Esc"
            aria-label="关闭工作区"
          >
            <X size={14} />
          </button>
          <span className="shrink-0 text-sm text-dim">工作区</span>
          {repoName && <span className="min-w-0 truncate text-sm text-ink">{repoName}</span>}
          {path && (
            <code className="min-w-0 flex-1 truncate font-mono text-xs text-faint" title={path}>
              {path}
            </code>
          )}
          <span className="ml-auto shrink-0 text-2xs text-faint">Esc 关闭</span>
        </div>
        <div className="min-h-0 flex-1">
          <Suspense
            fallback={(
              <div className="flex h-full items-center justify-center font-mono text-sm text-dim">
                加载中…
              </div>
            )}
          >
            <WorkspaceView
              key={`${repoId ?? 'all'}|${path ?? ''}|${tab}`}
              embedded
              initialRepoId={repoId ?? null}
              initialPath={path ?? null}
              initialTab={tab}
              onClose={onClose}
            />
          </Suspense>
        </div>
      </section>
    </div>
  )
}
