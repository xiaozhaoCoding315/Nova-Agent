import type {
  AdminQuotaPatch, AdminUser, AuthConfig, Brain, BuilderPlanResponse, BuilderProposalResponse,
  Change, ChangeListItem, ContractStatus, DebtReport, DebtSnapshot, Deployment, EditRecord,
  FileAttachment, FileList, FileNode, GitInfo, Health, Impact, Job, LlmSettings, LlmSettingsInput,
  LlmTestResult, Memory, Message, Metrics, NightItem, RegisterResult, Repo, Review, SelfQuota,
  Session, Task, TaskListItem, TraceEvent, Usage, User, VerifyResult,
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
  authConfig: () => request<AuthConfig>('/auth/config'),
  login: (username: string, password: string) => request<User>('/auth/login', json({ username, password })),
  register: (username: string, password: string, displayName?: string, inviteCode?: string) =>
    request<RegisterResult>('/auth/register', json({
      username, password, display_name: displayName || null, invite_code: inviteCode || null,
    })),
  guest: () => request<User>('/auth/guest', { method: 'POST' }),
  logout: () => request<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  me: () => request<User>('/auth/me'),
  updateProfile: (displayName: string) =>
    request<User>('/auth/profile', { ...json({ display_name: displayName }), method: 'PATCH' }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<User>('/auth/password', json({ current_password: currentPassword, new_password: newPassword })),
  resetPassword: (username: string, recoveryCode: string, newPassword: string) =>
    request<{ ok: boolean }>('/auth/password/reset', json({
      username, recovery_code: recoveryCode, new_password: newPassword,
    })),

  admin: {
    users: () => request<AdminUser[]>('/admin/users'),
    usageSources: (days = 7) =>
      request<{ source: string; model: string; calls: number; tokens: number }[]>(
        `/admin/usage/sources?days=${days}`,
      ),
    createUser: (username: string, password: string, displayName?: string, role: 'admin' | 'demo' = 'demo') =>
      request<User>('/admin/users', json({ username, password, display_name: displayName || null, role })),
    updateUser: (id: number, patch: AdminQuotaPatch) =>
      request<User>(`/admin/users/${id}`, { ...json(patch), method: 'PATCH' }),
    resetPassword: (id: number, newPassword: string) =>
      request<{ ok: boolean }>(`/admin/users/${id}/password`, json({ new_password: newPassword })),
    removeUser: (id: number) =>
      request<{ ok: boolean }>(`/admin/users/${id}`, { method: 'DELETE' }),
  },

  quota: {
    get: () => request<SelfQuota>('/settings/quota'),
    update: (values: {
      self_daily_tokens?: number | null
      self_hourly_messages?: number | null
      self_sandbox_daily?: number | null
    }) => request<SelfQuota>('/settings/quota', { ...json(values), method: 'PUT' }),
  },

  night: {
    list: () => request<NightItem[]>('/night-queue'),
    add: (body: {
      kind: 'change_execute' | 'task' | 'chat' | 'builder'
      change_id?: string
      repo_id?: string
      bug_report?: string
      content?: string
      session_id?: string
      repo_ids?: string[]
      name?: string
      requirements?: string
      stack?: 'python' | 'fullstack'
    }) => request<NightItem>('/night-queue', json(body)),
    cancel: (id: string) => request<{ ok: boolean }>(`/night-queue/${id}`, { method: 'DELETE' }),
  },

  sessions: {
    list: (repoId?: string) =>
      request<Session[]>(`/chat/sessions${repoId ? `?repo_id=${encodeURIComponent(repoId)}` : ''}`),
    create: (repoIds: string[] = []) => request<Session>('/chat/sessions', json({ repo_ids: repoIds })),
    messages: (id: string) => request<Message[]>(`/chat/sessions/${id}/messages`),
    rename: (id: string, title: string) =>
      request<Session>(`/chat/sessions/${id}`, { ...json({ title }), method: 'PATCH' }),
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
    debt: (id: string) => request<DebtReport>(`/repos/${id}/debt`),
    debtScan: (id: string) => request<DebtSnapshot>(`/repos/${id}/debt/scan`, { method: 'POST' }),
    impact: (id: string, q: string, depth = 2) =>
      request<Impact>(`/repos/${id}/impact?q=${encodeURIComponent(q)}&depth=${depth}`),
    upload: async (file: File): Promise<Repo> => {
      const form = new FormData()
      form.append('file', file)
      return request<Repo>('/repos/upload', { method: 'POST', body: form })
    },
    importGit: (gitUrl: string, name?: string) => request<Repo>('/repos/git', json({ git_url: gitUrl, name })),
    createBuilder: (name: string, requirements: string, rules?: string, stack: 'python' | 'fullstack' = 'python') =>
      request<Repo>('/repos/builder', json({ name, requirements, rules, stack })),
    designChat: (messages: { role: 'user' | 'assistant'; content: string }[], stack: 'python' | 'fullstack') =>
      request<{ reply: string }>('/repos/builder/design', json({ messages, stack })),
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
      request<{ ok: boolean; job_id: string }>(`/repos/${id}/verify`, { method: 'POST' }),
    lastVerify: (id: string) => request<VerifyResult | null>(`/repos/${id}/verify`),
    contract: (id: string) => request<ContractStatus>(`/repos/${id}/contract`),
    exportUrl: (id: string) => `/api/v1/repos/${id}/export`,
  },

  status: {
    health: () => request<Health>('/status/health'),
    usage: () => request<Usage>('/status/usage'),
    metrics: (days = 7) => request<Metrics>(`/status/metrics?days=${days}`),
  },

  files: {
    list: (params: { repoId?: string; sessionId?: string } = {}) => {
      const query = new URLSearchParams()
      if (params.repoId) query.set('repo_id', params.repoId)
      if (params.sessionId) query.set('session_id', params.sessionId)
      const suffix = query.toString()
      return request<FileList>(`/files${suffix ? `?${suffix}` : ''}`)
    },
    upload: (file: File, options: { repoId?: string; sessionId?: string; purpose?: string } = {}) => {
      const form = new FormData()
      form.append('file', file)
      if (options.repoId) form.append('repo_id', options.repoId)
      if (options.sessionId) form.append('session_id', options.sessionId)
      form.append('purpose', options.purpose ?? 'attachment')
      return request<FileAttachment>('/files', { method: 'POST', body: form })
    },
    downloadUrl: (id: string) => `/api/v1/files/${id}/download`,
    remove: (id: string) => request<{ ok: boolean }>(`/files/${id}`, { method: 'DELETE' }),
  },

  llm: {
    get: () => request<LlmSettings>('/settings/llm'),
    save: (input: LlmSettingsInput) =>
      request<LlmSettings>('/settings/llm', { ...json(input), method: 'PUT' }),
    clear: () => request<LlmSettings>('/settings/llm', { method: 'DELETE' }),
    test: (input: LlmSettingsInput) =>
      request<LlmTestResult>('/settings/llm/test', json(input)),
  },

  memory: {
    get: () => request<Memory>('/memory'),
    removeFact: (id: number) => request<{ ok: boolean }>(`/memory/facts/${id}`, { method: 'DELETE' }),
    removeDaily: (day: string) =>
      request<{ ok: boolean }>(`/memory/daily/${encodeURIComponent(day)}`, { method: 'DELETE' }),
  },

  deploys: {
    list: (repoId: string) => request<Deployment[]>(`/repos/${repoId}/deployments`),
    deploy: (repoId: string, force = false) =>
      request<Deployment>(`/repos/${repoId}/deploy`, json({ force })),
    teardown: (id: string) =>
      request<Deployment>(`/deploys/${id}/teardown`, { method: 'POST' }),
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
      request<{ ok: boolean; applied: string[]; commit?: string | null; branch?: string | null }>(
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