from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ---------- LLM ----------
    llm_model_priority: str = "zhipu,dashscope,deepseek,anthropic"
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_model: str = "glm-4.7-flash"
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "qwen3.8-max"
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-sonnet-5-5"
    anthropic_max_tokens: int = 8192
    anthropic_prompt_caching: bool = True
    anthropic_context_window: int = 200_000
    llm_timeout: int = 300         # seconds per LLM call (长任务的生成可能持续数分钟)
    task_llm_timeout: int = 180    # red-green task generation is heavier (thinking models)
    max_rounds: int = 16           # 每段工具调用轮次（触顶后自动续段，见 max_continuations）
    max_continuations: int = 6     # 段触顶后自动注入"继续"指令的次数（长任务不断档）
    turn_timeout: int = 3600       # 单轮任务总时长上限（秒），到点暂停并可手动继续
    subagent_max_tasks: int = 4          # spawn_agents 单次任务数上限
    subagent_max_parallel: int = 3       # 同时运行的子代理数
    subagent_max_rounds: int = 8         # 每个子代理最多工具轮次
    subagent_timeout: int = 300          # 每个子代理总时长（秒）
    subagent_turn_limit: int = 8         # 单轮对话内子代理任务总数
    subagent_summary_chars: int = 4000   # 单个子代理返回给父代理的摘要上限
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
        return bool(
            self.zhipu_api_key or self.deepseek_api_key
            or self.dashscope_api_key or self.anthropic_api_key
        )

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
    # None = auto: secure whenever the request arrived over HTTPS (direct or
    # through a trusted proxy). Explicit true/false overrides the detection.
    cookie_secure: bool | None = None
    # 反代地址白名单：只有来自这些来源的 X-Forwarded-For/Proto 才被采信。
    # 直连公网时留空，任何客户端伪造的转发头都会被忽略。
    trusted_proxies: str = ""
    admin_username: str = "admin"
    admin_password: str = ""
    demo_username: str = "demo"
    demo_password: str = ""
    # Account lifecycle: open | invite | closed
    registration_mode: str = "open"
    registration_invite_code: str = ""
    max_registrations_per_hour: int = 10
    # 每小时允许的失败登录次数，按来源 IP 与「IP + 账号」各算一次；0 = 关闭。
    max_login_attempts_per_hour: int = 20
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
    image_input_max_kb: int = 3584
    image_input_max_side: int = 8000
    image_input_max_pixels: int = 40_000_000
    image_input_max_total_kb: int = 10_240

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
    # 可选：app 运行在容器内时，容器数据目录对应的宿主机路径。
    # 留空则自动通过 docker inspect 读取自身挂载；无法探测时按宿主机运行处理。
    sandbox_host_data_dir: str = ""
    sandbox_mask_secrets: bool = True     # auto/full 写命令遮蔽密钥文件

    # ---------- Tools ----------
    enable_fetch_url: bool = True
    fetch_url_max_kb: int = 512
    # 逗号分隔的域名 allowlist；为空表示任意公网域名（仍受只读/确认模式门禁）
    fetch_url_allowed_domains: str = ""
    # 联网搜索：默认 DuckDuckGo（无需 Key）；也可用 Brave Search API。
    enable_web_search: bool = True
    web_search_provider: str = "auto"   # auto | bing | duckduckgo | brave
    web_search_api_key: str = ""
    web_search_max_results: int = 6
    web_search_timeout: int = 20

    # ---------- Skills ----------
    skills_enabled: bool = True
    skills_dir: str = "data/skills"   # <dir>/<skill-name>/SKILL.md, operator-provided

    # ---------- Tool hooks / policy ----------
    tool_pre_hook: str = ""       # executable command; JSON payload on stdin; exit 2 blocks
    tool_post_hook: str = ""      # best-effort post-tool audit hook
    shell_readonly_allowlist: bool = True   # readonly/ask 下放行只读 shell 命令
    tool_result_max_chars: int = 12_000     # 单条工具结果的字符预算
    # 单元测试快速档：跳过 trace/audit/usage 的 DB 写入
    nova_test_fast: bool = False

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

    # ---------- Local runtime ----------
    # server = 现有云端行为；local = 本机单用户运行时。
    nova_mode: Literal["server", "local"] = "server"
    nova_data_dir: str = ""
    local_user: str = "local"
    local_tmp_dir: str = ""
    local_pg_backend: Literal["pgserver", "pg_ctl"] = "pgserver"
    local_pg_bin_dir: str = ""
    local_pg_port: int = 0
    local_allow_install_deps: bool = False
    postgres_dsn_override: str = ""
    embeddings_enabled: bool = True
    job_max_concurrency: int = 0     # 0 = 沿用各 kind 自己的并发上限

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
        if self.postgres_dsn_override:
            return self.postgres_dsn_override
        return (f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
                f"?connect_timeout=3")

    @property
    def postgres_admin_dsn(self) -> str:
        """DSN against the maintenance DB, used to CREATE DATABASE on first run."""
        if self.postgres_dsn_override:
            return self._dsn_with_db(self.postgres_dsn_override, "postgres")
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

    @property
    def trusted_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    def is_trusted_proxy(self, host: str | None) -> bool:
        """转发头只采信来自反代的请求。

        8000 端口默认直接暴露在公网，若无条件相信 X-Forwarded-For，任何人
        只要改一个请求头就能伪装成新 IP，绕过注册限流与游客一次性限制。
        只有运维显式配置了 TRUSTED_PROXIES（例如 Caddy 容器网段）才放行。
        `*` 表示信任所有来源，仅当 app 端口已只监听回环地址时才该使用。
        """
        if not host:
            return False
        trusted = self.trusted_proxy_list
        return "*" in trusted or host in trusted

    @property
    def is_local(self) -> bool:
        return self.nova_mode == "local"

    @property
    def use_host_executor(self) -> bool:
        """Local mode runs commands on the host; cloud mode keeps Docker."""
        return self.is_local

    @property
    def use_embeddings(self) -> bool:
        """Local v1 has no Qdrant/embedding; cloud keeps dense retrieval."""
        return self.embeddings_enabled and not self.is_local

    @property
    def effective_job_max_concurrency(self) -> int:
        """0 = no global cap (existing per-kind limits); local = single worker."""
        return 1 if self.is_local else self.job_max_concurrency

    @property
    def data_root(self) -> Path:
        if not self.nova_data_dir:
            raise RuntimeError("NOVA_DATA_DIR is required when NOVA_MODE=local")
        return Path(self.nova_data_dir).expanduser().resolve()

    @property
    def local_tmp_root(self) -> Path:
        if self.local_tmp_dir:
            return Path(self.local_tmp_dir).expanduser().resolve()
        return self.data_root / "tmp"

    @staticmethod
    def _dsn_with_db(dsn: str, dbname: str) -> str:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        params = conninfo_to_dict(dsn)
        params["dbname"] = dbname
        return make_conninfo(**params)


settings = Settings()