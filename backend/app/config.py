from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---------- LLM ----------
    llm_model_priority: str = "dashscope,deepseek,longcat"
    longcat_api_key: str = ""
    longcat_base_url: str = "https://api.longcat.chat/openai/v1"
    longcat_model: str = "LongCat-2.0"
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen3.8-max"   # 阿里云百炼（DashScope）模型名
    llm_timeout: int = 90          # seconds per LLM call (harness)
    task_llm_timeout: int = 180    # red-green task generation is heavier (thinking models)
    max_rounds: int = 5            # agent tool-calling rounds
    # Deployment switch: false forces every user to bring their own key.
    llm_allow_server_fallback: bool = True
    # Model routing by purpose, applies to the shared server key only (BYOK
    # users' own model choice is never overridden). plan = SPEC/plan/review/
    # build/task generation (strong model); utility = summaries/fact
    # extraction (small, cheap model). Model name must be usable with the
    # first provider in LLM_MODEL_PRIORITY that has a key.
    llm_route_plan: str = ""
    llm_route_utility: str = ""

    @property
    def llm_configured(self) -> bool:
        return bool(self.deepseek_api_key or self.dashscope_api_key or self.longcat_api_key)

    # ---------- Embedding ----------
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    # ---------- PostgreSQL ----------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "nova_agent"

    # ---------- Qdrant ----------
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "code_chunks"

    # ---------- Auth ----------
    secret_key: str = "change-me-in-production"
    token_ttl_days: int = 7
    cookie_secure: bool = False    # set true when served over HTTPS
    admin_username: str = "admin"
    admin_password: str = ""
    demo_username: str = "demo"
    demo_password: str = ""
    # Account lifecycle: open | invite | closed
    registration_mode: str = "open"
    registration_invite_code: str = ""
    max_registrations_per_hour: int = 10
    max_users: int = 50
    min_password_length: int = 8
    guest_enabled: bool = True
    guest_ttl_hours: int = 24

    # ---------- Quotas ----------
    admin_hourly_messages: int = 60
    demo_hourly_messages: int = 10
    demo_daily_tokens: int = 100_000
    admin_daily_tokens: int = 0        # 0 = unlimited
    demo_sandbox_daily: int = 20
    admin_sandbox_daily: int = 0       # 0 = unlimited
    admin_job_hourly: int = 30         # import / reindex / task / builder
    demo_job_hourly: int = 5
    guest_hourly_messages: int = 5
    guest_daily_tokens: int = 50_000
    guest_sandbox_daily: int = 1
    guest_job_hourly: int = 2

    # ---------- Workspace limits ----------
    max_upload_mb: int = 100
    max_repo_files: int = 5000
    max_file_kb: int = 2048
    git_clone_timeout: int = 120
    repos_dir: str = "data/repos"          # legacy path, migrated to user_data_dir
    user_data_dir: str = "data/users"
    index_embed_max_chunks: int = 3000
    attachment_max_mb: int = 25
    user_storage_mb: int = 200
    guest_storage_mb: int = 50
    max_attachments_per_message: int = 5

    # ---------- Sandbox ----------
    sandbox_enabled: bool = True
    sandbox_image: str = "nova-sandbox:latest"
    sandbox_builder_image: str = "nova-builder:latest"
    sandbox_node_image: str = "nova-node:latest"
    sandbox_timeout: int = 30
    sandbox_install_timeout: int = 180
    sandbox_memory: str = "256m"
    sandbox_cpus: str = "0.5"
    sandbox_allow_network: bool = False   # 允许“安装依赖”时联网（admin only）

    # ---------- Tools ----------
    enable_fetch_url: bool = True
    fetch_url_max_kb: int = 512

    # ---------- Skills ----------
    skills_enabled: bool = True
    skills_dir: str = "data/skills"   # <dir>/<skill-name>/SKILL.md, operator-provided

    # ---------- Tool hooks / policy ----------
    tool_pre_hook: str = ""       # executable command; JSON payload on stdin; exit 2 blocks
    tool_post_hook: str = ""      # best-effort post-tool audit hook

    # ---------- MCP ----------
    mcp_enabled: bool = True
    mcp_config_path: str = "mcp_servers.json"
    mcp_servers_json: str = ""    # inline JSON config (overrides path)
    mcp_admin_only: bool = True
    mcp_timeout: int = 30

    # ---------- Preview deployments ----------
    preview_ttl_minutes: int = 120   # 0 = never auto-stop

    # ---------- Background jobs ----------
    job_stale_seconds: int = 120        # requeue running jobs whose heartbeat is older
    job_runner_enabled: bool = True

    # ---------- App ----------
    app_env: str = "dev"
    debug: bool = False
    log_level: str = "INFO"
    log_dir: str = "logs"
    cors_origins: str = "http://localhost:5173"
    auto_init_db: bool = False
    frontend_dist: str = ""        # explicit frontend build path (set in Docker)

    @property
    def postgres_dsn(self) -> str:
        return (f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
                f"?connect_timeout=3")

    @property
    def postgres_admin_dsn(self) -> str:
        """DSN against the maintenance DB, used to CREATE DATABASE on first run."""
        return (f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/postgres"
                f"?connect_timeout=3")

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def llm_priority_list(self) -> list[str]:
        return [p.strip() for p in self.llm_model_priority.split(",") if p.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()