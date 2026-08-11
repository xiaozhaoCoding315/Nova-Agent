"""Structured logging: console always, rotating file in production."""
import logging
import logging.handlers
from pathlib import Path
import structlog
from app.config import settings


def setup_logging() -> None:
    """Configure structlog + stdlib logging.

    Console handler always; TimedRotatingFileHandler when app_env == "prod".
    Idempotent — safe to call multiple times.
    """
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if settings.app_env == "prod":
        handlers.append(
            logging.handlers.TimedRotatingFileHandler(
                log_dir / "app.log",
                when="midnight",
                backupCount=7,
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level, logging.INFO),
        handlers=handlers,
    )

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
