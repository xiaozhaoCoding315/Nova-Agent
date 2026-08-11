"""Structured logging: console always, rotating file in production."""
import logging
import logging.handlers
from pathlib import Path
import structlog
from app.config import settings


def setup_logging() -> None:
    """Configure structlog + stdlib logging.

    Console handler always; TimedRotatingFileHandler when app_env == "prod".
    Idempotent — safe to call multiple times. `logging.basicConfig` is a no-op
    once the root logger has ANY handler, so handlers are attached directly:
    existing handlers of the types we manage are removed first, then re-added.
    """
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    target = log_dir / "app.log"
    level = getattr(logging, settings.log_level, logging.INFO)

    root = logging.getLogger()

    # Drop handlers we manage (console + prod rotating file) so repeated
    # setup doesn't stack duplicates, then re-add a single set below.
    for handler in list(root.handlers):
        if isinstance(handler, logging.StreamHandler) or isinstance(
            handler, logging.handlers.TimedRotatingFileHandler
        ):
            root.removeHandler(handler)
            handler.close()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(stream_handler)

    if settings.app_env == "prod":
        file_handler = logging.handlers.TimedRotatingFileHandler(
            target,
            when="midnight",
            backupCount=7,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(file_handler)

    root.setLevel(level)

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level, logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
