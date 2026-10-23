export type User = { id: number; username: string; role: 'admin' | 'demo' }

export type Session = {
  id: string
  title: string
  message_count: number
  created_at?: string
  updated_at?: string
}

export type Message = {
  id: number
  role: string
  content: string
  tool_json?: { tools_used?: string[] } | null
  created_at?: string
}

export type RetrievalHit = {
  path: string
  line_start: number
  line_end: number
  score: number
  source: string
  kind?: string
  snippet?: string
}

export type ToolCall = { id: string; name: string; args: Record<string, unknown>; round: number }
export type ToolResult = { id: string; name: string; ok: boolean; ms: number; preview: string }

export type RepoStatus = 'pending' | 'indexing' | 'ready' | 'failed'

export type Repo = {
  id: string
  name: string
  source: string
  status: RepoStatus
  error?: string | null
  stats?: { files?: number; chunks?: number; symbols?: number; embedded?: number }
  created_at?: string
}

export type FileNode = {
  path: string
  name: string
  type: 'dir' | 'file'
  size: number
  language: string
  children: FileNode[]
}

export type Health = {
  status: string
  version: string
  components: Record<string, unknown>
}

export type Usage = {
  today_tokens: number
  daily_token_budget: number
  tokens_remaining: number | null
  messages_last_hour: number
  hourly_message_limit: number
  sandbox_runs_today: number
  sandbox_daily_limit: number
}

export type StreamToolCard = {
  call: ToolCall
  result?: ToolResult
}