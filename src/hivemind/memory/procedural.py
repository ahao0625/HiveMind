"""v2.0 Procedural Memory — env snapshots for '越用越快' (faster with use).

Stores execution records paired with environment snapshots. Before reusing a cached
result (system1 fast path), validate_before_use() checks that the environment hasn't
changed — if dependencies differ, the record is demoted and system2 full verification
is triggered instead.

Persistence: atomic writes via temp file + os.replace to prevent corruption.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


# ── Data Models ──────────────────────────────────────────────────


class EnvSnapshot(BaseModel, frozen=True):
    """Frozen snapshot of the execution environment."""
    os_name: str
    os_version: str
    python_version: str
    installed_packages: tuple[str, ...] = ()
    key_env_vars: tuple[str, ...] = ()  # names only, not values (security)


class GameRecord(BaseModel, frozen=True):
    """A single procedural memory record — one successful tool execution."""
    key: str  # composite: tool_name:params_hash
    tool_name: str
    params_hash: str
    env_snapshot: EnvSnapshot
    result_hash: str
    success: bool = True
    latency_ms: float = 0.0
    use_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── ProceduralMemory ─────────────────────────────────────────────


class ProceduralMemory:
    """Stores execution traces paired with env snapshots.

    Lifecycle:
      - On success → record() stores a GameRecord
      - On system1 cache hit → validate_before_use() checks env consistency
      - N successes → promote() to cache
      - M env mismatches → demote() to force system2
    """

    def __init__(
        self,
        max_records: int = 500,
        env_tolerance: int = 2,
        persistence_path: str = "~/.hivemind/procedural_memory.json",
        promote_after: int = 3,
        max_failures_before_demote: int = 2,
    ) -> None:
        self.max_records = max_records
        self.env_tolerance = env_tolerance
        self.persistence_path = os.path.expanduser(persistence_path)
        self.promote_after = promote_after
        self.max_failures_before_demote = max_failures_before_demote
        self._records: dict[str, GameRecord] = {}
        self._load()

    # ── Environment Snapshotting ──────────────────────────────

    @staticmethod
    def snapshot_environment() -> EnvSnapshot:
        """Capture the current execution environment."""
        try:
            import importlib.metadata as im

            pkgs = tuple(
                sorted(f"{dist.metadata['Name']}=={dist.version}" for dist in im.distributions())
            )
        except Exception:
            pkgs = ()

        return EnvSnapshot(
            os_name=platform.system(),
            os_version=platform.release(),
            python_version=sys.version.split()[0],
            installed_packages=pkgs[:200],  # cap for performance
            key_env_vars=(
                "PATH", "HOME", "PYTHONPATH", "VIRTUAL_ENV",
                "CONDA_DEFAULT_ENV", "NODE_ENV", "JAVA_HOME",
            ),
        )

    # ── CRUD ──────────────────────────────────────────────────

    def record(
        self,
        tool_name: str,
        params: tuple,
        result_data: str,
        success: bool = True,
        latency_ms: float = 0.0,
    ) -> GameRecord:
        """Record a successful execution with env snapshot."""
        params_hash = _hash_str(str(params))
        key = f"{tool_name}:{params_hash}"
        env = self.snapshot_environment()
        result_hash = _hash_str(result_data)

        existing = self._records.get(key)
        if existing is not None:
            record = GameRecord(
                key=key,
                tool_name=tool_name,
                params_hash=params_hash,
                env_snapshot=env,
                result_hash=result_hash,
                success=success,
                latency_ms=latency_ms,
                use_count=existing.use_count + 1,
                created_at=existing.created_at,
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
        else:
            record = GameRecord(
                key=key,
                tool_name=tool_name,
                params_hash=params_hash,
                env_snapshot=env,
                result_hash=result_hash,
                success=success,
                latency_ms=latency_ms,
                use_count=1,
            )

        self._records[key] = record
        self._evict_if_needed()
        self._save()
        return record

    def get(self, tool_name: str, params: tuple) -> GameRecord | None:
        """Look up a cached record by tool + params."""
        key = f"{tool_name}:{_hash_str(str(params))}"
        return self._records.get(key)

    def validate_before_use(self, tool_name: str, params: tuple) -> tuple[bool, str]:
        """Check if cached record's env matches current env.

        Returns:
            (is_valid, reason) — True if env diff is within tolerance.
        """
        record = self.get(tool_name, params)
        if record is None:
            return False, "no_cached_record"

        current = self.snapshot_environment()
        diff_count = self._env_diff_count(record.env_snapshot, current)

        if diff_count <= self.env_tolerance:
            return True, "env_match"
        else:
            self.demote(tool_name, params)
            return False, f"env_diverged({diff_count} diffs > {self.env_tolerance})"

    def promote(self, tool_name: str, params: tuple) -> GameRecord | None:
        """Increment use_count; records with enough successes get cached longer."""
        key = f"{tool_name}:{_hash_str(str(params))}"
        record = self._records.get(key)
        if record is None:
            return None
        new_record = GameRecord(
            key=record.key,
            tool_name=record.tool_name,
            params_hash=record.params_hash,
            env_snapshot=record.env_snapshot,
            result_hash=record.result_hash,
            success=record.success,
            latency_ms=record.latency_ms,
            use_count=record.use_count + 1,
            created_at=record.created_at,
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        self._records[key] = new_record
        self._save()
        return new_record

    def demote(self, tool_name: str, params: tuple) -> None:
        """Remove a record that failed validation."""
        key = f"{tool_name}:{_hash_str(str(params))}"
        self._records.pop(key, None)
        self._save()

    def get_best_match(self, tool_name: str, params: tuple) -> GameRecord | None:
        """Find the best matching record by tool and params similarity."""
        params_hash = _hash_str(str(params))
        # exact match first
        key = f"{tool_name}:{params_hash}"
        if key in self._records:
            return self._records[key]

        # fallback to same tool, highest use_count
        candidates = [
            r for r in self._records.values()
            if r.tool_name == tool_name and r.success
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.use_count)

    # ── Internal ──────────────────────────────────────────────

    @staticmethod
    def _env_diff_count(old: EnvSnapshot, new: EnvSnapshot) -> int:
        """Count how many env fields differ between two snapshots."""
        diffs = 0
        if old.os_name != new.os_name:
            diffs += 1
        if old.os_version != new.os_version:
            diffs += 1
        if old.python_version != new.python_version:
            diffs += 1
        # compare package sets (ignore order)
        old_pkgs = set(old.installed_packages)
        new_pkgs = set(new.installed_packages)
        if old_pkgs != new_pkgs:
            diffs += 1
        return diffs

    def _evict_if_needed(self) -> None:
        """Remove oldest records if over capacity."""
        while len(self._records) > self.max_records:
            oldest = min(
                self._records.values(),
                key=lambda r: r.created_at,
            )
            del self._records[oldest.key]

    def _save(self) -> None:
        """Atomic save to prevent JSON corruption on crash."""
        dir_path = os.path.dirname(self.persistence_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        data = {
            key: record.model_dump()
            for key, record in self._records.items()
        }
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(self.persistence_path) or None,
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(tmp_path, self.persistence_path)
        except Exception:
            os.unlink(tmp_path)
            raise

    def _load(self) -> None:
        """Load persisted records."""
        if not os.path.exists(self.persistence_path):
            return
        try:
            with open(self.persistence_path) as f:
                data = json.load(f)
            for key, raw in data.items():
                env = EnvSnapshot(**raw["env_snapshot"])
                self._records[key] = GameRecord(
                    key=raw["key"],
                    tool_name=raw["tool_name"],
                    params_hash=raw["params_hash"],
                    env_snapshot=env,
                    result_hash=raw["result_hash"],
                    success=raw.get("success", True),
                    latency_ms=raw.get("latency_ms", 0.0),
                    use_count=raw.get("use_count", 0),
                    created_at=raw.get("created_at", ""),
                    updated_at=raw.get("updated_at", ""),
                )
        except (json.JSONDecodeError, KeyError, TypeError):
            # corrupt file → start fresh
            self._records = {}


# ── Helpers ──────────────────────────────────────────────────────


def _hash_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:16]
