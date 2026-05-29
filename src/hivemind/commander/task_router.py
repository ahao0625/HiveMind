"""Commander — task router: System 1 (fast cache) vs System 2 (full flow) dispatch.

v2.0: Optional procedural_memory parameter for env validation before cache reuse.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.commander.arbiter import Decision


class TaskRouter:
    """Routes intents: System1=cached results, System2=full gateway→executor→verification.

    v2.0: Accepts optional procedural_memory reference for future env-aware caching.
    """

    def __init__(self, default_ttl: int = 300, procedural_memory: Any = None) -> None:
        self._lock = asyncio.Lock()
        self._cache: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._procedural_memory = procedural_memory  # v2.0: reserved for env-aware routing

    async def try_system1(self, intent: RefinedIntent, decision: Decision) -> Any | None:
        if decision.execution_mode != "system1": return None
        cache_key = self._make_key(intent)
        async with self._lock:
            entry = self._cache.get(cache_key)
            if entry is not None:
                value, expires_at = entry
                if time.monotonic() < expires_at: return value
                del self._cache[cache_key]
        return None

    async def cache_result(self, intent: RefinedIntent, result: Any, ttl: int | None = None) -> None:
        cache_key = self._make_key(intent)
        ttl = ttl or self._default_ttl
        async with self._lock:
            self._cache[cache_key] = (result, time.monotonic() + ttl)
            if len(self._cache) > 1000:
                oldest = min(self._cache.items(), key=lambda x: x[1][1])
                del self._cache[oldest[0]]

    async def invalidate(self, tool_name: str) -> None:
        async with self._lock:
            to_del = [k for k in self._cache if tool_name in k]
            for k in to_del: del self._cache[k]

    @staticmethod
    def _make_key(intent: RefinedIntent) -> str:
        raw = json.dumps({"tool": intent.tool_name, "params": dict(sorted(intent.parameters.items()))},
                         sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]
