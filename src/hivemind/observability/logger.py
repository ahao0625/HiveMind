"""Structured logger for HiveMind — structlog when available, stdlib fallback."""

from __future__ import annotations

import logging
import os
import sys

try:
    import structlog as _structlog
    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False


def setup_logger(name: str = "hivemind", level: int = logging.INFO):
    """Return a configured logger (structlog if available, else stdlib).

    In development, outputs pretty-printed console logs.
    In production (JSON_LOG=1), outputs newline-delimited JSON.
    """
    if HAS_STRUCTLOG:
        if os.environ.get("JSON_LOG"):
            _structlog.configure(
                processors=[
                    _structlog.stdlib.filter_by_level,
                    _structlog.stdlib.add_logger_name,
                    _structlog.stdlib.add_log_level,
                    _structlog.stdlib.PositionalArgumentsFormatter(),
                    _structlog.processors.TimeStamper(fmt="iso"),
                    _structlog.processors.StackInfoRenderer(),
                    _structlog.processors.format_exc_info,
                    _structlog.processors.UnicodeDecoder(),
                    _structlog.processors.JSONRenderer(),
                ],
                context_class=dict,
                logger_factory=_structlog.stdlib.LoggerFactory(),
                wrapper_class=_structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=True,
            )
        else:
            _structlog.configure(
                processors=[
                    _structlog.stdlib.filter_by_level,
                    _structlog.stdlib.add_logger_name,
                    _structlog.stdlib.add_log_level,
                    _structlog.stdlib.PositionalArgumentsFormatter(),
                    _structlog.processors.TimeStamper(fmt="%H:%M:%S"),
                    _structlog.dev.ConsoleRenderer(colors=True),
                ],
                context_class=dict,
                logger_factory=_structlog.stdlib.LoggerFactory(),
                wrapper_class=_structlog.stdlib.BoundLogger,
                cache_logger_on_first_use=True,
            )
        return _structlog.get_logger(name)

    # Stdlib fallback
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(h)
    logger.setLevel(level)
    return logger
