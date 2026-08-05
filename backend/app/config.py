from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_model_priority: str = "longcat,deepseek,dashscope"
    longcat_api_key: str = ""
    longcat_base_url: str = "https://api.longcat.chat/openai/v1"
    longcat_model: str = "LongCat-2.0"
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""

    qdrant_host: str = "192.168.150.128"
    qdrant_port: int = 6333

    postgres_host: str = "192.168.150.128"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "novatech"
    postgres_db: str = "novatech"

    neo4j_host: str = "192.168.150.128"
    neo4j_port: int = 7687
    neo4j_user: str = "neo4j"
    neo4j_password: str = "novatech123"

    embedding_provider: str = "dashscope"
    embedding_model: str = "text-embedding-v3"

    debug: bool = True
    log_level: str = "INFO"
    secret_key: str = "change-me"
    cors_origins: str = "http://localhost:5173"

    @property
    def llm_priority_list(self) -> list[str]:
        return [p.strip() for p in self.llm_model_priority.split(",") if p.strip()]

    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @property
    def neo4j_uri(self) -> str:
        return f"bolt://{self.neo4j_host}:{self.neo4j_port}"

    @property
    def postgres_dsn(self) -> str:
        return (f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
