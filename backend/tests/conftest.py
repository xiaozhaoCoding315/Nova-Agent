import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires live DB at 192.168.150.128")

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
