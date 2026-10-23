from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- Auth ----------

class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    role: str


# ---------- Chat ----------

class SessionOut(BaseModel):
    id: str
    title: str
    message_count: int = 0
    permission_mode: str = "ask"
    repo_ids: list[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    tool_json: Optional[dict] = None
    created_at: Optional[datetime] = None


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    content: str = Field(min_length=1, max_length=8000)
    # None = keep the session's saved selection; [] = explicitly clear it.
    repo_ids: Optional[list[str]] = None
    permission_mode: Optional[Literal["readonly", "ask", "auto"]] = None


# ---------- Workspace ----------

class RepoImportGit(BaseModel):
    git_url: str
    name: Optional[str] = None


# ---------- Builder ----------

class BuilderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    requirements: str = Field(min_length=10, max_length=8000)
    rules: Optional[str] = Field(default=None, max_length=4000)


class BuilderFeedback(BaseModel):
    feedback: Optional[str] = Field(default=None, max_length=4000)


# ---------- Git ----------

class GitCommitRequest(BaseModel):
    message: Optional[str] = Field(default=None, max_length=200)


class GitRollbackRequest(BaseModel):
    commit: str = Field(min_length=7, max_length=40)


class RepoOut(BaseModel):
    id: str
    name: str
    source: str = ""
    status: str = "pending"
    kind: str = "import"          # import | builder
    error: Optional[str] = None
    stats: dict = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class FileNodeOut(BaseModel):
    path: str
    name: str
    type: str                      # dir | file
    size: int = 0
    language: str = ""
    children: list["FileNodeOut"] = Field(default_factory=list)


class FileContentOut(BaseModel):
    path: str
    language: str = ""
    line_count: int = 0
    content: str


class SymbolOut(BaseModel):
    name: str
    kind: str
    path: str
    line_start: int
    line_end: int
    signature: str = ""


class SearchHitOut(BaseModel):
    path: str
    line_start: int
    line_end: int
    content: str
    score: float = 0.0
    source: str = ""               # dense | keyword | symbol


# ---------- Tasks ----------

class TaskCreate(BaseModel):
    repo_id: str
    bug_report: str = Field(min_length=5, max_length=8000)
    title: Optional[str] = Field(default=None, max_length=120)


# ---------- Changes (SPEC + plan) ----------

class ChangeCreate(BaseModel):
    repo_id: str
    title: Optional[str] = Field(default=None, max_length=120)
    requirements: str = Field(min_length=10, max_length=8000)


class ChangeSpecUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=120)
    goal: Optional[str] = Field(default=None, max_length=4000)
    in_scope: Optional[list[str]] = None
    out_scope: Optional[list[str]] = None
    interfaces: Optional[list[str]] = None
    acceptance_cases: Optional[list[str]] = None
    nfr: Optional[list[str]] = None
    open_questions: Optional[list[str]] = None


class ChangeApplyRequest(BaseModel):
    force: bool = False


# ---------- Status ----------

class HealthOut(BaseModel):
    status: str                    # ok | degraded
    version: str
    components: dict


class UsageOut(BaseModel):
    today_tokens: int
    daily_token_budget: int        # 0 = unlimited
    tokens_remaining: Optional[int] = None
    messages_last_hour: int
    hourly_message_limit: int
    sandbox_runs_today: int
    sandbox_daily_limit: int       # 0 = unlimited


# ---------- Shared API envelopes ----------

class OkOut(BaseModel):
    ok: bool = True


class StatusActionOut(BaseModel):
    ok: bool = True
    status: str


class JobOut(BaseModel):
    id: str
    user_id: Optional[int] = None
    kind: str
    payload: dict = Field(default_factory=dict)
    status: str
    progress: float = 0.0
    step: Optional[str] = None
    result: dict = Field(default_factory=dict)
    error: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 1
    cancel_requested: bool = False
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ReviewFindingOut(BaseModel):
    file: Optional[str] = None
    line: Optional[int] = None
    issue: str
    suggestion: Optional[str] = None


class ReviewOut(BaseModel):
    verdict: str
    summary: str = ""
    blocking: list[ReviewFindingOut] = Field(default_factory=list)
    non_blocking: list[ReviewFindingOut] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    reviewed_at: Optional[str] = None


class VerifyStepOut(BaseModel):
    name: str
    command: str = ""
    required: bool = True
    status: str
    exit_code: int = 0
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0


class VerifyResultOut(BaseModel):
    status: str = "unsupported"
    stack: Optional[str] = None
    notes: list[str] = Field(default_factory=list)
    steps: list[VerifyStepOut] = Field(default_factory=list)
    exit_code: int = -1
    stdout: str = ""
    stderr: str = ""
    command: str = ""
    image: str = ""
    at: Optional[str] = None
    elapsed_ms: Optional[int] = None


# ---------- Git ----------

class GitCommitOut(BaseModel):
    hash: str
    message: str
    date: str


class GitStatusOut(BaseModel):
    available: bool = True
    initialized: bool = False
    branch: Optional[str] = None
    dirty: bool = False
    changed_files: int = 0
    commits: list[GitCommitOut] = Field(default_factory=list)
    reason: Optional[str] = None


class GitDiffOut(BaseModel):
    diff: str = ""


class GitRollbackOut(GitStatusOut):
    reindex_started: bool = True


# ---------- Changes ----------

class ChangeTaskOut(BaseModel):
    id: str
    seq: int
    title: str
    kind: str
    in_scope: list[str] = Field(default_factory=list)
    out_scope: list[str] = Field(default_factory=list)
    acceptance: str = ""
    depends_on: list[int] = Field(default_factory=list)
    status: str = "pending"
    attempts: int = 0
    result: dict = Field(default_factory=dict)


class ChangeProposalOut(BaseModel):
    edit_id: Optional[str] = None
    diff: Optional[str] = None
    files: list[str] = Field(default_factory=list)
    gate: Optional[VerifyResultOut] = None
    review: Optional[ReviewOut] = None
    tasks: list[dict] = Field(default_factory=list)


class ChangeEvidenceOut(BaseModel):
    summary: Optional[str] = None
    spec: Optional[str] = None
    tasks: list[dict] = Field(default_factory=list)
    gate: Optional[VerifyResultOut] = None
    unverified: list[str] = Field(default_factory=list)
    elapsed_ms: Optional[int] = None
    applied: Optional[bool] = None
    applied_at: Optional[str] = None
    commit: Optional[str] = None
    applied_files: list[str] = Field(default_factory=list)


class ChangeOut(BaseModel):
    id: str
    user_id: int
    repo_id: str
    repo_name: str
    title: str
    requirements: str = ""
    goal: str = ""
    in_scope: list[str] = Field(default_factory=list)
    out_scope: list[str] = Field(default_factory=list)
    interfaces: list[str] = Field(default_factory=list)
    acceptance_cases: list[str] = Field(default_factory=list)
    nfr: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    status: str
    version: int = 1
    plan_notes: str = ""
    proposal: ChangeProposalOut = Field(default_factory=ChangeProposalOut)
    evidence: ChangeEvidenceOut = Field(default_factory=ChangeEvidenceOut)
    error: Optional[str] = None
    job_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    tasks: list[ChangeTaskOut] = Field(default_factory=list)


class ChangeListItemOut(BaseModel):
    id: str
    title: str
    status: str
    version: int = 1
    repo_id: str
    repo_name: str
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    task_count: int = 0


class ChangeActionOut(BaseModel):
    ok: bool = True
    job_id: Optional[str] = None


class ChangeApplyOut(BaseModel):
    ok: bool = True
    applied: list[str] = Field(default_factory=list)
    commit: Optional[str] = None


class ChangeReportOut(BaseModel):
    change_id: str
    status: str
    spec: dict = Field(default_factory=dict)
    tasks: list[ChangeTaskOut] = Field(default_factory=list)
    proposal: ChangeProposalOut = Field(default_factory=ChangeProposalOut)
    evidence: ChangeEvidenceOut = Field(default_factory=ChangeEvidenceOut)
    error: Optional[str] = None


# ---------- Tasks ----------

class TaskOut(BaseModel):
    id: str
    title: Optional[str] = None
    bug_report: str = ""
    status: str
    steps: list[dict] = Field(default_factory=list)
    result: dict = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    repo_id: str
    repo_name: str
    user_id: int
    job_id: Optional[str] = None


class TaskListItemOut(BaseModel):
    id: str
    title: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    repo_id: str
    repo_name: str
    applied: bool = False


class TaskApplyOut(BaseModel):
    ok: bool = True
    applied: list[str] = Field(default_factory=list)
    reindex_started: bool = True


# ---------- Builder ----------

class BuilderPlanOut(BaseModel):
    status: str
    plan: dict = Field(default_factory=dict)
    error: Optional[str] = None
    brief: Optional[str] = None
    rules: Optional[str] = None


class BuilderProposalOut(BaseModel):
    status: str
    proposal: dict = Field(default_factory=dict)
    error: Optional[str] = None


class BuilderActionOut(StatusActionOut):
    pass


class BuilderApplyOut(BaseModel):
    ok: bool = True
    applied: list[str] = Field(default_factory=list)
    status: str = "indexing"


# ---------- Edits ----------

class EditOut(BaseModel):
    id: str
    status: str
    files: dict[str, str] = Field(default_factory=dict)
    file_paths: list[str] = Field(default_factory=list)
    diff: str = ""
    note: str = ""
    repo_id: str
    repo_name: str
    review: Optional[ReviewOut] = None
    created_at: Optional[datetime] = None
    applied_at: Optional[datetime] = None


class EditApproveOut(BaseModel):
    ok: bool = True
    applied: list[str] = Field(default_factory=list)
    commit: Optional[str] = None
    reindex_started: bool = True


class EditRevertOut(BaseModel):
    ok: bool = True
    restored: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    repo_id: str
    session_id: Optional[str] = None
    commit: Optional[str] = None
    reindex_started: bool = True


# ---------- Trajectory / search / impact / brain ----------

class TraceEventOut(BaseModel):
    id: int
    turn_id: Optional[str] = None
    kind: str
    payload: dict = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class SearchResponseOut(BaseModel):
    symbols: list[SymbolOut] = Field(default_factory=list)
    hits: list[SearchHitOut] = Field(default_factory=list)


class ImpactRiskOut(BaseModel):
    level: str
    score: Optional[int] = None
    reasons: list[str] = Field(default_factory=list)


class ImpactSymbolOut(BaseModel):
    name: str
    kind: str = ""
    path: str
    line_start: int = 0
    line_end: int = 0
    signature: str = ""


class ImpactReferenceOut(BaseModel):
    path: str
    line_start: int = 0
    occurrences: int = 0


class ImpactOut(BaseModel):
    found: bool
    query: Optional[str] = None
    symbols: list[ImpactSymbolOut] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    direct_dependents: list[str] = Field(default_factory=list)
    transitive_dependents: list[str] = Field(default_factory=list)
    dependency_levels: dict = Field(default_factory=dict)
    references: list[ImpactReferenceOut] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    risk: Optional[ImpactRiskOut] = None
    suggested_command: str = ""
    note: Optional[str] = None


class BrainTotalsOut(BaseModel):
    files: int = 0
    lines: int = 0
    symbols: int = 0
    dependencies: int = 0
    docs: int = 0
    tests: int = 0


class BrainHotFileOut(BaseModel):
    path: str
    inbound: int = 0
    outbound: int = 0


class BrainModuleOut(BaseModel):
    module: str
    files: int = 0
    lines: int = 0
    symbols: int = 0


class BrainGraphOut(BaseModel):
    nodes: list[str] = Field(default_factory=list)
    edges: list[list[str]] = Field(default_factory=list)


class BrainGlossaryOut(BaseModel):
    name: str
    kind: str = ""
    path: str = ""
    line: int = 0
    signature: str = ""


class BrainOut(BaseModel):
    totals: BrainTotalsOut = Field(default_factory=BrainTotalsOut)
    languages: dict[str, int] = Field(default_factory=dict)
    entry_points: list[str] = Field(default_factory=list)
    hot_files: list[BrainHotFileOut] = Field(default_factory=list)
    reading_order: list[str] = Field(default_factory=list)
    modules: list[BrainModuleOut] = Field(default_factory=list)
    graph: BrainGraphOut = Field(default_factory=BrainGraphOut)
    glossary: list[BrainGlossaryOut] = Field(default_factory=list)


FileNodeOut.model_rebuild()