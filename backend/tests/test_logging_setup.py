import logging
import os
import tempfile
from pathlib import Path


def test_logging_setup_creates_file_in_prod(monkeypatch):
    import app.core.logging_setup as ls
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setattr("app.config.settings.app_env", "prod")
    monkeypatch.setattr("app.config.settings.log_dir", tmpdir)
    try:
        ls.setup_logging()
        log_file = Path(tmpdir) / "app.log"
        assert log_file.exists()
    finally:
        # Reset root handlers so the tmpdir file handler doesn't leak
        # into other tests (e.g. app.main's lifespan setup).
        logging.getLogger().handlers.clear()

