"""Memory — working memory: per-task scratchpad, cleared on completion."""

import asyncio
import sys


class WorkingMemory:
    def __init__(self, max_bytes: int = 10 * 1024 * 1024) -> None:
        self._lock = asyncio.Lock()
        self._store: dict[str, str] = {}
        self.max_bytes = max_bytes

    async def put(self, key: str, value: str) -> None:
        async with self._lock:
            self._store[key] = value
            # evict oldest entries if over max_bytes
            while self._total_bytes() > self.max_bytes and len(self._store) > 1:
                oldest = min(self._store.keys(), key=lambda k: k)
                del self._store[oldest]

    async def get(self, key: str) -> str | None:
        async with self._lock: return self._store.get(key)

    async def snapshot(self) -> dict[str, str]:
        async with self._lock: return dict(self._store)

    async def clear(self) -> None:
        async with self._lock: self._store.clear()

    def _total_bytes(self) -> int:
        return sum(sys.getsizeof(k) + sys.getsizeof(v) for k, v in self._store.items())
