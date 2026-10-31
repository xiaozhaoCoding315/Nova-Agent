import pytest

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
    s = _fresh(llm_model_priority="zhipu,deepseek")
    assert s.llm_priority_list == ["zhipu", "deepseek"]


def test_llm_configured_flag():
    assert not _fresh(
        deepseek_api_key="", dashscope_api_key="", zhipu_api_key="", anthropic_api_key="",
    ).llm_configured
    assert _fresh(
        deepseek_api_key="", dashscope_api_key="", zhipu_api_key="sk-x", anthropic_api_key="",
    ).llm_configured


def test_quota_defaults():
    s = _fresh()
    assert s.demo_daily_tokens > 0
    assert s.admin_daily_tokens == 0          # 0 = unlimited
    assert s.demo_hourly_messages < s.admin_hourly_messages


def test_env_override_bool_and_int():
    s = _fresh(sandbox_enabled=False, max_rounds=3)
    assert s.sandbox_enabled is False
    assert s.max_rounds == 3


def test_local_mode_derived_flags():
    s = _fresh(nova_mode="local", nova_data_dir="C:/NovaData")
    assert s.is_local is True
    assert s.use_host_executor is True
    assert s.use_embeddings is False
    assert s.effective_job_max_concurrency == 1


def test_server_mode_defaults_are_unchanged():
    s = _fresh()
    assert s.nova_mode == "server"
    assert s.is_local is False
    assert s.use_host_executor is False
    assert s.use_embeddings is True
    assert s.effective_job_max_concurrency == 0


def test_local_mode_requires_data_dir():
    s = _fresh(nova_mode="local", nova_data_dir="")
    with pytest.raises(RuntimeError, match="NOVA_DATA_DIR"):
        _ = s.data_root


def test_local_tmp_root_defaults_under_data_dir():
    s = _fresh(nova_mode="local", nova_data_dir="C:/NovaData")
    assert s.local_tmp_root == s.data_root / "tmp"


def test_dsn_override_switches_database_names():
    from psycopg.conninfo import conninfo_to_dict

    s = _fresh(
        postgres_dsn_override="postgresql://nova:pw@127.0.0.1:55432/nova_agent?connect_timeout=3"
    )
    assert s.postgres_dsn == (
        "postgresql://nova:pw@127.0.0.1:55432/nova_agent?connect_timeout=3"
    )
    admin = conninfo_to_dict(s.postgres_admin_dsn)
    assert admin["dbname"] == "postgres"
    # psycopg 3.2 (pinned) returns conninfo values as strings for string input.
    assert int(admin["port"]) == 55432
