"""v2.0 MemorySystem — unified facade over four memory tiers.

Wraps working, short-term, long-term, and procedural memory behind a single interface.
Supports __getitem__ for backward compatibility (ctx.memory["long_term"]).

Usage:
    mem = MemorySystem(config.memory)
    await mem.short_term.put("key", "value")
    mem.procedural.record("read_file", ("/path",), "content")
    is_valid, reason = mem.procedural.validate_before_use("read_file", ("/path",))
"""

from __future__ import annotations

from hivemind.config import MemoryConfig
from hivemind.memory.consistency import ConsistencyManager
from hivemind.memory.long_term import LongTermMemory
from hivemind.memory.procedural import ProceduralMemory
from hivemind.memory.short_term import ShortTermMemory
from hivemind.memory.working import WorkingMemory


class MemorySystem:
    """Unified memory facade aggregating all four tiers."""

    def __init__(self, config: MemoryConfig) -> None:
        self.working = WorkingMemory(max_bytes=config.working.max_bytes)
        self.short_term = ShortTermMemory(
            max_items=config.short_term.max_items,
            default_ttl=config.short_term.default_ttl_seconds,
        )
        self.long_term = LongTermMemory(
            persistence_path=config.long_term.persistence_path,
        )
        self.procedural = ProceduralMemory(
            max_records=config.procedural.max_records,
            env_tolerance=config.procedural.env_tolerance,
            persistence_path=config.procedural.persistence_path,
            promote_after=config.procedural.promote_after,
            max_failures_before_demote=config.procedural.max_failures_before_demote,
        )
        self.consistency = ConsistencyManager()

    # ── Backward Compatibility ─────────────────────────────────

    def __getitem__(self, key: str):
        """Support ctx.memory["long_term"], ctx.memory["short_term"], etc."""
        if key == "long_term":
            return self.long_term
        if key == "short_term":
            return self.short_term
        if key == "working":
            return self.working
        if key == "procedural":
            return self.procedural
        raise KeyError(f"Unknown memory tier: {key}")

    # ── Cross-tier Operations ─────────────────────────────────

    async def search_all(self, query: str, limit: int = 10) -> list[dict]:
        """Search across short-term and long-term memory."""
        results: list[dict] = []

        # short-term first (more relevant)
        st_results = await self.short_term.search(query)
        for r in st_results[:limit]:
            results.append({"tier": "short_term", **(r.model_dump() if hasattr(r, 'model_dump') else r)})

        # long-term fallback
        remaining = limit - len(results)
        if remaining > 0:
            lt_results = await self.long_term.search(query)
            for r in lt_results[:remaining]:
                results.append({"tier": "long_term", **(r.model_dump() if hasattr(r, 'model_dump') else r)})

        return results

    async def store_cross_tier(self, key: str, value: str, ttl: int | None = None) -> None:
        """Store in both short-term and long-term memory."""
        await self.short_term.store(key, value, ttl_seconds=ttl)
        await self.long_term.store(key, value)

    # ── Procedural Delegates ──────────────────────────────────

    def record_procedural(
        self,
        tool_name: str,
        params: tuple,
        result_data: str,
        success: bool = True,
        latency_ms: float = 0.0,
    ):
        """Delegate to ProceduralMemory.record()."""
        return self.procedural.record(tool_name, params, result_data, success, latency_ms)

    def validate_procedural(self, tool_name: str, params: tuple) -> tuple[bool, str]:
        """Delegate to ProceduralMemory.validate_before_use()."""
        return self.procedural.validate_before_use(tool_name, params)
