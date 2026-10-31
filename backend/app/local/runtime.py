"""Local-mode setting validation. Called from the FastAPI lifespan."""
from pathlib import Path

from app.config import settings

DEFAULT_SECRET = "change-me-in-production"


def validate_local_settings() -> None:
    if not settings.is_local:
        return
    if len(settings.secret_key) < 32 or settings.secret_key == DEFAULT_SECRET:
        raise RuntimeError(
            "local mode requires a generated SECRET_KEY "
            "(start with `python nova.py local`, not bare uvicorn)"
        )
    root = settings.data_root
    root.mkdir(parents=True, exist_ok=True)
    settings.local_tmp_root.mkdir(parents=True, exist_ok=True)
    Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
