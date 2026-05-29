"""Memory — working memory: per-task scratchpad, cleared on completion."""

import asyncio


class WorkingMemory:
    def __init__(self, max_bytes: int = 10 * 1024 * 1024) -> None:
        self._lock = asyncio.Lock()
        self._store: dict[str, str] = {}

    async def put(self, key: str, value: str) -> None:
        async with self._lock: self._store[key] = value

    async def get(self, key: str) -> str | None:
        async with self._lock: return self._store.get(key)

    async def snapshot(self) -> dict[str, str]:
        async with self._lock: return dict(self._store)

    async def clear(self) -> None:
        async with self._lock: self._store.clear()
