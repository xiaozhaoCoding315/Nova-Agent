from app.config import Settings


def test_settings_defaults():
    s = Settings()
    assert s.postgres_host == "192.168.150.128"
    assert s.qdrant_port == 6333
    assert s.neo4j_port == 7687


def test_llm_priority_parsing():
    s = Settings(llm_model_priority="longcat,deepseek")
    assert s.llm_priority_list == ["longcat", "deepseek"]


def test_connection_urls():
    s = Settings()
    assert s.qdrant_url == "http://192.168.150.128:6333"
    assert "postgresql://" in s.postgres_dsn
    assert s.neo4j_uri == "bolt://192.168.150.128:7687"
