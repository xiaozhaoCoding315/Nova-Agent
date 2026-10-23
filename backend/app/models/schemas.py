from datetime import datetime
from typing import Optional

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
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    tool_json: Optional[dict] = None
    created_at: Optional[datetime] = None


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    content: str = Field(min_length=1, max_length=8000)
    repo_ids: list[str] = Field(default_factory=list)


# ---------- Workspace ----------

class RepoImportGit(BaseModel):
    git_url: str
    name: Optional[str] = None


class RepoOut(BaseModel):
    id: str
    name: str
    source: str = ""
    status: str = "pending"
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


FileNodeOut.model_rebuild()