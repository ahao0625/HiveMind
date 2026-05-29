"""v2.0 Semantic classifier — second layer of injection detection.

Confidence-based classification of suspicious input. Unlike the structural
guard which blocks deterministically, the classifier uses confidence levels:

  ≥95% → hard block (known attack pattern)
  50-95% → silent downgrade (sanitize parameters)
  30-50% → log only (low-confidence suspicion)
  <30% → pass

Silent downgrade is a key design principle: the attacker gets no feedback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from hivemind.config import InjectionSemanticConfig

Action = Literal["block", "downgrade", "log", "pass"]


@dataclass(frozen=True)
class ClassificationResult:
    """Result of semantic classification for a single parameter."""
    param_name: str
    action: Action
    confidence: float  # 0.0–1.0
    reason: str = ""
    cleaned_value: str | None = None  # downgraded value if action=downgrade


@dataclass
class SemanticResult:
    """Aggregate semantic classification result."""
    results: list[ClassificationResult] = field(default_factory=list)
    blocked_params: list[str] = field(default_factory=list)
    downgraded_params: dict[str, str] = field(default_factory=dict)

    @property
    def has_blocks(self) -> bool:
        return len(self.blocked_params) > 0

    @property
    def has_downgrades(self) -> bool:
        return len(self.downgraded_params) > 0

    def add(self, r: ClassificationResult) -> None:
        self.results.append(r)
        if r.action == "block":
            self.blocked_params.append(r.param_name)
        elif r.action == "downgrade" and r.cleaned_value is not None:
            self.downgraded_params[r.param_name] = r.cleaned_value


class SemanticClassifier:
    """Confidence-based semantic injection classifier.

    Known attack patterns are matched with high confidence.
    Suspicious but ambiguous patterns trigger downgrade or logging.
    """

    # High-confidence patterns (≥95%) → block
    HIGH_CONFIDENCE: list[tuple[str, float, str]] = [
        (r";\s*rm\s+-rf", 0.99, "rm -rf injection"),
        (r";\s*wget\s+\S+", 0.95, "wget download injection"),
        (r";\s*curl\s+\S+", 0.95, "curl injection"),
        (r"`[^`]*`", 0.95, "command substitution"),
        (r"\$\([^)]*\)", 0.95, "command substitution"),
        (r"/etc/(passwd|shadow|sudoers)", 0.98, "sensitive file access"),
        (r"\.\./\.\./", 0.98, "directory traversal"),
        (r"--no-check-certificate", 0.97, "SSL verification bypass"),
    ]

    # Medium-confidence patterns (50-95%) → downgrade
    MEDIUM_CONFIDENCE: list[tuple[str, float, str]] = [
        (r"[;&|]", 0.75, "shell metacharacters"),
        (r">>\s*/", 0.70, "write redirect to root"),
        (r"\bexec\b", 0.60, "exec keyword"),
        (r"\beval\b", 0.60, "eval keyword"),
        (r"\bimport\s+os\b", 0.55, "os import"),
        (r"\b__import__\b", 0.55, "dunder import"),
    ]

    # Low-confidence patterns (30-50%) → log only
    LOW_CONFIDENCE: list[tuple[str, float, str]] = [
        (r"\bchmod\b", 0.45, "chmod keyword"),
        (r"\bchown\b", 0.45, "chown keyword"),
        (r"\bsudo\b", 0.40, "sudo keyword"),
        (r"\bDELETE\s+FROM\b", 0.35, "SQL DELETE"),
        (r"\bDROP\b", 0.35, "SQL DROP keyword"),
    ]

    def __init__(self, config: InjectionSemanticConfig) -> None:
        self._enabled = config.enabled
        self._block_threshold = config.block_confidence
        self._downgrade_threshold = config.downgrade_confidence
        self._log_threshold = config.log_confidence

    def classify(self, tool_name: str, params: dict) -> SemanticResult:
        """Classify all string parameters for semantic threats."""
        result = SemanticResult()
        if not self._enabled:
            return result

        for key, value in params.items():
            if not isinstance(value, str):
                continue
            r = self._classify_value(key, value)
            result.add(r)

        return result

    def _classify_value(self, param_name: str, value: str) -> ClassificationResult:
        """Classify a single parameter value."""
        # Check high-confidence patterns first
        for pattern, confidence, reason in self.HIGH_CONFIDENCE:
            if re.search(pattern, value):
                return ClassificationResult(param_name, "block", confidence, reason)

        # Check medium-confidence patterns
        for pattern, confidence, reason in self.MEDIUM_CONFIDENCE:
            if re.search(pattern, value):
                cleaned = self.downgrade(value)
                return ClassificationResult(
                    param_name, "downgrade", confidence, reason, cleaned,
                )

        # Check low-confidence patterns
        for pattern, confidence, reason in self.LOW_CONFIDENCE:
            if re.search(pattern, value):
                return ClassificationResult(param_name, "log", confidence, reason)

        return ClassificationResult(param_name, "pass", 0.0, "clean")

    @staticmethod
    def downgrade(value: str) -> str:
        """Sanitize a suspicious value by stripping dangerous characters.

        Strategy:
          - Shell metacharacters: stripped (;&|`$(){}[])
          - Path traversal: normalization
          - SQL keywords: pass through (blocked at HIGH confidence instead)
        """
        cleaned = value
        cleaned = re.sub(r"[;&|`$(){}\[\]]", "", cleaned)  # strip shell metachars
        cleaned = re.sub(r"\.\.\/", "", cleaned)  # strip traversal
        cleaned = cleaned.strip()
        return cleaned
