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
    llm_timeout: int = 300         # seconds per LLM call (长任务的生成可能持续数分钟)
    task_llm_timeout: int = 180    # red-green task generation is heavier (thinking models)
    max_rounds: int = 12           # 每段工具调用轮次（触顶后自动续段，见 max_continuations）
    max_continuations: int = 3     # 段触顶后自动注入"继续"指令的次数（长任务不断档）
    turn_timeout: int = 1800       # 单轮任务总时长上限（秒），到点暂停并可手动继续
    llm_round_retries: int = 1     # 单轮模型调用失败且无产出时的自动重试次数
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
    guest_total_messages: int = 3     # 游客终身可发送的对话条数（0 = 不限）
    guest_once_ip_days: int = 7       # 同一 IP 创建游客的最小间隔天数（0 = 不限制）
    default_context_window: int = 131_072   # 未配置个性化窗口时的上下文估算基准
    local_exec_timeout: int = 60            # 本地执行器回传结果的等待上限（秒）
    # 服务端共享 Key 的供应范围：开启基础开关后，默认仅游客与管理员可用；
    # 注册用户必须自带 API Key（保护部署者额度），除非显式放开此开关。
    llm_server_fallback_registered: bool = False

    # ---------- 邮箱（注册验证 / 找回密码）----------
    smtp_host: str = ""            # 如 smtp.qq.com 或 smtpdm.aliyun.com；留空 = 未启用邮件
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""        # QQ/163 邮箱填授权码，不是登录密码
    smtp_from: str = ""            # 发件人显示，如 "Nova Agent <xxx@qq.com>"
    smtp_ssl: bool = True          # 465 端口用 SSL；587 端口请设 false（走 STARTTLS）
    email_verify_required: bool = True   # 邮件服务启用后，注册是否必须邮箱验证码
    email_code_ttl_minutes: int = 10

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.smtp_from)

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

    # ---------- Builder ----------
    # Boot generated projects in a throwaway container after approval
    # (health check, then immediate teardown) — "runs" beats "compiles".
    builder_smoke_enabled: bool = True

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

    # ---------- Night queue ----------
    night_queue_enabled: bool = True
    night_window_start: int = 0       # local server hour, inclusive
    night_window_end: int = 8         # exclusive; items run serially inside the window
    night_max_per_hour: int = 3       # items dispatched per maintenance tick
    night_budget_reserve: float = 0.2 # stop dispatching above 80% of the daily token budget

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
    downloads_dir: str = "data/downloads"   # 桌面客户端安装包目录，挂载到 /downloads

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