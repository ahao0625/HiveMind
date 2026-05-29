"""v2.0 Structural injection guard — first layer of injection detection.

Validates each parameter against per-tool slot definitions:
character allowlists, type constraints, and length limits.
This is fast, deterministic, and produces no false positives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from hivemind.config import InjectionStructuralConfig, ParameterSlotConfig, ToolSlotConfig


@dataclass(frozen=True)
class SlotResult:
    """Result of validating a single parameter slot."""
    param_name: str
    passed: bool
    reason: str = ""
    blocked: bool = False


@dataclass
class StructuralResult:
    """Aggregate result from the structural guard layer."""
    passed: bool = True
    slot_results: list[SlotResult] = field(default_factory=list)
    blocked_params: list[str] = field(default_factory=list)

    def add(self, result: SlotResult) -> None:
        self.slot_results.append(result)
        if not result.passed:
            self.passed = False
            if result.blocked:
                self.blocked_params.append(result.param_name)


class StructuralGuard:
    """Validates tool parameters against per-slot definitions.

    Each parameter is checked against its slot's character allowlist,
    type constraint, and max length. Unknown parameters use the default slot.
    """

    def __init__(self, config: InjectionStructuralConfig) -> None:
        self._enabled = config.enabled
        # build lookup: tool_name → {param_name → SlotDefinition}
        self._slots: dict[str, dict[str, ParameterSlotConfig]] = {}
        for tool_slot in config.per_tool_slots:
            self._slots[tool_slot.tool_name] = {
                s.param_name: s for s in tool_slot.slots
            }
        self._default_slot = config.default_slot

    def validate(self, tool_name: str, params: dict) -> StructuralResult:
        """Validate all parameters for a tool call."""
        result = StructuralResult()
        if not self._enabled:
            return result

        tool_slots = self._slots.get(tool_name, {})
        for key, value in params.items():
            slot = tool_slots.get(key, self._default_slot)
            result.add(self._validate_slot(key, str(value), slot))

        return result

    def _validate_slot(
        self, param_name: str, value: str, slot: ParameterSlotConfig,
    ) -> SlotResult:
        """Check a single parameter against its slot definition."""
        # Type check
        if slot.type_constraint == "int":
            try:
                int(value)
            except ValueError:
                return SlotResult(param_name, False, f"expected int, got: {value[:50]}", True)
        elif slot.type_constraint == "float":
            try:
                float(value)
            except ValueError:
                return SlotResult(param_name, False, f"expected float, got: {value[:50]}", True)

        # Length check
        if len(value) > slot.max_length:
            return SlotResult(
                param_name, False,
                f"length {len(value)} exceeds max {slot.max_length}",
                True,
            )

        # Character allowlist check (only for str type)
        if slot.type_constraint == "str" and slot.allowed_chars:
            pattern = re.compile(slot.allowed_chars)
            matches = pattern.findall(value)
            cleaned = "".join(matches)
            if cleaned != value:
                # find the first illegal character
                illegal_chars = set(value) - set(cleaned)
                return SlotResult(
                    param_name, False,
                    f"illegal chars in '{param_name}': {illegal_chars}",
                    True,
                )

        return SlotResult(param_name, True, "ok")
