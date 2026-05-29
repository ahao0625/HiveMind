"""Memory — short-term memory: in-memory key-value with TTL."""

import asyncio
import time
from datetime import datetime, timezone
from pydantic import BaseModel, Field


class MemoryEntry(BaseModel):
    key: str
    value: str
    metadata: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: float | None = None
    access_count: int = 0
    last_accessed: str | None = None


class ShortTermMemory:
    def __init__(self, max_items: int = 1000, default_ttl: int = 300) -> None:
        self._lock = asyncio.Lock()
        self._store: dict[str, MemoryEntry] = {}
        self._max_items = max_items
        self._default_ttl = default_ttl

    async def store(self, key: str, value: str, ttl_seconds: int | None = None,
                    metadata: dict | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        entry = MemoryEntry(key=key, value=value, metadata=metadata or {}, expires_at=time.monotonic() + ttl)
        async with self._lock:
            if len(self._store) >= self._max_items:
                oldest = min(self._store.values(), key=lambda e: e.created_at)
                del self._store[oldest.key]
            self._store[key] = entry

    async def retrieve(self, key: str) -> MemoryEntry | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None: return None
            if entry.expires_at and time.monotonic() > entry.expires_at:
                del self._store[key]; return None
            entry.access_count += 1
            entry.last_accessed = datetime.now(timezone.utc).isoformat()
            return entry

    async def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        results: list[MemoryEntry] = []
        async with self._lock:
            now = time.monotonic()
            for entry in self._store.values():
                if entry.expires_at and now > entry.expires_at: continue
                if query.lower() in entry.key.lower() or query.lower() in entry.value.lower():
                    results.append(entry)
            results.sort(key=lambda e: e.access_count, reverse=True)
            return results[:limit]
