"""Gateway — structured audit logger."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    identity: str
    tool_name: str
    params_hash: str
    gateway_result: str  # "passed" | "blocked"
    arbiter_decision: str  # "approved" | "blocked" | "human_required"
    executor_result: str  # "success" | "failure" | "skipped"
    verification_result: str  # "passed" | "failed" | "skipped"
    duration_ms: float = 0.0
    trace_id: str = ""
    summary: str = ""


class AuditLogger:
    """Records every tool invocation into an in-memory ring buffer."""

    def __init__(self, max_entries: int = 10000) -> None:
        self._lock = asyncio.Lock()
        self._events: deque[AuditEvent] = deque(maxlen=max_entries)

    async def record(self, event: AuditEvent) -> None:
        async with self._lock:
            self._events.append(event)

    async def recent(self, limit: int = 50) -> list[AuditEvent]:
        async with self._lock:
            items = list(self._events)[-limit:]
            return list(reversed(items))
