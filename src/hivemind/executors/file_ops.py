"""Executor — safe file operations within sandbox root directory."""

from __future__ import annotations

import os
import time

from hivemind.config import FileOpsConfig
from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.executors.base import Executor, ExecutorResult


class FileOpsExecutor(Executor):
    """Read/write/delete/list files within a configured sandbox root."""

    def __init__(self, config: FileOpsConfig) -> None:
        self._root = os.path.realpath(os.path.expanduser(config.root_dir))
        self._max_size = config.max_file_size_mb * 1024 * 1024
        self._allowed_exts = set(config.allowed_extensions)
        os.makedirs(self._root, exist_ok=True)

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in ("read_file", "write_file", "delete_file", "list_files")

    async def execute(self, intent: RefinedIntent) -> ExecutorResult:
        t0 = time.monotonic()
        try:
            if intent.tool_name == "read_file":
                result = self._read(intent.parameters.get("path", ""))
            elif intent.tool_name == "write_file":
                result = self._write(intent.parameters.get("path", ""), intent.parameters.get("content", ""))
            elif intent.tool_name == "delete_file":
                result = self._delete(intent.parameters.get("path", ""))
            elif intent.tool_name == "list_files":
                result = self._list_dir(intent.parameters.get("path", "."))
            else:
                return ExecutorResult(success=False, error=f"Unknown file op: {intent.tool_name}")
        except Exception as exc:
            return ExecutorResult(success=False, error=str(exc), duration_ms=(time.monotonic() - t0) * 1000)
        result.duration_ms = (time.monotonic() - t0) * 1000
        return result

    def _resolve(self, path: str) -> str:
        full = os.path.realpath(os.path.join(self._root, path))
        if not full.startswith(self._root + os.sep) and full != self._root:
            raise ValueError(f"Path '{path}' is outside sandbox root")
        return full

    def _read(self, path: str) -> ExecutorResult:
        if not path: return ExecutorResult(success=False, error="path is required")
        full = self._resolve(path)
        if not os.path.exists(full): return ExecutorResult(success=False, error=f"File not found: {path}")
        if os.path.getsize(full) > self._max_size: return ExecutorResult(success=False, error="File too large")
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return ExecutorResult(success=True, output=content, metadata={"path": path, "size": len(content)})

    def _write(self, path: str, content: str) -> ExecutorResult:
        if not path: return ExecutorResult(success=False, error="path is required")
        full = self._resolve(path)
        ext = os.path.splitext(path)[1].lower()
        if ext and ext not in self._allowed_exts:
            return ExecutorResult(success=False, error=f"Extension '{ext}' not allowed")
        if len(content.encode("utf-8")) > self._max_size:
            return ExecutorResult(success=False, error="Content exceeds max file size")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return ExecutorResult(success=True, output=f"Written {len(content)} bytes to {path}",
                              metadata={"path": path, "bytes": len(content)})

    def _delete(self, path: str) -> ExecutorResult:
        if not path: return ExecutorResult(success=False, error="path is required")
        full = self._resolve(path)
        if not os.path.exists(full): return ExecutorResult(success=False, error=f"File not found: {path}")
        os.remove(full)
        return ExecutorResult(success=True, output=f"Deleted {path}")

    def _list_dir(self, path: str) -> ExecutorResult:
        full = self._resolve(path)
        if not os.path.isdir(full): return ExecutorResult(success=False, error=f"Not a directory: {path}")
        entries = []
        for entry in sorted(os.listdir(full)):
            full_entry = os.path.join(full, entry)
            entry_type = "dir" if os.path.isdir(full_entry) else "file"
            size = os.path.getsize(full_entry) if os.path.isfile(full_entry) else 0
            entries.append({"name": entry, "type": entry_type, "size": size})
        return ExecutorResult(success=True, output="\n".join(e["name"] for e in entries),
                              metadata={"path": path, "entries": entries})
