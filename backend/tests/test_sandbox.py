import pytest
from app.core.sandbox.config import SANDBOX_CONFIG, SandboxConfig
from app.core.sandbox.runtime import is_docker_available


def test_sandbox_config_defaults():
    assert SANDBOX_CONFIG.network_disabled is True
    assert SANDBOX_CONFIG.read_only_root is True
    assert SANDBOX_CONFIG.drop_all_capabilities is True
    assert SANDBOX_CONFIG.no_new_privileges is True
    assert SANDBOX_CONFIG.cpu_limit == "0.5"
    assert SANDBOX_CONFIG.memory_limit == "256m"
    assert SANDBOX_CONFIG.timeout_seconds == 30


def test_sandbox_config_custom():
    cfg = SandboxConfig(cpu_limit="1.0", memory_limit="512m", timeout_seconds=60)
    assert cfg.cpu_limit == "1.0"
    assert cfg.memory_limit == "512m"


def test_docker_detection_runs():
    """Should not crash regardless of Docker availability."""
    result = is_docker_available()
    assert isinstance(result, bool)
