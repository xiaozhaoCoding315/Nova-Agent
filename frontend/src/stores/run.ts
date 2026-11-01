import { create } from 'zustand'
import { api, ApiError } from '../lib/api'
import type { Task, TaskListItem } from '../lib/types'
import { useChat } from './chat'
import { useRepos } from './repos'

type RunState = {
  taskId: string | null
  task: Task | null
  recent: TaskListItem[]
  open: boolean
  error: string | null
  start: (task: Task) => void
  restore: (taskId: string) => Promise<void>
  refresh: () => Promise<void>
  loadRecent: (repoId?: string | null) => Promise<void>
  apply: () => Promise<void>
  reject: () => Promise<void>
  close: () => void
  reset: () => void
}

const POLL_INTERVAL = 1500
const MAX_POLL_FAILURES = 5
const RUN_PREFIX = 'nova.run.'

let pollTimer: ReturnType<typeof setInterval> | null = null
let pollFailures = 0
/** 同一时刻只允许一个轮询请求；手动刷新与轮询共用这个令牌。 */
let refreshInFlight = false
/** 递增令牌让晚到的响应失效（切换任务、关闭面板或换会话后不得回写）。 */
let refreshGeneration = 0

function isActive(status: string | undefined | null): boolean {
  return status === 'running' || status === 'queued'
}

function stopPolling() {
  if (pollTimer != null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  pollFailures = 0
  refreshGeneration += 1
  refreshInFlight = false
}

/** 账号切换时清掉所有运行记录，避免把上一账号的任务带进新账号。 */
export function clearStoredRuns(): void {
  try {
    const keys: string[] = []
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index)
      if (key?.startsWith(RUN_PREFIX)) keys.push(key)
    }
    for (const key of keys) localStorage.removeItem(key)
  } catch {
    /* localStorage 不可用时没有持久化记录可清 */
  }
}

function timestamp(value?: string | null): number {
  if (!value) return 0
  const time = new Date(value).getTime()
  return Number.isNaN(time) ? 0 : time
}

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

/** `nova.run.<sessionId|new>`：每个会话记住自己最近一次运行的任务。 */
export function runStorageKey(sessionId: string | null = useChat.getState().sessionId): string {
  return `nova.run.${sessionId ?? 'new'}`
}

export function readStoredRun(sessionId: string | null = useChat.getState().sessionId): string | null {
  return readStored(runStorageKey(sessionId))
}

export function writeStoredRun(sessionId: string | null, taskId: string | null): void {
  try {
    if (taskId) localStorage.setItem(runStorageKey(sessionId), taskId)
    else localStorage.removeItem(runStorageKey(sessionId))
  } catch {
    /* localStorage 不可用时只是失去刷新后的恢复能力 */
  }
}

function errorText(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

export const useRun = create<RunState>((set, get) => {
  const schedulePolling = () => {
    if (pollTimer != null) return
    pollTimer = setInterval(() => {
      if (refreshInFlight) return
      void get().refresh()
    }, POLL_INTERVAL)
  }

  return {
    taskId: null,
    task: null,
    recent: [],
    open: false,
    error: null,

    start: (task) => {
      stopPolling()
      set({ taskId: task.id, task, open: true, error: null })
      writeStoredRun(useChat.getState().sessionId, task.id)
      if (isActive(task.status)) schedulePolling()
    },

    restore: async (taskId) => {
      stopPolling()
      set({ taskId, task: null, open: true, error: null })
      const sessionId = useChat.getState().sessionId
      const requestId = ++refreshGeneration
      refreshInFlight = true
      try {
        const task = await api.tasks.get(taskId)
        if (
          requestId !== refreshGeneration
          || get().taskId !== taskId
          || useChat.getState().sessionId !== sessionId
        ) return
        set({ task, error: null })
        if (isActive(task.status)) schedulePolling()
      } catch (err) {
        if (
          requestId !== refreshGeneration
          || get().taskId !== taskId
          || useChat.getState().sessionId !== sessionId
        ) return
        // 只清理发起本次恢复的会话 key，绝不误删刚切换到的另一个会话。
        writeStoredRun(sessionId, null)
        set({ taskId: null, task: null, error: errorText(err, '加载修复任务失败') })
      } finally {
        if (requestId === refreshGeneration) refreshInFlight = false
      }
    },

    refresh: async () => {
      const taskId = get().taskId
      // 面板关闭后不再刷新；重新打开由入口先置 open=true 再调用 refresh。
      if (!taskId || !get().open) return
      const sessionId = useChat.getState().sessionId
      const before = get().task
      const requestId = ++refreshGeneration
      refreshInFlight = true
      try {
        const task = await api.tasks.get(taskId)
        if (
          requestId !== refreshGeneration
          || get().taskId !== taskId
          || useChat.getState().sessionId !== sessionId
        ) return
        pollFailures = 0
        set({ task, error: null })
        if (isActive(task.status)) {
          schedulePolling()
        } else {
          stopPolling()
          // 轮询从运行态结束时，补丁可能刚写入仓库：刷新一次项目状态与索引。
          if (before && isActive(before.status)) void useRepos.getState().refresh()
        }
      } catch (err) {
        if (
          requestId !== refreshGeneration
          || get().taskId !== taskId
          || useChat.getState().sessionId !== sessionId
        ) return
        pollFailures += 1
        set({ error: errorText(err, '刷新修复任务失败') })
        if (pollFailures >= MAX_POLL_FAILURES) stopPolling()
      } finally {
        if (requestId === refreshGeneration) refreshInFlight = false
      }
    },

    loadRecent: async (repoId) => {
      try {
        const list = await api.tasks.list()
        const filtered = repoId ? list.filter((item) => item.repo_id === repoId) : list
        filtered.sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at))
        set({ recent: filtered.slice(0, 10) })
      } catch {
        /* 最近任务只是辅助入口，失败不打扰主流程 */
      }
    },

    apply: async () => {
      const taskId = get().taskId
      if (!taskId) return
      set({ error: null })
      try {
        await api.tasks.apply(taskId)
        if (get().taskId !== taskId) return
        await get().refresh()
        await useRepos.getState().refresh()
        await get().loadRecent(get().task?.repo_id ?? null)
      } catch (err) {
        if (get().taskId !== taskId) return
        set({ error: errorText(err, '应用补丁失败') })
      }
    },

    reject: async () => {
      const taskId = get().taskId
      if (!taskId) return
      set({ error: null })
      try {
        await api.tasks.reject(taskId)
        if (get().taskId !== taskId) return
        await get().refresh()
        await useRepos.getState().refresh()
        await get().loadRecent(get().task?.repo_id ?? null)
      } catch (err) {
        if (get().taskId !== taskId) return
        set({ error: errorText(err, '拒绝修复失败') })
      }
    },

    close: () => {
      // 关闭面板后不再轮询；重新打开时会主动 refresh 并恢复轮询。
      stopPolling()
      set({ open: false })
    },

    reset: () => {
      stopPolling()
      writeStoredRun(useChat.getState().sessionId, null)
      set({ taskId: null, task: null, recent: [], open: false, error: null })
    },
  }
})
