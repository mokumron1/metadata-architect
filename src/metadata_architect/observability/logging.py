"""
Structured logging setup.

Configures structlog with JSON rendering for production and
pretty-printed console output for development.

Call configure_logging() once at app startup (done in api/main.py).
"""

import logging
import os
import sys


def configure_logging() -> None:
    """Configure structlog + stdlib logging for the application."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    is_dev = os.getenv("ENV", "production").lower() in {"development", "dev", "local"}

    try:
        import structlog

        shared_processors = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
        ]

        if is_dev:
            renderer = structlog.dev.ConsoleRenderer()
        else:
            renderer = structlog.processors.JSONRenderer()

        structlog.configure(
            processors=shared_processors + [
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, log_level, logging.INFO)
            ),
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
            foreign_pre_chain=shared_processors,
        )

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)

        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(log_level)

        # Silence noisy third-party loggers
        for noisy in ("uvicorn.access", "httpx", "httpcore", "sqlalchemy.engine"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    except ImportError:
        # structlog not available — fall back to stdlib
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            stream=sys.stdout,
        )
