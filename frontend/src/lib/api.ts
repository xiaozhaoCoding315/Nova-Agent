import type { FileNode, Health, Message, Repo, Session, Usage, User } from './types'

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
    upload: async (file: File): Promise<Repo> => {
      const form = new FormData()
      form.append('file', file)
      return request<Repo>('/repos/upload', { method: 'POST', body: form })
    },
    importGit: (gitUrl: string, name?: string) => request<Repo>('/repos/git', json({ git_url: gitUrl, name })),
  },

  status: {
    health: () => request<Health>('/status/health'),
    usage: () => request<Usage>('/status/usage'),
  },
}