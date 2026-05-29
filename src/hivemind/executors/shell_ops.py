"""Executor — shell command execution with binary allow-list."""

from __future__ import annotations

import asyncio
import os
import shlex
import time

from hivemind.config import ShellOpsConfig
from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.executors.base import Executor, ExecutorResult


class ShellOpsExecutor(Executor):
    """Runs shell commands with strict binary allow-listing."""

    def __init__(self, config: ShellOpsConfig) -> None:
        self._allowed: set[str] = set(config.allowed_binaries)
        self._timeout = config.timeout_seconds

    def can_handle(self, tool_name: str) -> bool:
        return tool_name == "run_command"

    async def execute(self, intent: RefinedIntent) -> ExecutorResult:
        t0 = time.monotonic()
        cmd = intent.parameters.get("command", "")
        if not cmd: return ExecutorResult(success=False, error="command is required")

        try:
            parts = shlex.split(cmd)
        except ValueError as e:
            return ExecutorResult(success=False, error=f"Invalid command syntax: {e}")
        if not parts: return ExecutorResult(success=False, error="Empty command")

        binary = os.path.basename(parts[0])
        if binary not in self._allowed:
            return ExecutorResult(success=False, error=f"Binary '{binary}' not allowed. Allowed: {sorted(self._allowed)}")

        cwd = intent.parameters.get("cwd")
        try:
            proc = await asyncio.create_subprocess_exec(
                *parts, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=cwd, env=os.environ.copy(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
            return ExecutorResult(
                success=proc.returncode == 0,
                output=(stdout.decode("utf-8", errors="replace") if proc.returncode == 0
                        else stderr.decode("utf-8", errors="replace"))[:100_000],
                stdout=stdout.decode("utf-8", errors="replace")[:100_000],
                stderr=stderr.decode("utf-8", errors="replace")[:100_000],
                duration_ms=(time.monotonic() - t0) * 1000,
                metadata={"exit_code": proc.returncode, "binary": binary},
            )
        except asyncio.TimeoutError:
            return ExecutorResult(success=False, error=f"Command timed out after {self._timeout}s")
        except FileNotFoundError:
            return ExecutorResult(success=False, error=f"Binary not found: {binary}")
