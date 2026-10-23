from app.config import Settings


def _fresh(**overrides) -> Settings:
    """Settings built from explicit values only (ignore any local .env)."""
    return Settings(_env_file=None, **overrides)


def test_defaults_are_localhost_not_lan():
    s = _fresh()
    assert s.postgres_host == "localhost"
    assert s.qdrant_host == "localhost"
    assert s.postgres_db == "nova_agent"
    assert s.qdrant_collection == "code_chunks"


def test_connection_urls():
    s = _fresh(postgres_host="db", qdrant_host="vec")
    assert s.qdrant_url == "http://vec:6333"
    assert "postgresql://" in s.postgres_dsn
    assert s.postgres_admin_dsn.endswith("/postgres?connect_timeout=3")


def test_llm_priority_parsing():
    s = _fresh(llm_model_priority="longcat,deepseek")
    assert s.llm_priority_list == ["longcat", "deepseek"]


def test_llm_configured_flag():
    assert not _fresh(deepseek_api_key="", dashscope_api_key="", longcat_api_key="").llm_configured
    assert _fresh(deepseek_api_key="sk-x", dashscope_api_key="", longcat_api_key="").llm_configured


def test_quota_defaults():
    s = _fresh()
    assert s.demo_daily_tokens > 0
    assert s.admin_daily_tokens == 0          # 0 = unlimited
    assert s.demo_hourly_messages < s.admin_hourly_messages


def test_env_override_bool_and_int():
    s = _fresh(sandbox_enabled=False, max_rounds=3)
    assert s.sandbox_enabled is False
    assert s.max_rounds == 3