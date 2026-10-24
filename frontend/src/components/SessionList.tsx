import clsx from 'clsx'
import {
  MessageSquarePlus, MoreHorizontal, Pencil, Search, Trash2,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import type { Repo, Session } from '../lib/types'
import { Button, Modal } from './common'

function sessionDate(session: Session): Date | null {
  const value = session.updated_at || session.created_at
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function groupLabel(date: Date | null): string {
  if (!date) return '更早'
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today.getTime() - 86400000)
  if (date >= today) return '今天'
  if (date >= yesterday) return '昨天'
  if (date >= new Date(today.getTime() - 6 * 86400000)) return '近 7 天'
  return '更早'
}

function relativeTime(date: Date | null): string {
  if (!date) return ''
  const diff = Date.now() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  return `${date.getMonth() + 1}/${date.getDate()}`
}

export function SessionList({
  sessions,
  projects,
  projectFilter,
  onProjectFilterChange,
  activeId,
  onSelect,
  onNew,
  onDelete,
  onRename,
}: {
  sessions: Session[]
  projects: Repo[]
  projectFilter: string
  onProjectFilterChange: (repoId: string) => void
  activeId: string | null
  onSelect: (id: string) => void
  onNew: () => void
  onDelete: (id: string) => void
  onRename: (id: string, title: string) => void
}) {
  const [search, setSearch] = useState('')
  const repoNames = useMemo(
    () => new Map(projects.map((repo) => [repo.id, repo.name])),
    [projects],
  )
  const projectName = (session: Session) =>
    session.primary_repo_id
      ? repoNames.get(session.primary_repo_id) ?? ''
      : (session.repo_ids ?? []).map((id) => repoNames.get(id)).find(Boolean) ?? ''
  const [menuId, setMenuId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<Session | null>(null)

  const groups = useMemo(() => {
    const keyword = search.trim().toLowerCase()
    const filtered = keyword
      ? sessions.filter((session) => {
          const name = projectName(session)
          return session.title.toLowerCase().includes(keyword)
            || name.toLowerCase().includes(keyword)
        })
      : sessions
    const buckets = new Map<string, Session[]>()
    for (const session of filtered) {
      const label = groupLabel(sessionDate(session))
      const bucket = buckets.get(label) ?? []
      bucket.push(session)
      buckets.set(label, bucket)
    }
    const order = ['今天', '昨天', '近 7 天', '更早']
    return order
      .filter((label) => buckets.has(label))
      .map((label) => ({ label, items: buckets.get(label) as Session[] }))
  }, [sessions, search, repoNames])

  const startRename = (session: Session) => {
    setMenuId(null)
    setRenamingId(session.id)
    setRenameValue(session.title)
  }

  const commitRename = (id: string) => {
    if (renamingId !== id) return
    const title = renameValue.trim()
    setRenamingId(null)
    if (title) onRename(id, title)
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 px-3 pb-2 pt-1">
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-dim">会话</span>
        <span className="rounded bg-raised px-1.5 py-0.5 text-[10px] text-dim">{sessions.length}</span>
        <button
          onClick={onNew}
          className="ml-auto flex h-7 w-7 items-center justify-center rounded-md text-dim transition-colors hover:bg-raised hover:text-ink"
          title="新建对话"
          aria-label="新建对话"
        >
          <MessageSquarePlus size={15} />
        </button>
      </div>

      <div className="px-3 pb-2">
        <select
          value={projectFilter}
          onChange={(event) => onProjectFilterChange(event.target.value)}
          className="mb-2 w-full rounded-md border border-edge bg-base/60 px-2 py-1.5 text-[11.5px] text-dim outline-none focus:border-accentSoft"
          title="按项目筛选会话；新建对话会继承当前项目"
        >
          <option value="">全部项目</option>
          {projects.map((repo) => (
            <option key={repo.id} value={repo.id}>{repo.name}</option>
          ))}
        </select>
        <div className="flex items-center gap-1.5 rounded-md border border-edge bg-base/60 px-2 py-1.5 focus-within:border-accentSoft">
          <Search size={12} className="shrink-0 text-dim" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="搜索会话"
            className="min-w-0 flex-1 bg-transparent text-[11.5px] outline-none placeholder:text-dim/60"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {groups.length === 0 && (
          <div className="px-2 py-6 text-center text-[11.5px] leading-relaxed text-dim">
            {search ? '没有匹配的会话。' : '还没有会话。新建一个对话，或直接开始提问。'}
          </div>
        )}
        {groups.map((group) => (
          <div key={group.label} className="mb-2">
            <p className="px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-dim/70">{group.label}</p>
            {group.items.map((session) => {
              const date = sessionDate(session)
              const active = session.id === activeId
              const renaming = renamingId === session.id
              const project = projectName(session)
              return (
                <div
                  key={session.id}
                  onClick={() => {
                    if (!renaming) onSelect(session.id)
                  }}
                  className={clsx(
                    'group relative mb-0.5 flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 transition-colors',
                    active ? 'bg-accentSoft/35 text-ink' : 'text-dim hover:bg-raised/80 hover:text-ink',
                  )}
                >
                  <span
                    className={clsx(
                      'h-1.5 w-1.5 shrink-0 rounded-full',
                      active ? 'bg-accent' : 'bg-transparent',
                    )}
                  />
                  <div className="min-w-0 flex-1">
                    {renaming ? (
                      <input
                        autoFocus
                        value={renameValue}
                        onChange={(event) => setRenameValue(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            event.preventDefault()
                            commitRename(session.id)
                          } else if (event.key === 'Escape') {
                            setRenamingId(null)
                          }
                        }}
                        onBlur={() => commitRename(session.id)}
                        onClick={(event) => event.stopPropagation()}
                        className="w-full rounded border border-accentSoft bg-base px-1 py-0.5 text-[12px] text-ink outline-none"
                      />
                    ) : (
                      <p className="truncate text-[12.5px]" title={session.title}>{session.title}</p>
                    )}
                    <p className="mt-0.5 flex min-w-0 items-center gap-1 text-[10px] text-dim/70">
                      {project && <span className="truncate text-accent/70">{project}</span>}
                      <span className="shrink-0">{session.message_count} 条</span>
                      {date && <span className="shrink-0">· {relativeTime(date)}</span>}
                    </p>
                  </div>
                  {!renaming && (
                    <button
                      onClick={(event) => {
                        event.stopPropagation()
                        setMenuId((current) => (current === session.id ? null : session.id))
                      }}
                      className={clsx(
                        'flex h-6 w-6 shrink-0 items-center justify-center rounded text-dim/60 transition-colors hover:bg-raised hover:text-ink',
                        menuId === session.id ? 'opacity-100' : 'opacity-0 group-hover:opacity-100',
                      )}
                      aria-label="会话操作"
                    >
                      <MoreHorizontal size={13} />
                    </button>
                  )}

                  {menuId === session.id && (
                    <>
                      <div className="fixed inset-0 z-20" onClick={() => setMenuId(null)} />
                      <div className="absolute right-1 top-8 z-30 w-28 overflow-hidden rounded-lg border border-edge bg-panel py-1 shadow-xl">
                        <button
                          className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11.5px] text-ink hover:bg-raised"
                          onClick={(event) => {
                            event.stopPropagation()
                            startRename(session)
                          }}
                        >
                          <Pencil size={12} /> 重命名
                        </button>
                        <button
                          className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11.5px] text-err hover:bg-err/10"
                          onClick={(event) => {
                            event.stopPropagation()
                            setMenuId(null)
                            setDeleteTarget(session)
                          }}
                        >
                          <Trash2 size={12} /> 删除
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )
            })}
          </div>
        ))}
      </div>

      <Modal
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="删除会话"
        width="max-w-sm"
      >
        <p className="text-[13px] leading-relaxed text-dim">
          确定删除「{deleteTarget?.title}」？消息与轨迹将一并删除，此操作无法撤销。
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button size="sm" onClick={() => setDeleteTarget(null)}>取消</Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() => {
              if (deleteTarget) onDelete(deleteTarget.id)
              setDeleteTarget(null)
            }}
          >
            删除会话
          </Button>
        </div>
      </Modal>
    </div>
  )
}
