"""AppContext — shared state available to all MCP tools via lifespan."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hivemind.config import HiveMindConfig


@dataclass
class AppContext:
    """Typed application context injected into every tool via FastMCP lifespan.

    All subsystems are initialized once at server startup and reused across
    all tool invocations.  Mutable state (rate-limiter buckets, memory stores,
    metrics) lives within each subsystem instance.
    """

    config: HiveMindConfig
    logger: Any  # structlog.BoundLogger or logging.Logger

    # Lazy-initialised subsystems — set after construction
    gateway: object = field(default=None, repr=False)
    commander: object = field(default=None, repr=False)
    executors: object = field(default=None, repr=False)
    verifier: object = field(default=None, repr=False)
    memory: object = field(default=None, repr=False)
    metrics: object = field(default=None, repr=False)
