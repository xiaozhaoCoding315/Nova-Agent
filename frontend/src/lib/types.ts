export type User = {
  id: number
  username: string
  display_name?: string | null
  role: 'admin' | 'demo' | 'local'
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

export type InviteCode = {
  id: number
  code: string
  note: string
  max_uses: number
  used_count: number
  created_at?: string | null
  expires_at?: string | null
}

export type LocalExecStatus = {
  connected: boolean
  last_seen_age?: number | null
}

export type NovaMode = 'server' | 'local'

export type ModeFeatures = {
  host_executor: boolean
  isolation: 'none' | 'container'
  sandbox: 'host' | 'docker'
  semantic_search: boolean
  jobs_concurrency: number
  registration: boolean
}

export type ModeInfo = {
  mode: NovaMode
  local: boolean
  auth: 'login' | 'none'
  features: ModeFeatures
  data_dir: string
}

export type LocalSetupStatus = {
  configured: boolean
  data_dir: string
  project_count: number
  has_llm_key: boolean
  default_provider?: string | null
  default_model?: string | null
}

export type LocalSetupInput = {
  project_path: string
  project_name?: string | null
  provider?: string
  model?: string
  api_key?: string | null
}

export type LocalSetupResult = {
  ok: boolean
  repo: Repo
  provider: string
  model: string
  has_key: boolean
}

/** 上下文计量（估算）：本轮提示用了多少 token、分布在哪里。 */
export type ContextMeter = {
  window: number
  sections: Record<string, number>
  total: number
  actualPromptTokens?: number | null
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
  email_verification: boolean
}

export type RegisterResult = {
  user: User
  recovery_code: string
}

export type OverrideKey =
  | 'provider' | 'model' | 'reasoning_effort'
  | 'context_window' | 'temperature' | 'max_tokens'

export type LlmOverrides = {
  provider?: string | null
  model?: string | null
  reasoning_effort?: '' | 'low' | 'medium' | 'high' | null
  context_window?: number | null
  temperature?: number | null
  max_tokens?: number | null
  /**
   * 请求侧专用：这些键要回到厂商默认。后端把覆盖存在 JSONB 对象里，null
   * 值删不掉键，所以「自动」必须显式点名要清除的键。
   */
  clear?: OverrideKey[]
}

export type Session = {
  id: string
  title: string
  message_count: number
  permission_mode?: PermissionMode
  repo_ids?: string[]
  primary_repo_id?: string | null
  model?: string | null
  llm_overrides?: LlmOverrides
  product_mode?: 'dev' | 'thesis'
  thesis_project_id?: string | null
  created_at?: string
  updated_at?: string
}

export type TurnStatus =
  | 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled' | 'interrupted'

export type Turn = {
  id: string
  session_id: string
  status: TurnStatus
  cancel_requested?: boolean
  error?: string | null
  created_at?: string | null
  updated_at?: string | null
  finished_at?: string | null
}

export type TurnSnapshot = {
  turn: Turn | null
  latest: Turn | null
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

export type SubagentFinding = {
  title: string
  detail: string
  file?: string | null
  line?: number | null
}

export type SubagentRun = {
  id: string
  title: string
  status: 'running' | 'ok' | 'partial' | 'failed' | 'timeout'
  summary?: string
  findings?: SubagentFinding[]
  files?: string[]
  rounds?: number
  tools?: string[]
  tokens?: { prompt?: number; completion?: number }
  ms?: number
  citations?: {
    verified: number
    missing: number
    out_of_range: number
    skipped: number
    executed: boolean
  }
  error?: string | null
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
    plan?: PlanState
    subagents?: SubagentRun[]
  } | null
  attachments?: FileAttachment[]
  created_at?: string
}

export type PlanStep = {
  title: string
  status: 'pending' | 'in_progress' | 'completed'
}

export type PlanState = {
  steps: PlanStep[]
  explanation?: string | null
}

export type ToolApproval = {
  id: string
  name: string
  args: Record<string, unknown>
  reason: string
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
  stdout_tail?: string | null
  stderr_tail?: string | null
  content_preview?: string | null
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
export type ToolResult = {
  id: string
  name: string
  ok: boolean
  ms: number
  preview: string
  stdout_tail?: string | null
  stderr_tail?: string | null
  content_preview?: string | null
}

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
  origin?: 'upload' | 'git' | 'local'
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
  status: 'passed' | 'failed' | 'not_run' | 'skipped' | 'unsupported'
  exit_code: number
  timed_out?: boolean
  stdout: string
  stderr: string
  duration_ms: number
  reason?: string
}

export type VerificationEnvironment = {
  mode: 'container' | 'host' | 'unknown'
  isolation: 'container' | 'none' | 'unknown'
  network: 'disabled' | 'enabled' | 'host' | 'unknown'
  workdir_scope: 'repo_snapshot' | 'host_repo' | 'unknown'
  env_scrubbed: boolean
  image: string
  notes: string[]
}

export type VerificationWorkspace = {
  commit: string
  branch: string
  dirty: boolean | null
  workspace_digest: string
  diff_digest: string
  source: 'git' | 'snapshot'
}

export type VerificationReport = {
  schema_version: string
  status: 'passed' | 'failed' | 'not_run' | 'skipped' | 'unsupported'
  stack: string
  environment: VerificationEnvironment
  workspace: VerificationWorkspace
  steps: VerifyStep[]
  notes: string[]
  started_at: string
  finished_at: string
  elapsed_ms: number
  command: string
  exit_code: number
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
  report?: VerificationReport
}

export type EvidenceClaim = {
  claim_id: string
  statement: string
  kind: string
  status: 'confirmed' | 'unverified' | 'not_run' | 'unsupported' | 'failed'
  commit: string
  path: string
  line: number | null
  evidence_ids: string[]
  notes: string[]
}

export type EvidenceArtifact = {
  artifact_id: string
  name: string
  sha256: string
  size: number
  media_type: string
  created_at: string
}

export type EvidenceEnvironment = {
  mode: string
  os: string
  arch: string
  isolation: string
  network: string
  image_digest: string
  tool_versions: Record<string, string>
  working_dir: string
  notes: string[]
}

export type EvidencePack = {
  schema_version: string
  pack_id: string
  task_id: string
  repo_id: string
  commit: string
  created_at: string
  claims: EvidenceClaim[]
  artifacts: EvidenceArtifact[]
  environment: EvidenceEnvironment
  unproven: string[]
  manifest_sha256: string
}

export type EvidencePackSummary = {
  pack_id: string
  task_id: string
  repo_id: string
  commit: string
  created_at: string
  claims: number
  artifacts: number
  unproven: number
  manifest_sha256: string
}

export type EvidenceVerifyResult = {
  pack_id: string
  ok: boolean
  problems: string[]
}

export type EnvironmentRow = {
  dimension: string
  local: unknown
  container: unknown
  result: 'same' | 'different' | 'unknown'
  note: string
}

export type EnvironmentComparison = {
  rows: EnvironmentRow[]
  comparable: string[]
  not_comparable: string[]
  different: string[]
  unknown: string[]
  identical: boolean
  note: string
}

export type GitHubConnectionStatus = {
  connected: boolean
  login: string
  scopes: string
  created_at?: string
  updated_at?: string
}

export type GitHubRemote = {
  host: string
  owner: string
  repo: string
  full_name: string
  branch: string
}

export type GitHubPullRequest = {
  number: number
  url: string
  title: string
  head: string
  base: string
  draft: boolean
  state: string
  owner?: string
  repo?: string
  created_at: string
}

export type GitHubCheck = {
  name: string
  status: string
  conclusion: string
  url: string
  source: string
}

export type GitHubReview = {
  id: number
  user: string
  state: string
  body: string
  submitted_at: string
  url: string
}

export type GitHubComment = {
  id: number
  user: string
  body: string
  path: string
  line: number | null
  created_at: string
  url: string
}

export type GitHubPullRequestStatus = {
  number: number
  url: string
  title: string
  state: string
  draft: boolean
  mergeable: boolean | null
  mergeable_state: string
  head: string
  head_sha: string
  base: string
  updated_at: string
  checks: GitHubCheck[]
  reviews: GitHubReview[]
  comments: GitHubComment[]
  auto_merge: boolean
  note: string
}

export type RemoteConfig = {
  enabled: boolean
  mode: 'direct' | 'relay'
  pairing_ttl_seconds: number
  workbench_path: string
  commands: string[]
  transport: string
}

export type RemotePairing = {
  pair_id: string
  status: 'pending' | 'claimed' | 'confirmed' | 'rejected' | 'expired'
  created_at: string
  expires_at: string
  claimed_at: string
  confirmed_at: string
  device_id: string
  device_name: string
  sas: string
}

export type RemoteDevice = {
  device_id: string
  name: string
  status: 'pending' | 'active' | 'revoked'
  created_at: string
  confirmed_at: string
  revoked_at: string
  last_seen_at: string
  permissions: string[]
  public_key: Record<string, string>
}

export type RemoteNotification = {
  id: string
  kind: string
  status: string
  summary: string
  task_id: string
  device_id: string
  created_at: string
  read: boolean
}

export type RemoteProgressEvent = {
  event_id: string
  task_id: string
  session_id: string
  kind: string
  status: string
  stage: string
  percent: number | null
  summary: string
  created_at: string
  metadata: Record<string, unknown>
}

export type RemoteApproval = {
  approval_id: string
  task_id: string
  title: string
  reason: string
  risk: 'low' | 'medium' | 'high'
  remote_decidable: boolean
  action_hash: string
  expires_at: string
}

export type RemoteCommandEnvelope = {
  v: number
  command_id: string
  device_id: string
  type: 'status.get' | 'run.stop' | 'approval.list' | 'approval.decide'
  action_hash: string
  args_ciphertext: string
  approval_id: string
  decision: string
  issued_at: string
  expires_at: string
  nonce: string
  signature: string
}

export type RemoteCommandResult = {
  ok: boolean
  device_status: string
  decision: {
    allowed: boolean
    reason: string
    risk: string
    requires_local: boolean
    status: string
  }
  server_time?: string
  events?: RemoteProgressEvent[]
  notifications?: RemoteNotification[]
  approvals?: RemoteApproval[]
  approval?: { approval_id: string; status: string; action_hash: string }
  stopped_task_ids?: string[]
  idempotent?: boolean
  pairing?: { pair_id: string; sas: string; expires_at: string }
}

export type RemoteAudit = {
  local: Record<string, unknown>[]
  relay: Record<string, unknown>[]
  note: string
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
  env?: string
  components: Record<string, unknown>
}

/** /api/v1/downloads 的一个安装包。 */
export type DownloadFile = {
  name: string
  platform: string
  size: number
  modified_at: string
  url: string
}

export type DownloadsListing = {
  files: DownloadFile[]
  directory: string
  hint: string
}

export type ExtensionTool = {
  name: string
  description: string
  admin_only: boolean
}

export type ExtensionServer = {
  name: string
  tools: ExtensionTool[]
}

export type SkillInfo = {
  name: string
  description: string
  triggers: string[]
}

export type Extensions = {
  mcp_enabled: boolean
  mcp_ready: boolean
  mcp_servers: ExtensionServer[]
  skills_enabled: boolean
  skills: SkillInfo[]
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
  group: 'domestic' | 'international' | 'aggregator' | 'local' | string
  kind: 'openai' | 'anthropic' | string
  base_url: string
  models: string[]
  docs_url: string
  free_tier: boolean
  supports_tools: boolean
  supports_vision: boolean
  supports_reasoning: boolean
  supports_temperature: boolean
  context_window: number
  base_url_locked: boolean
  env_key: string
  icon: string
}

export type LlmCredential = {
  provider: string
  label: string
  icon: string
  model: string
  base_url: string
  has_key: boolean
  key_hint?: string | null
  context_window?: number | null
  reasoning_effort?: string | null
  is_default: boolean
  updated_at?: string | null
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
  context_window?: number | null
  reasoning_effort?: string | null
  providers: LlmProvider[]
  credentials: LlmCredential[]
  updated_at?: string | null
}

export type LlmSettingsInput = {
  provider: string
  model: string
  base_url?: string | null
  api_key?: string | null
  context_window?: number
  reasoning_effort?: string
}

export type LlmCredentialInput = {
  model: string
  base_url?: string | null
  api_key?: string | null
  context_window?: number
  reasoning_effort?: string
  is_default?: boolean
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

export type ToolMetric = {
  name: string
  calls: number
  ok_rate: number
  avg_ms: number | null
  p95_ms: number | null
  policy_denials: number
  business_errors: number
  infra_errors: number
}

export type Metrics = {
  window_days: number
  tasks_total: number
  first_gate_pass_rate: number
  rework_rate: number
  approval_minutes_avg: number | null
  tokens_total: number
  p95_job_seconds: number | null
  tool_metrics?: ToolMetric[]
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
  stdout_tail?: string | null
  stderr_tail?: string | null
  output?: string
}

export type StreamUsage = {
  model?: string
  prompt_tokens: number
  completion_tokens: number
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

export type ThesisDegree = 'undergraduate' | 'master' | 'doctor'

export type ThesisTemplate = {
  id: string
  name: string
  description: string
  source: string
  version?: string
  degree: string
  is_sample: boolean
}

export type ThesisProject = {
  id: string
  title: string
  school: string
  degree: ThesisDegree | string
  template_id: string
  status: string
  document_count: number
  open_issue_count: number
  source_repo_id?: string | null
  source_notes?: string
  created_at?: string | null
  updated_at?: string | null
}

export type ThesisStats = {
  block_count?: number
  paragraph_count?: number
  table_count?: number
  heading_count?: number
  max_heading_level?: number
  char_count?: number
  word_count?: number
  image_count?: number
  section_count?: number
  page_break_count?: number
  empty_paragraph_count?: number
  has_toc?: boolean
  [key: string]: number | boolean | undefined
}

export type ThesisDocument = {
  id: string
  project_id: string
  filename: string
  sha256: string
  size: number
  mime: string
  status: 'parsed' | 'failed' | string
  parse_error?: string | null
  stats: ThesisStats
  version?: number
  has_working_copy?: boolean
  created_at?: string | null
  updated_at?: string | null
}

export type ThesisOutlineNode = {
  level: number
  text: string
  block_index: number
  style: string
}

export type ThesisDocumentDetail = ThesisDocument & {
  outline: ThesisOutlineNode[]
  warnings: string[]
}

export type ThesisProjectDetail = ThesisProject & {
  documents: ThesisDocument[]
}

export type ThesisIssue = {
  id: string
  project_id: string
  document_id: string
  rule_id: string
  category: string
  severity: 'blocker' | 'warn' | 'info' | string
  title: string
  detail: string
  location: Record<string, unknown>
  evidence: Record<string, unknown>
  status: string
  fix_type?: string | null
  fix_available?: boolean
  source?: string
  template_version?: string
  confidence?: string
  created_at?: string | null
  updated_at?: string | null
}

export type ThesisFixPreview = {
  issue_id: string
  fix_type: string
  payload: Record<string, unknown>
  before: Record<string, unknown>
  after: Record<string, unknown>
  verification: Record<string, unknown>
  note: string
}

export type ThesisFix = {
  id: string
  project_id: string
  document_id: string
  issue_id?: string | null
  rule_id: string
  fix_type: string
  before: Record<string, unknown>
  after: Record<string, unknown>
  applied_at?: string | null
  undone_at?: string | null
}

export type ThesisApplyResult = {
  issue: ThesisIssue
  fix: ThesisFix
  document: ThesisDocument
  remaining_counts: ThesisIssueCounts
}

export type ThesisCitation = {
  id: string
  project_id: string
  document_id: string
  kind: 'reference' | 'in_text' | string
  raw: string
  normalized: Record<string, unknown>
  status: string
  confidence: string
  doi?: string
  metadata_status?: string
  metadata?: Record<string, unknown>
  metadata_fetched_at?: string | null
  created_at?: string | null
}

export type ThesisCitationAudit = {
  project_id: string
  document_id: string
  references: Record<string, unknown>[]
  in_text: Record<string, unknown>[]
  citations: ThesisCitation[]
  reference_section_found: boolean
  generated_at: string
}

export type ThesisReferencePdf = {
  id: string
  project_id: string
  filename: string
  sha256: string
  size: number
  page_count: number
  created_at?: string | null
}

export type ThesisCitationEvidence = {
  id: string
  project_id: string
  document_id?: string | null
  reference_index?: number | null
  reference_raw: string
  pdf_id?: string | null
  pdf_filename: string
  page?: number | null
  quote: string
  score: number
  method: string
  support: 'needs_review' | 'supported' | 'partial' | 'unsupported' | string
  note: string
  created_at?: string | null
  updated_at?: string | null
}

export type ThesisEvidenceLocateResult = {
  project_id: string
  document_id: string
  pdfs: ThesisReferencePdf[]
  evidence: ThesisCitationEvidence[]
  matched: number
  total_references: number
  located_at: string
}

export type ThesisDisclosure = {
  id: string
  project_id: string
  tool: string
  tool_version: string
  purpose: string
  stage: string
  prompt: string
  output: string
  modified: boolean
  created_at?: string | null
}

export type ThesisDisclosureInput = {
  tool: string
  tool_version?: string
  purpose?: string
  stage?: string
  prompt?: string
  output?: string
  modified?: boolean
}

export type ThesisIssueCounts = {
  blocker: number
  warn: number
  info: number
  total: number
}

export type ThesisScanResult = {
  project_id: string
  document_id: string
  template_id: string
  issues: ThesisIssue[]
  counts: ThesisIssueCounts
  scanned_at: string
}

export type ThesisReport = {
  project: ThesisProject
  document: ThesisDocument | null
  template: ThesisTemplate
  counts: ThesisIssueCounts
  by_category: Record<string, number>
  issues: ThesisIssue[]
  fixes: ThesisFix[]
  generated_at: string
}

export type ThesisProjectInput = {
  title: string
  school?: string
  degree?: ThesisDegree
  template_id?: string
  source_repo_id?: string | null
  source_notes?: string
}
export type DocumentWorkspace = {
  id: string
  title: string
  kind: 'report' | 'thesis' | 'resume'
  created_at: string
  root?: string | null
}

export type DocumentWorkspaceInput = {
  title: string
  kind?: 'report' | 'thesis' | 'resume'
  root?: string | null
}

export type DocumentFile = {
  path: string
  size: number
  sha256: string
  updated_at: string
}

export type DocumentContent = {
  path: string
  content: string
  sha256: string
  size: number
  last_known_sha?: string | null
}

export type DocumentVersion = {
  version_id: string
  path: string
  sha256: string
  size: number
  created_at: string
}

export type DocumentWriteResult = {
  path: string
  sha256: string
  created: boolean
  version?: DocumentVersion | null
}

export type DocumentFidelity = {
  source_format: string
  target_format: string
  status: 'exact' | 'partial' | 'lossy'
  preserved: string[]
  modified: string[]
  dropped: string[]
  unsupported: string[]
  notes: string[]
  renderer: string
  renderer_version: string
  template_version?: string | null
}

export type DocumentExportResult = {
  status: 'done' | 'failed' | 'unsupported'
  format: 'docx' | 'pdf'
  path?: string | null
  filename?: string | null
  fidelity: Partial<DocumentFidelity>
  diagnostics: string[]
}

export type DocumentConvertResult = {
  status: string
  output_path?: string | null
  fidelity_path?: string | null
  fidelity: DocumentFidelity
  diagnostics: string[]
}

export type DocumentDiagnostics = {
  workspace: Record<string, unknown>
  manuscripts: number
  unreadable: string[]
  unsupported: Record<string, number>
  tools: { pandoc: boolean; libreoffice: boolean }
  schema_version: string
}

export type ThesisStageSummary = {
  stage: string
  label: string
  position: 'current' | 'done' | 'upcoming'
  readiness: string
  readiness_label: string
  confirmed: boolean
  stale: boolean
  confirmed_at: string
  artifact: string
}

export type ThesisStageEvent = {
  id: string
  type: string
  stage: string
  from_stage: string
  readiness: string
  content_sha: string
  note: string
  created_at: string
}

export type ResumeProfile = {
  id: string
  user_id: number
  name: string
  headline: string
  contact: Record<string, string>
  created_at: string
  updated_at: string
}

export type ResumeFactStatus =
  | 'self_reported' | 'evidence_linked' | 'needs_confirmation' | 'excluded'

export type ResumeFact = {
  id: string
  profile_id: string
  category: string
  title: string
  detail: string
  status: ResumeFactStatus
  evidence: string
  metrics: string[]
  created_at: string
  updated_at: string
}

export type ResumeJobVersion = {
  id: string
  profile_id: string
  title: string
  company: string
  jd_text: string
  jd_sha256: string
  fact_ids: string[]
  template: string
  notes: string
  created_at: string
  updated_at: string
  markdown?: string
}

export type ResumeProfileDetail = {
  profile: ResumeProfile
  facts: ResumeFact[]
  versions: ResumeJobVersion[]
}

export type ResumeQuestion = { key: string; question: string }

export type ThesisStageDraft = {
  stage: string
  label: string
  content: string
  usage?: Record<string, unknown> | null
  note: string
}

export type ThesisExportWarning = {
  stage: string
  label: string
  kind: 'not_final' | 'unconfirmed' | 'stale' | 'needs_review'
  message: string
}

export type ThesisExportReadiness = {
  project_id: string
  ready: boolean
  stage: string
  readiness: string
  warnings: ThesisExportWarning[]
}

export type ThesisStages = {
  project_id: string
  state: {
    stage: string
    readiness: string
    confirmations: Record<string, { sha256: string; confirmed_at: string; stale: boolean }>
    artifacts: Record<string, string>
    contents: Record<string, string>
    updated_at: string
  }
  summary: ThesisStageSummary[]
  current_content: string
  events: ThesisStageEvent[]
}
