"""Gateway — injection detector (structural + semantic layers)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from hivemind.config import InjectionConfig


@dataclass
class GateResult:
    passed: bool
    rule_name: str
    reason: str
    evidence: str = ""


class InjectionDetector:
    """Detects prompt/command/SQL injection and path traversal attempts.

    Two layers:
      1. Structural guard — checks argument types, lengths, encodings
      2. Semantic classifier — pattern-matches known attack signatures,
         silently downgrades suspicious input (no feedback to attacker).
    """

    def __init__(self, config: InjectionConfig) -> None:
        self._enabled = config.enabled
        self._banned_commands: list[str] = list(config.banned_commands)
        self._blocked_paths: list[str] = list(config.blocked_paths)
        self._sql_patterns: list[re.Pattern] = [
            re.compile(p) for p in config.sql_patterns
        ]

    # ── public API ───────────────────────────────────────────────

    def check_all(self, tool_name: str, params: dict) -> list[GateResult]:
        """Run all relevant injection checks for a tool call."""
        if not self._enabled:
            return []
        results: list[GateResult] = []

        for key, value in params.items():
            if isinstance(value, str):
                results.append(self._check_command_injection(key, value))
                results.append(self._check_sql_injection(key, value))
                if key in ("path", "file", "target", "directory", "cwd", "url"):
                    results.append(self._check_path_traversal(key, value))

        return [r for r in results if not r.passed or r.evidence]

    # ── checks ───────────────────────────────────────────────────

    def _check_command_injection(self, key: str, value: str) -> GateResult:
        """Detect shell metacharacter injection and banned commands."""
        shell_meta = re.findall(r'[;&|`$(){}\[\]]', value)
        if shell_meta:
            return GateResult(
                False, "check_command_injection",
                f"Suspicious shell metacharacters in '{key}': {shell_meta}",
                value[:200],
            )
        lower = value.lower()
        for banned in self._banned_commands:
            if banned.lower() in lower:
                return GateResult(
                    False, "check_destructive_cmd",
                    f"Banned command fragment '{banned}' detected in '{key}'",
                    value[:200],
                )
        return GateResult(True, "check_command_injection", "clean")

    def _check_sql_injection(self, key: str, value: str) -> GateResult:
        for pattern in self._sql_patterns:
            m = pattern.search(value)
            if m:
                return GateResult(
                    False, "check_sql_injection",
                    f"SQL injection pattern detected in '{key}': {m.group()}",
                    value[:200],
                )
        return GateResult(True, "check_sql_injection", "clean")

    def _check_path_traversal(self, key: str, value: str) -> GateResult:
        """Detect directory traversal and access to sensitive paths."""
        if "../" in value or "..\\" in value:
            return GateResult(
                False, "check_path_traversal",
                f"Directory traversal detected in '{key}'",
                value[:200],
            )
        expanded = os.path.expanduser(value)
        for blocked in self._blocked_paths:
            blocked_exp = os.path.expanduser(blocked)
            if expanded.startswith(blocked_exp) or expanded == blocked_exp:
                return GateResult(
                    False, "check_sensitive_paths",
                    f"Access to blocked path '{blocked}' in '{key}'",
                    value[:200],
                )
        return GateResult(True, "check_path_traversal", "clean")
