"""Memory — long-term memory: JSON file-backed persistent store."""

import asyncio
import json
import os
from datetime import datetime, timezone
from hivemind.memory.short_term import MemoryEntry


class LongTermMemory:
    def __init__(self, persistence_path: str = "~/.hivemind/long_term_memory.json") -> None:
        self._path = os.path.expanduser(persistence_path)
        self._lock = asyncio.Lock()
        self._store: dict[str, MemoryEntry] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path): return
        try:
            with open(self._path) as f:
                data = json.load(f)
            self._store = {k: MemoryEntry(**v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError): pass

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as f:
            json.dump({k: v.model_dump() for k, v in self._store.items()}, f, indent=2, default=str)

    async def store(self, key: str, value: str, metadata: dict | None = None) -> MemoryEntry:
        entry = MemoryEntry(key=key, value=value, metadata=metadata or {})
        async with self._lock: self._store[key] = entry; self._save()
        return entry

    async def retrieve(self, key: str) -> MemoryEntry | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry:
                entry.access_count += 1
                entry.last_accessed = datetime.now(timezone.utc).isoformat()
            return entry

    async def search(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        async with self._lock:
            results = [e for e in self._store.values()
                       if query.lower() in e.key.lower() or query.lower() in e.value.lower()]
            results.sort(key=lambda e: e.access_count, reverse=True)
            return results[:limit]

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._store: del self._store[key]; self._save(); return True
            return False

    async def list_keys(self, prefix: str = "") -> list[str]:
        async with self._lock:
            return sorted(k for k in self._store if k.startswith(prefix))
