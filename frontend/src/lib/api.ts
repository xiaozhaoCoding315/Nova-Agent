import type {
  Brain, BuilderPlanResponse, BuilderProposalResponse, Change, ChangeListItem, EditRecord,
  FileNode, GitInfo, Health, Impact, Job, Message, Repo, Review, Session, Task, TaskListItem,
  TraceEvent, Usage, User, VerifyResult,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api/v1${path}`, { credentials: 'include', ...options })
  } catch {
    throw new ApiError(0, '网络连接失败，请检查服务是否可用')
  }
  if (!res.ok) {
    let detail = `请求失败（${res.status}）`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* keep default */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

function json(body: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }
}

export const api = {
  login: (username: string, password: string) => request<User>('/auth/login', json({ username, password })),
  logout: () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  me: () => request<User>('/auth/me'),

  sessions: {
    list: () => request<Session[]>('/chat/sessions'),
    create: () => request<Session>('/chat/sessions', { method: 'POST' }),
    messages: (id: string) => request<Message[]>(`/chat/sessions/${id}/messages`),
    remove: (id: string) => request<{ ok: boolean }>(`/chat/sessions/${id}`, { method: 'DELETE' }),
  },

  repos: {
    list: () => request<Repo[]>('/repos'),
    get: (id: string) => request<Repo>(`/repos/${id}`),
    remove: (id: string) => request<{ ok: boolean }>(`/repos/${id}`, { method: 'DELETE' }),
    reindex: (id: string) => request<{ ok: boolean }>(`/repos/${id}/reindex`, { method: 'POST' }),
    tree: (id: string) => request<FileNode[]>(`/repos/${id}/tree`),
    file: (id: string, path: string) =>
      request<{ path: string; language: string; line_count: number; content: string }>(
        `/repos/${id}/file?path=${encodeURIComponent(path)}`,
      ),
    search: (id: string, q: string) =>
      request<{ symbols: unknown[]; hits: unknown[] }>(`/repos/${id}/search?q=${encodeURIComponent(q)}`),
    brain: (id: string) => request<Brain>(`/repos/${id}/brain`),
    impact: (id: string, q: string, depth = 2) =>
      request<Impact>(`/repos/${id}/impact?q=${encodeURIComponent(q)}&depth=${depth}`),
    upload: async (file: File): Promise<Repo> => {
      const form = new FormData()
      form.append('file', file)
      return request<Repo>('/repos/upload', { method: 'POST', body: form })
    },
    importGit: (gitUrl: string, name?: string) => request<Repo>('/repos/git', json({ git_url: gitUrl, name })),
    createBuilder: (name: string, requirements: string, rules?: string) =>
      request<Repo>('/repos/builder', json({ name, requirements, rules })),
    getPlan: (id: string) => request<BuilderPlanResponse>(`/repos/${id}/plan`),
    regeneratePlan: (id: string) =>
      request<{ ok: boolean }>(`/repos/${id}/plan/generate`, { method: 'POST' }),
    approvePlan: (id: string) =>
      request<{ ok: boolean }>(`/repos/${id}/plan/approve`, { method: 'POST' }),
    generate: (id: string, feedback?: string) =>
      request<{ ok: boolean }>(`/repos/${id}/generate`, json({ feedback: feedback ?? null })),
    getProposal: (id: string) => request<BuilderProposalResponse>(`/repos/${id}/proposal`),
    approveProposal: (id: string) =>
      request<{ ok: boolean; applied: string[] }>(`/repos/${id}/proposal/approve`, { method: 'POST' }),
    rejectProposal: (id: string) =>
      request<{ ok: boolean }>(`/repos/${id}/proposal/reject`, { method: 'POST' }),
    verify: (id: string) =>
      request<VerifyResult>(`/repos/${id}/verify`, { method: 'POST' }),
    lastVerify: (id: string) => request<Partial<VerifyResult>>(`/repos/${id}/verify`),
    exportUrl: (id: string) => `/api/v1/repos/${id}/export`,
  },

  status: {
    health: () => request<Health>('/status/health'),
    usage: () => request<Usage>('/status/usage'),
  },

  tasks: {
    list: () => request<TaskListItem[]>('/tasks'),
    create: (repoId: string, bugReport: string, title?: string) =>
      request<Task>('/tasks', json({ repo_id: repoId, bug_report: bugReport, title })),
    get: (id: string) => request<Task>(`/tasks/${id}`),
    apply: (id: string) =>
      request<{ ok: boolean; applied: string[]; reindex_started: boolean }>(`/tasks/${id}/apply`, {
        method: 'POST',
      }),
    reject: (id: string) => request<{ ok: boolean }>(`/tasks/${id}/reject`, { method: 'POST' }),
    review: (id: string) => request<Review>(`/tasks/${id}/review`, { method: 'POST' }),
  },

  changes: {
    list: () => request<ChangeListItem[]>('/changes'),
    get: (id: string) => request<Change>(`/changes/${id}`),
    create: (repoId: string, requirements: string, title?: string) =>
      request<Change>('/changes', json({ repo_id: repoId, requirements, title })),
    update: (id: string, patch: Record<string, unknown>) =>
      request<Change>(`/changes/${id}`, { ...json(patch), method: 'PATCH' }),
    draft: (id: string) => request<{ ok: boolean; job_id: string }>(`/changes/${id}/draft`, { method: 'POST' }),
    approve: (id: string) => request<Change>(`/changes/${id}/approve`, { method: 'POST' }),
    plan: (id: string) => request<{ ok: boolean; job_id: string }>(`/changes/${id}/plan`, { method: 'POST' }),
    approvePlan: (id: string) => request<Change>(`/changes/${id}/plan/approve`, { method: 'POST' }),
    execute: (id: string) => request<{ ok: boolean; job_id: string }>(`/changes/${id}/execute`, { method: 'POST' }),
    apply: (id: string, force = false) =>
      request<{ ok: boolean; applied: string[]; commit?: string | null }>(
        `/changes/${id}/apply`, json({ force }),
      ),
    reject: (id: string) => request<{ ok: boolean }>(`/changes/${id}/reject`, { method: 'POST' }),
    cancel: (id: string) => request<{ ok: boolean }>(`/changes/${id}/cancel`, { method: 'POST' }),
  },

  jobs: {
    list: () => request<Job[]>('/jobs'),
    get: (id: string) => request<Job>(`/jobs/${id}`),
    cancel: (id: string) => request<Job>(`/jobs/${id}/cancel`, { method: 'POST' }),
    retry: (id: string) => request<Job>(`/jobs/${id}/retry`, { method: 'POST' }),
  },

  edits: {
    get: (id: string) => request<EditRecord>(`/edits/${id}`),
    approve: (id: string) =>
      request<{ ok: boolean; applied: string[] }>(`/edits/${id}/approve`, { method: 'POST' }),
    reject: (id: string) => request<{ ok: boolean }>(`/edits/${id}/reject`, { method: 'POST' }),
    revert: (id: string) =>
      request<{ ok: boolean; restored: string[]; removed: string[] }>(`/edits/${id}/revert`, {
        method: 'POST',
      }),
    review: (id: string) => request<Review>(`/edits/${id}/review`, { method: 'POST' }),
  },

  git: {
    status: (id: string) => request<GitInfo>(`/repos/${id}/git`),
    init: (id: string) => request<GitInfo>(`/repos/${id}/git/init`, { method: 'POST' }),
    commit: (id: string, message?: string) =>
      request<GitInfo>(`/repos/${id}/git/commit`, json({ message })),
    diff: (id: string) => request<{ diff: string }>(`/repos/${id}/git/diff`),
    rollback: (id: string, commit: string) =>
      request<GitInfo & { reindex_started: boolean }>(`/repos/${id}/git/rollback`, json({ commit })),
  },

  trajectory: (sessionId: string) =>
    request<TraceEvent[]>(`/chat/sessions/${sessionId}/trajectory`),
}