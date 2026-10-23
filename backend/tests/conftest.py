"""Shared pytest configuration.

Integration tests (marked ``integration``) talk to the live PostgreSQL /
Qdrant instances. They are skipped automatically when those services are
unreachable, so a plain ``pytest`` run works offline.
"""
import socket

import pytest

from app.config import settings


def _reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


_services_available: bool | None = None


def _services_up() -> bool:
    global _services_available
    if _services_available is None:
        _services_available = (
            _reachable(settings.postgres_host, settings.postgres_port)
            and _reachable(settings.qdrant_host, settings.qdrant_port)
        )
    return _services_available


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: requires live PostgreSQL + Qdrant (auto-skipped when unreachable)",
    )


def pytest_collection_modifyitems(config, items):
    if _services_up():
        return
    skip_marker = pytest.mark.skip(
        reason=f"PostgreSQL/Qdrant unreachable at {settings.postgres_host} / {settings.qdrant_host}"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_marker)