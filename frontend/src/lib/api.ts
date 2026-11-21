import type {
  AdminQuotaPatch, AdminUser, AuthConfig, Brain, BuilderPlanResponse, BuilderProposalResponse,
  ContractStatus, DebtReport, DebtSnapshot, Deployment, DocumentContent, DocumentDiagnostics,
  DocumentExportResult, DocumentFile, DocumentVersion, DocumentWorkspace, DocumentWorkspaceInput,
  DocumentWriteResult, DownloadsListing, EditRecord, Extensions,
  FileAttachment, FileList, FileNode, GitInfo, Health, Impact, InviteCode, Job, LocalExecStatus,
  LocalSetupInput, LocalSetupResult, LocalSetupStatus,
  LlmCredential, LlmCredentialInput, LlmOverrides, LlmProvider, LlmSettings, LlmSettingsInput,
  LlmTestResult, Memory, Message, Metrics, ModeInfo, RegisterResult, Repo,
  Review, SelfQuota, Session, Task, TaskListItem, ThesisApplyResult, ThesisCitationAudit,
  ThesisCitationEvidence, ThesisDisclosure, ThesisDisclosureInput, ThesisDocument,
  ThesisDocumentDetail, ThesisEvidenceLocateResult, ThesisFix, ThesisFixPreview, ThesisIssue,
  ThesisProject, ThesisProjectDetail, ThesisProjectInput, ThesisReferencePdf, ThesisReport,
  ThesisScanResult, ThesisStages, ThesisTemplate, TraceEvent, Turn, TurnSnapshot, Usage, User,
  VerifyResult,
} from './types'

export class ApiError extends Error {
  status: number
  data?: unknown
  constructor(status: number, message: string, data?: unknown) {
    super(message)
    this.status = status
    this.data = data
  }
}

/** 常见状态码的友好解释；后端返回了具体 detail 时优先展示 detail。 */
const FRIENDLY_HTTP: Record<number, string> = {
  400: '请求参数有误，请检查后重试',
  401: '登录已过期，请重新登录',
  403: '没有权限执行此操作',
  404: '请求的内容不存在，可能已被删除',
  408: '请求超时，请重试',
  413: '内容太大，请精简后重试',
  422: '提交的内容格式不正确',
  429: '操作太频繁或额度已用完，请稍后再试',
  500: '服务器内部错误，请稍后重试；若持续出现请联系管理员',
  502: '服务暂时不可用（网关错误），请稍后重试',
  503: '服务正在维护或过载，请稍后重试',
  504: '服务响应超时，请稍后重试',
}

export function friendlyHttpError(status: number, detail?: string, data?: unknown): ApiError {
  const text = detail?.trim()
  if (text) return new ApiError(status, text, data)
  return new ApiError(status, FRIENDLY_HTTP[status] ?? `请求失败（${status}），请稍后重试`, data)
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api/v1${path}`, { credentials: 'include', ...options })
  } catch {
    throw new ApiError(0, '网络连接失败，请检查服务是否可用')
  }
  if (!res.ok) {
    let detail: string | undefined
    let data: unknown
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (body?.detail && typeof body.detail === 'object') {
        data = body.detail
        if (typeof body.detail.message === 'string') detail = body.detail.message
      }
    } catch {
      /* 非 JSON 错误体（如网关 HTML 页），用状态码兜底文案 */
    }
    throw friendlyHttpError(res.status, detail, data)
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

/** Fetch a file with the session cookie and hand it to the browser. */
async function downloadFile(path: string, options: RequestInit = {}): Promise<void> {
  let res: globalThis.Response
  try {
    res = await fetch(`/api/v1${path}`, { credentials: 'include', ...options })
  } catch {
    throw new ApiError(0, '网络连接失败，请检查服务是否可用')
  }
  if (!res.ok) {
    let detail: string | undefined
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* 非 JSON 错误体 */
    }
    throw friendlyHttpError(res.status, detail)
  }
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  const plainMatch = /filename="?([^";]+)"?/i.exec(disposition)
  const filename = utf8Match
    ? decodeURIComponent(utf8Match[1])
    : plainMatch?.[1] ?? 'download'
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export const api = {
  authConfig: () => request<AuthConfig>('/auth/config'),
  login: (username: string, password: string) => request<User>('/auth/login', json({ username, password })),
  register: (username: string, password: string, displayName?: string, inviteCode?: string, email?: string, emailCode?: string) =>
    request<RegisterResult>('/auth/register', json({
      username, password, display_name: displayName || null, invite_code: inviteCode || null,
      email: email || null, email_code: emailCode || null,
    })),
  emailCode: (email: string, purpose: 'register' | 'reset') =>
    request<{ ok: boolean; masked_email: string }>('/auth/email/code', json({ email, purpose })),
  resetPasswordByEmail: (username: string, email: string, code: string, newPassword: string) =>
    request<{ ok: boolean }>('/auth/password/reset/email', json({
      username, email, code, new_password: newPassword,
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
    invites: {
      list: () => request<InviteCode[]>('/admin/invites'),
      create: (note: string, maxUses: number, expiresDays: number) =>
        request<InviteCode>('/admin/invites', json({ note, max_uses: maxUses, expires_days: expiresDays })),
      remove: (id: number) => request<{ ok: boolean }>(`/admin/invites/${id}`, { method: 'DELETE' }),
    },
  },

  quota: {
    get: () => request<SelfQuota>('/settings/quota'),
    update: (values: {
      self_daily_tokens?: number | null
      self_hourly_messages?: number | null
      self_sandbox_daily?: number | null
    }) => request<SelfQuota>('/settings/quota', { ...json(values), method: 'PUT' }),
  },

  sessions: {
    list: (repoId?: string, scope?: { productMode?: 'dev' | 'thesis'; thesisProjectId?: string }) => {
      const params = new URLSearchParams()
      if (repoId) params.set('repo_id', repoId)
      if (scope?.productMode) params.set('product_mode', scope.productMode)
      if (scope?.thesisProjectId) params.set('thesis_project_id', scope.thesisProjectId)
      const suffix = params.toString()
      return request<Session[]>(`/chat/sessions${suffix ? `?${suffix}` : ''}`)
    },
    create: (
      repoIds: string[] = [],
      scope?: { productMode?: 'dev' | 'thesis'; thesisProjectId?: string },
    ) => request<Session>('/chat/sessions', json({
      repo_ids: repoIds,
      product_mode: scope?.productMode ?? 'dev',
      thesis_project_id: scope?.thesisProjectId ?? null,
    })),
    messages: (id: string) => request<Message[]>(`/chat/sessions/${id}/messages`),
    rename: (id: string, title: string) =>
      request<Session>(`/chat/sessions/${id}`, { ...json({ title }), method: 'PATCH' }),
    update: (id: string, patch: { title?: string; llm_overrides?: LlmOverrides }) =>
      request<Session>(`/chat/sessions/${id}`, { ...json(patch), method: 'PATCH' }),
    remove: (id: string) => request<{ ok: boolean }>(`/chat/sessions/${id}`, { method: 'DELETE' }),
    cancelTool: (sessionId: string, toolCallId: string) =>
      request<{ ok: boolean; killed: number }>(
        `/chat/sessions/${sessionId}/tools/${encodeURIComponent(toolCallId)}/cancel`,
        { method: 'POST' },
      ),
    approveTool: (sessionId: string, toolCallId: string) =>
      request<{ ok: boolean }>(
        `/chat/sessions/${sessionId}/tools/${encodeURIComponent(toolCallId)}/approve`,
        { method: 'POST' },
      ),
    rejectTool: (sessionId: string, toolCallId: string) =>
      request<{ ok: boolean }>(
        `/chat/sessions/${sessionId}/tools/${encodeURIComponent(toolCallId)}/reject`,
        { method: 'POST' },
      ),
  },

  turns: {
    get: (id: string) => request<Turn>(`/chat/turns/${id}`),
    active: (sessionId: string) =>
      request<TurnSnapshot>(`/chat/sessions/${sessionId}/turns/active`),
    cancel: (id: string) =>
      request<{ ok: boolean; canceled: boolean }>(`/chat/turns/${id}/cancel`, {
        method: 'POST',
      }),
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
    localFolder: (path: string, name?: string) =>
      request<Repo>('/repos/local', json({ path, name })),
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
    mode: () => request<ModeInfo>('/status/mode'),
  },

  extensions: () => request<Extensions>('/extensions'),

  downloads: () => request<DownloadsListing>('/downloads'),

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
    providers: () => request<LlmProvider[]>('/settings/llm/providers'),
    credentials: () => request<LlmCredential[]>('/settings/llm/credentials'),
    saveCredential: (provider: string, input: LlmCredentialInput) =>
      request<LlmCredential>(`/settings/llm/credentials/${provider}`, {
        ...json(input),
        method: 'PUT',
      }),
    deleteCredential: (provider: string) =>
      request<{ ok: boolean }>(`/settings/llm/credentials/${provider}`, {
        method: 'DELETE',
      }),
    setDefault: (provider: string) =>
      request<LlmCredential>(`/settings/llm/credentials/${provider}/default`, {
        method: 'POST',
      }),
  },

  local: {
    status: () => request<LocalExecStatus>('/local/exec/status'),
    setupStatus: () => request<LocalSetupStatus>('/local/setup'),
    setup: (input: LocalSetupInput) =>
      request<LocalSetupResult>('/local/setup', json(input)),
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

  thesis: {
    templates: () => request<ThesisTemplate[]>('/thesis/templates'),
    projects: () => request<ThesisProject[]>('/thesis/projects'),
    project: (id: string) => request<ThesisProjectDetail>(`/thesis/projects/${id}`),
    createProject: (input: ThesisProjectInput) =>
      request<ThesisProject>('/thesis/projects', json(input)),
    updateProject: (id: string, patch: Partial<ThesisProjectInput>) =>
      request<ThesisProject>(`/thesis/projects/${id}`, { ...json(patch), method: 'PATCH' }),
    removeProject: (id: string) =>
      request<{ ok: boolean }>(`/thesis/projects/${id}`, { method: 'DELETE' }),
    documents: (projectId: string) =>
      request<ThesisDocument[]>(`/thesis/projects/${projectId}/documents`),
    uploadDocument: (projectId: string, file: File) => {
      const form = new FormData()
      form.append('file', file)
      return request<ThesisDocument>(`/thesis/projects/${projectId}/documents`, {
        method: 'POST',
        body: form,
      })
    },
    document: (documentId: string) =>
      request<ThesisDocumentDetail>(`/thesis/documents/${documentId}`),
    scan: (projectId: string, templateId?: string) => {
      const suffix = templateId ? `?template_id=${encodeURIComponent(templateId)}` : ''
      return request<ThesisScanResult>(`/thesis/projects/${projectId}/scan${suffix}`, {
        method: 'POST',
      })
    },
    issues: (projectId: string, status = 'open') =>
      request<ThesisIssue[]>(
        `/thesis/projects/${projectId}/issues?status=${encodeURIComponent(status)}`,
      ),
    updateIssue: (issueId: string, status: 'open' | 'ignored') =>
      request<ThesisIssue>(`/thesis/issues/${issueId}`, {
        ...json({ status }),
        method: 'PATCH',
      }),
    previewFix: (issueId: string) =>
      request<ThesisFixPreview>(`/thesis/issues/${issueId}/preview`, { method: 'POST' }),
    applyFix: (issueId: string) =>
      request<ThesisApplyResult>(`/thesis/issues/${issueId}/apply`, { method: 'POST' }),
    undoFix: (issueId: string) =>
      request<ThesisApplyResult>(`/thesis/issues/${issueId}/undo`, { method: 'POST' }),
    fixes: (projectId: string) =>
      request<ThesisFix[]>(`/thesis/projects/${projectId}/fixes`),
    citations: (projectId: string) =>
      request<ThesisCitationAudit>(`/thesis/projects/${projectId}/citations`),
    auditCitations: (projectId: string) =>
      request<ThesisCitationAudit>(`/thesis/projects/${projectId}/citations/audit`, {
        method: 'POST',
      }),
    verifyMetadata: (projectId: string) =>
      request<ThesisCitationAudit>(`/thesis/projects/${projectId}/citations/metadata`, {
        method: 'POST',
      }),
    referencePdfs: (projectId: string) =>
      request<ThesisReferencePdf[]>(`/thesis/projects/${projectId}/reference-pdfs`),
    uploadReferencePdf: (projectId: string, file: File) => {
      const form = new FormData()
      form.append('file', file)
      return request<ThesisReferencePdf>(`/thesis/projects/${projectId}/reference-pdfs`, {
        method: 'POST',
        body: form,
      })
    },
    deleteReferencePdf: (pdfId: string) =>
      request<{ ok: boolean }>(`/thesis/reference-pdfs/${pdfId}`, { method: 'DELETE' }),
    citationEvidence: (projectId: string) =>
      request<ThesisCitationEvidence[]>(`/thesis/projects/${projectId}/citations/evidence`),
    locateEvidence: (projectId: string) =>
      request<ThesisEvidenceLocateResult>(`/thesis/projects/${projectId}/citations/locate`, {
        method: 'POST',
      }),
    updateEvidence: (evidenceId: string, support: string, note?: string) =>
      request<ThesisCitationEvidence>(`/thesis/citations/evidence/${evidenceId}`, {
        ...json({ support, note }),
        method: 'PATCH',
      }),
    disclosures: (projectId: string) =>
      request<ThesisDisclosure[]>(`/thesis/projects/${projectId}/disclosures`),
    createDisclosure: (projectId: string, input: ThesisDisclosureInput) =>
      request<ThesisDisclosure>(`/thesis/projects/${projectId}/disclosures`, json(input)),
    deleteDisclosure: (disclosureId: string) =>
      request<{ ok: boolean }>(`/thesis/disclosures/${disclosureId}`, { method: 'DELETE' }),
    stages: (projectId: string) =>
      request<ThesisStages>(`/thesis/projects/${projectId}/stages`),
    setStageContent: (projectId: string, content: string) =>
      request<ThesisStages>(`/thesis/projects/${projectId}/stages/content`, json({ content })),
    setStageReadiness: (projectId: string, readiness: string) =>
      request<ThesisStages>(`/thesis/projects/${projectId}/stages/readiness`, json({ readiness })),
    confirmStage: (projectId: string, note = '') =>
      request<ThesisStages>(`/thesis/projects/${projectId}/stages/confirm`, json({ note })),
    advanceStage: (projectId: string, toStage?: string) =>
      request<ThesisStages>(
        `/thesis/projects/${projectId}/stages/advance`,
        json({ to_stage: toStage ?? null }),
      ),
    returnStage: (projectId: string, toStage: string) =>
      request<ThesisStages>(`/thesis/projects/${projectId}/stages/return`, json({ to_stage: toStage })),
    report: (projectId: string) =>
      request<ThesisReport>(`/thesis/projects/${projectId}/report`),
    exportReport: (projectId: string, format: 'html' | 'docx') =>
      downloadFile(`/thesis/projects/${projectId}/report/export?format=${format}`),
    exportPackage: (projectId: string) =>
      downloadFile(`/thesis/projects/${projectId}/export`, { method: 'POST' }),
  },

  documents: {
    workspaces: () => request<{ workspaces: DocumentWorkspace[] }>('/documents/workspaces'),
    createWorkspace: (input: DocumentWorkspaceInput) =>
      request<DocumentWorkspace>('/documents/workspaces', json(input)),
    workspace: (id: string) => request<DocumentWorkspace>(`/documents/workspaces/${id}`),
    removeWorkspace: (id: string) =>
      request<{ ok: boolean }>(`/documents/workspaces/${id}`, { method: 'DELETE' }),
    files: (id: string) =>
      request<{ files: DocumentFile[] }>(`/documents/workspaces/${id}/files`),
    content: (id: string, path: string) =>
      request<DocumentContent>(
        `/documents/workspaces/${id}/content?path=${encodeURIComponent(path)}`,
      ),
    saveContent: (
      id: string,
      input: { path: string; content: string; base_sha?: string | null; force?: boolean },
    ) => request<DocumentWriteResult>(`/documents/workspaces/${id}/content`, {
      ...json(input),
      method: 'PUT',
    }),
    versions: (id: string, path: string) =>
      request<{ versions: DocumentVersion[] }>(
        `/documents/workspaces/${id}/versions?path=${encodeURIComponent(path)}`,
      ),
    restore: (id: string, versionId: string, input: { path: string; base_sha?: string | null }) =>
      request<DocumentWriteResult>(
        `/documents/workspaces/${id}/versions/${versionId}/restore`,
        json(input),
      ),
    export: (id: string, input: { path: string; format: 'docx' | 'pdf' }) =>
      request<DocumentExportResult>(`/documents/workspaces/${id}/export`, json(input)),
    downloadExport: (id: string, path: string) =>
      downloadFile(`/documents/workspaces/${id}/download?path=${encodeURIComponent(path)}`),
    diagnostics: (id: string) =>
      request<DocumentDiagnostics>(`/documents/workspaces/${id}/diagnostics`),
    draft: (id: string, input: { requirements: string; path?: string; word_count?: number }) =>
      request<{ path: string; sha256: string; content: string; usage?: Record<string, unknown> }>(
        `/documents/workspaces/${id}/draft`, json(input),
      ),
  },

  trajectory: (sessionId: string) =>
    request<TraceEvent[]>(`/chat/sessions/${sessionId}/trajectory`),
}