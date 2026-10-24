export type User = {
  id: number
  username: string
  display_name?: string | null
  role: 'admin' | 'demo'
  status?: 'active' | 'disabled'
  is_guest?: boolean
  expires_at?: string | null
  created_at?: string | null
}

export type AdminUser = User & {
  last_login_at?: string | null
  sessions: number
  repos: number
  files: number
  storage_bytes: number
  tokens_total: number
  quota_daily_tokens?: number | null
  quota_hourly_messages?: number | null
  quota_sandbox_daily?: number | null
  quota_job_hourly?: number | null
  quota_storage_mb?: number | null
}

export type AdminQuotaPatch = {
  status?: 'active' | 'disabled'
  role?: 'admin' | 'demo'
  display_name?: string
  quota_daily_tokens?: number | null
  quota_hourly_messages?: number | null
  quota_sandbox_daily?: number | null
  quota_job_hourly?: number | null
  quota_storage_mb?: number | null
}

export type SelfQuota = {
  self_daily_tokens?: number | null
  self_hourly_messages?: number | null
  self_sandbox_daily?: number | null
  today_tokens: number
  daily_token_budget: number
  tokens_remaining: number | null
  messages_last_hour: number
  hourly_message_limit: number
  sandbox_runs_today: number
  sandbox_daily_limit: number
  job_hourly_limit: number
  storage_limit_mb: number
}

export type AuthConfig = {
  registration_mode: 'open' | 'invite' | 'closed'
  guest_enabled: boolean
  invite_required: boolean
  min_password_length: number
}

export type RegisterResult = {
  user: User
  recovery_code: string
}

export type Session = {
  id: string
  title: string
  message_count: number
  permission_mode?: PermissionMode
  repo_ids?: string[]
  primary_repo_id?: string | null
  model?: string | null
  created_at?: string
  updated_at?: string
}

export type PermissionMode = 'readonly' | 'ask' | 'auto' | 'full'

export type EditRef = {
  id: string
  files: string[]
  staged: boolean
  status: string
  diff?: string
}

export type ReviewFinding = {
  file?: string
  line?: number
  issue: string
  suggestion?: string
}

export type Review = {
  verdict: 'pass' | 'warn' | 'block'
  summary: string
  blocking: ReviewFinding[]
  non_blocking: ReviewFinding[]
  evidence: string[]
  reviewed_at?: string
}

export type EditRecord = {
  id: string
  status: 'pending' | 'applied' | 'rejected' | 'reverted'
  files: Record<string, string>
  file_paths: string[]
  diff: string
  note: string
  repo_id: string
  repo_name: string
  review?: Review | null
  created_at?: string
  applied_at?: string
}

export type DeliveryReport = {
  status: 'verified' | 'partial' | 'unverified' | 'failed'
  request: string
  repos: { id: string; name: string }[]
  permission_mode: string
  final_answer?: string
  files_changed: { path: string; status: string }[]
  commands: { tool: string; command: string; exit_code?: number; ok: boolean; timed_out?: boolean; ms: number }[]
  checks: { name: string; status: string; detail: string }[]
  citations: { verified: number; missing: number; out_of_range: number; skipped: number; executed: boolean }
  unverified: string[]
  errors: string[]
  stats: {
    rounds: number
    tools: string[]
    prompt_tokens: number
    completion_tokens: number
    elapsed_ms: number
  }
  generated_at?: string
}

export type FileAttachment = {
  id: string
  filename: string
  mime: string
  size: number
  purpose?: string
  repo_id?: string | null
  session_id?: string | null
  created_at?: string | null
}

export type FileList = {
  files: FileAttachment[]
  used_bytes: number
  limit_bytes: number
}

export type Message = {
  id: number
  role: string
  content: string
  tool_json?: {
    tools_used?: string[]
    tool_events?: ToolEvent[]
    evidence?: Evidence
    edits?: EditRef[]
    report?: DeliveryReport
  } | null
  attachments?: FileAttachment[]
  created_at?: string
}

export type ToolEvent = {
  name: string
  ok: boolean
  ms: number
  round?: number
  command?: string | null
  exit_code?: number | null
  timed_out?: boolean
  args?: Record<string, unknown>
  error?: string | null
  preview?: string | null
}

export type Citation = {
  path: string
  line: number
  status: 'verified' | 'missing' | 'out_of_range' | 'unchecked'
  resolved_path?: string
}

export type Evidence = {
  citations: Citation[]
  verified: number
  missing: number
  out_of_range: number
  skipped: number
  executed: boolean
}

export type Brain = {
  totals: { files: number; lines: number; symbols: number; dependencies: number; docs: number; tests: number }
  languages: Record<string, number>
  entry_points: string[]
  hot_files: { path: string; inbound: number; outbound: number }[]
  reading_order: string[]
  modules: { module: string; files: number; lines: number; symbols: number }[]
  graph: { nodes: string[]; edges: [string, string][] }
  glossary: { name: string; kind: string; path: string; line: number; signature: string }[]
}

export type Impact = {
  found: boolean
  query?: string
  symbols?: { name: string; kind: string; path: string; line_start: number; line_end: number; signature: string }[]
  targets?: string[]
  direct_dependents?: string[]
  transitive_dependents?: string[]
  references?: { path: string; line_start: number; occurrences: number }[]
  tests?: string[]
  risk?: { level: 'low' | 'medium' | 'high' | 'unknown'; score?: number; reasons: string[] }
  suggested_command?: string
  note?: string
}

export type TaskStep = {
  step: string
  status?: string
  detail?: string
  analysis?: string
  files?: string[]
  test_files?: string[]
  fix_files?: string[]
  command?: string
  exit_code?: number
  root_prefix?: string | null
  stdout?: string
  stderr?: string
}

export type TaskResult = {
  analysis?: string
  root_prefix?: string
  test_files?: Record<string, string>
  fix_files?: Record<string, string>
  base_files?: Record<string, string | null>
  red?: { exit_code: number; stdout: string; stderr: string; command: string; detail?: string }
  green?: { exit_code: number; stdout: string; stderr: string; command: string }
  diff?: string
  applied?: boolean
  rejected?: boolean
  error?: string
  elapsed_ms?: number
  repair_attempts?: number
  review?: Review | null
}

export type Task = {
  id: string
  title: string
  bug_report: string
  status: string
  steps: TaskStep[]
  result: TaskResult
  created_at?: string
  repo_id: string
  repo_name: string
}

export type TaskListItem = {
  id: string
  title: string
  status: string
  created_at?: string
  repo_id: string
  repo_name: string
  applied: boolean
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

export type RepoStatus =
  | 'pending'
  | 'indexing'
  | 'ready'
  | 'failed'
  | 'planning'
  | 'plan_ready'
  | 'approved'
  | 'generating'
  | 'review'

export type Repo = {
  id: string
  name: string
  source: string
  status: RepoStatus
  kind?: 'import' | 'builder'
  error?: string | null
  stats?: { files?: number; chunks?: number; symbols?: number; embedded?: number; dependencies?: number }
  created_at?: string
  smoke?: { ok: boolean; status: string; note?: string; elapsed_ms?: number } | null
}

export type BuilderPlan = {
  summary: string
  stack: string[]
  structure: { path: string; purpose: string }[]
  data_model: { table: string; fields: string[] }[]
  api: { method: string; path: string; description: string }[]
  milestones: { name: string; tasks: string[]; verification?: string }[]
  risks: string[]
}

export type BuilderProposal = {
  files: { path: string; content: string }[]
  notes?: string
  feedback?: string
  gate?: VerifyResult | null
}

export type VerifyStep = {
  name: string
  command: string
  required: boolean
  status: 'passed' | 'failed' | 'skipped'
  exit_code: number
  timed_out?: boolean
  stdout: string
  stderr: string
  duration_ms: number
}

export type VerifyResult = {
  status: 'passed' | 'failed' | 'unsupported'
  stack?: string
  notes?: string[]
  steps?: VerifyStep[]
  elapsed_ms?: number
  exit_code: number
  stdout: string
  stderr: string
  command: string
  image: string
  at: string
}

export type ContractStatus = {
  configured: boolean
  source?: string | null
  target?: string | null
  source_exists: boolean
  target_exists: boolean
  from_config: boolean
  last_status?: string | null
  last_detail?: string | null
  checked_at?: string | null
}

export type GitCommit = { hash: string; message: string; date: string }

export type GitInfo = {
  available: boolean
  initialized: boolean
  branch?: string
  dirty?: boolean
  changed_files?: number
  commits: GitCommit[]
  reason?: string
}

export type TraceEvent = {
  id: number
  turn_id?: string | null
  kind: string
  payload: Record<string, any>
  created_at?: string
}

export type BuilderPlanResponse = {
  status: RepoStatus
  plan: BuilderPlan | Record<string, never>
  brief?: string
  rules?: string
  error?: string | null
}

export type BuilderProposalResponse = {
  status: RepoStatus
  proposal: BuilderProposal | Record<string, never>
  error?: string | null
}

// ---------- Change workflow (SPEC + plan) ----------

export type ChangeStatus =
  | 'drafting'
  | 'draft'
  | 'approved'
  | 'planning'
  | 'plan_ready'
  | 'plan_approved'
  | 'executing'
  | 'review'
  | 'applied'
  | 'rejected'
  | 'failed'
  | 'canceled'

export type ChangeTask = {
  id: string
  seq: number
  title: string
  kind: string
  in_scope: string[]
  out_scope: string[]
  acceptance: string
  depends_on: number[]
  status: string
  attempts: number
  result: {
    notes?: string
    files?: string[]
    gate?: VerifyResult
    attempts?: number
    tests?: string[]
    error?: string
  }
}

export type ChangeProposal = {
  edit_id?: string
  diff?: string
  files?: string[]
  gate?: VerifyResult
  review?: Review
  tasks?: { seq: number; title: string; kind: string; files: string[]; acceptance: string; gate: string; attempts: number }[]
}

export type ChangeEvidence = {
  summary?: string
  spec?: string
  tasks?: unknown[]
  gate?: VerifyResult
  unverified?: string[]
  elapsed_ms?: number
  applied?: boolean
  applied_at?: string
  commit?: string | null
  branch?: string | null
  applied_files?: string[]
}

export type Change = {
  id: string
  user_id: number
  repo_id: string
  repo_name: string
  title: string
  requirements: string
  goal: string
  in_scope: string[]
  out_scope: string[]
  interfaces: string[]
  acceptance_cases: string[]
  nfr: string[]
  open_questions: string[]
  status: ChangeStatus
  version: number
  plan_notes: string
  proposal: ChangeProposal
  evidence: ChangeEvidence
  error?: string | null
  job_id?: string | null
  approved_at?: string | null
  created_at?: string
  updated_at?: string
  tasks: ChangeTask[]
}

export type ChangeListItem = {
  id: string
  title: string
  status: ChangeStatus
  version: number
  repo_id: string
  repo_name: string
  error?: string | null
  created_at?: string
  updated_at?: string
  task_count: number
}

export type Job = {
  id: string
  kind: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled'
  progress: number
  step?: string | null
  result?: Record<string, unknown>
  error?: string | null
  attempts: number
  max_attempts: number
  cancel_requested: boolean
  created_at?: string
  started_at?: string
  finished_at?: string
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

export type LlmProvider = {
  id: string
  label: string
  base_url: string
  models: string[]
}

export type LlmSettings = {
  source: 'user' | 'server' | 'none'
  configured: boolean
  provider?: string | null
  model?: string | null
  base_url?: string | null
  has_key: boolean
  key_hint?: string | null
  server_model?: string | null
  allow_server_fallback: boolean
  providers: LlmProvider[]
  updated_at?: string | null
}

export type LlmSettingsInput = {
  provider: string
  model: string
  base_url?: string | null
  api_key?: string | null
}

export type LlmTestResult = {
  ok: boolean
  model: string
  latency_ms: number
  message: string
}

export type MemoryFact = {
  id: number
  content: string
  importance: number
  ttl_days: number
  promoted_at?: string | null
  last_used_at?: string | null
  created_at?: string | null
}

export type MemoryDaily = {
  day: string
  summary: string
  message_count: number
  created_at?: string | null
  updated_at?: string | null
}

export type Memory = {
  facts: MemoryFact[]
  daily: MemoryDaily[]
}

export type Metrics = {
  window_days: number
  accepted_changes: number
  changes_total: number
  tasks_total: number
  first_gate_pass_rate: number
  rework_rate: number
  approval_minutes_avg: number | null
  tokens_total: number
  p95_job_seconds: number | null
  generated_at?: string | null
}

export type Deployment = {
  id: string
  user_id: number
  repo_id: string
  action_id?: string | null
  container_name?: string | null
  host_port?: number | null
  url?: string | null
  status: string
  image?: string | null
  command?: string | null
  error?: string | null
  created_at?: string | null
  updated_at?: string | null
  stopped_at?: string | null
}

export type StreamToolCard = {
  call: ToolCall
  result?: ToolResult
  command?: string | null
  exit_code?: number | null
  timedOut?: boolean
}

export type StreamUsage = {
  model?: string
  prompt_tokens: number
  completion_tokens: number
}

export type NightItem = {
  id: string
  kind: 'change_execute' | 'task'
  target_id?: string | null
  payload?: Record<string, unknown>
  title: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
  job_id?: string | null
  error?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export type DebtSnapshot = {
  score: number
  metrics: {
    file_count?: number
    test_file_count?: number
    test_ratio?: number
    symbol_count?: number
    long_function_count?: number
    long_functions?: { name: string; kind?: string; lines: number }[]
    todo_chunk_count?: number
    huge_files?: { path: string; lines: number }[]
  }
  created_at?: string | null
}

export type DebtReport = {
  latest: DebtSnapshot | null
  history: DebtSnapshot[]
}