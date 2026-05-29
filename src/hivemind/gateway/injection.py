"""Gateway — injection detector (structural + semantic layers).

v2.0: Two-layer architecture.
  Layer 1 — StructuralGuard: per-parameter slot validation (fast, deterministic).
  Layer 2 — SemanticClassifier: confidence-based attack detection.
  Legacy checks retained as HIGH confidence semantic rules.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from hivemind.config import InjectionConfig
from hivemind.gateway.semantic_classifier import (
    ClassificationResult,
    SemanticClassifier,
    SemanticResult,
)
from hivemind.gateway.structural_guard import (
    SlotResult,
    StructuralGuard,
    StructuralResult,
)


@dataclass
class GateResult:
    """Unified gate result — legacy compatible."""
    passed: bool
    rule_name: str
    reason: str
    evidence: str = ""


@dataclass
class InjectionResult:
    """v2.0 aggregate injection check result across both layers."""
    passed: bool = True
    blocked: bool = False
    structural: StructuralResult | None = None
    semantic: SemanticResult | None = None
    legacy_results: list[GateResult] = field(default_factory=list)
    # params after downgrade (cleaned by semantic classifier)
    downgraded_params: dict[str, str] | None = None

    def to_legacy(self) -> list[GateResult]:
        """Convert to legacy GateResult list for backward compatibility."""
        results: list[GateResult] = []
        if self.structural:
            for sr in self.structural.slot_results:
                if not sr.passed:
                    results.append(GateResult(
                        False, "structural_guard", sr.reason, sr.param_name,
                    ))
        if self.semantic:
            for cr in self.semantic.results:
                if cr.action == "block":
                    results.append(GateResult(
                        False, f"semantic_{cr.action}", cr.reason, cr.param_name,
                    ))
        results.extend(self.legacy_results)
        return results


class InjectionDetector:
    """Detects prompt/command/SQL injection and path traversal attempts.

    v2.0 Two-layer architecture:
      1. StructuralGuard — validates argument types, lengths, character sets
      2. SemanticClassifier — confidence-based attack pattern detection
         ≥95% → block, 50-95% → silent downgrade, 30-50% → log only
      3. Legacy checks — retained as deterministic high-confidence rules
    """

    def __init__(self, config: InjectionConfig) -> None:
        self._enabled = config.enabled
        self._banned_commands: list[str] = list(config.banned_commands)
        self._blocked_paths: list[str] = list(config.blocked_paths)
        self._sql_patterns: list[re.Pattern] = [
            re.compile(p) for p in config.sql_patterns
        ]
        # v2.0: two-layer architecture
        self._structural = StructuralGuard(config.structural)
        self._semantic = SemanticClassifier(config.semantic)

    # ── public API ───────────────────────────────────────────────

    def check_all(self, tool_name: str, params: dict) -> InjectionResult:
        """Run all injection checks: structural → semantic → legacy.

        Returns an InjectionResult with structural, semantic, and legacy
        results plus downgraded_params for use by the caller.
        """
        result = InjectionResult()
        if not self._enabled:
            return result

        # Layer 1: Structural guard (per-parameter slot validation)
        result.structural = self._structural.validate(tool_name, params)
        if result.structural.blocked_params:
            result.blocked = True

        # Layer 2: Semantic classifier (confidence-based)
        result.semantic = self._semantic.classify(tool_name, params)
        if result.semantic.has_blocks:
            result.blocked = True
        if result.semantic.has_downgrades:
            result.downgraded_params = dict(result.semantic.downgraded_params)

        # Layer 3: Legacy hard checks
        for key, value in params.items():
            if isinstance(value, str):
                r = self._check_command_injection(key, value)
                if not r.passed:
                    result.legacy_results.append(r)
                    result.blocked = True
                r = self._check_sql_injection(key, value)
                if not r.passed:
                    result.legacy_results.append(r)
                    result.blocked = True
                if key in ("path", "file", "target", "directory", "cwd", "url"):
                    r = self._check_path_traversal(key, value)
                    if not r.passed:
                        result.legacy_results.append(r)
                        result.blocked = True

        result.passed = not result.blocked
        return result

    def check_structural(self, tool_name: str, params: dict) -> StructuralResult:
        """Run only the structural guard layer."""
        return self._structural.validate(tool_name, params)

    def check_semantic(self, tool_name: str, params: dict) -> SemanticResult:
        """Run only the semantic classifier layer."""
        return self._semantic.classify(tool_name, params)

    # ── legacy checks ───────────────────────────────────────────

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
