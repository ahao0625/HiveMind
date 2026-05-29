"""Commander — rule engine: hard gates (one-vote veto) + soft scoring (auxiliary)."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from typing import Callable

from hivemind.config import Constitution, HardGateRule, ScoringDimension
from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.gateway.injection import GateResult


@dataclass
class RuleEngineResult:
    hard_gates: list[GateResult] = field(default_factory=list)
    soft_scores: dict[str, float] = field(default_factory=dict)
    overall_score: float = 0.0
    blocked: bool = False
    block_reason: str = ""


class RuleEngine:
    """Orchestrates hard-gate execution then soft scoring.

    Hard gates have one-vote veto power. Soft scores are only computed
    when all hard gates pass.
    """

    def __init__(self, constitution: Constitution) -> None:
        self._hard_gate_rules = sorted(constitution.hard_gates, key=lambda r: r.priority)
        self._scoring_dims = list(constitution.scoring_dimensions)
        self._approval_threshold = constitution.approval_threshold
        self._human_threshold = constitution.human_approval_threshold
        self._gate_funcs: dict[str, Callable] = {}
        self._score_funcs: dict[str, Callable] = {}

    @property
    def approval_threshold(self) -> float: return self._approval_threshold
    @property
    def human_threshold(self) -> float: return self._human_threshold

    def evaluate(self, intent: RefinedIntent, sandbox_root: str = "/tmp/hivemind-sandbox") -> RuleEngineResult:
        # Phase 1: Hard gates
        gate_results: list[GateResult] = []
        for rule in self._hard_gate_rules:
            result = self._run_gate(rule, intent, sandbox_root)
            gate_results.append(result)
            if not result.passed:
                return RuleEngineResult(hard_gates=gate_results, blocked=True,
                                        block_reason=f"[{rule.name}] {result.reason}")

        # Phase 2: Soft scoring
        scores: dict[str, float] = {}
        weighted_sum = 0.0
        total_weight = 0.0
        for dim in self._scoring_dims:
            raw = self._run_score(dim, intent)
            scores[dim.id] = raw
            weighted_sum += raw * dim.weight
            total_weight += dim.weight
        overall = weighted_sum / total_weight if total_weight > 0 else 0.5
        return RuleEngineResult(hard_gates=gate_results, soft_scores=scores, overall_score=round(overall, 4))

    def _run_gate(self, rule: HardGateRule, intent: RefinedIntent, sandbox_root: str) -> GateResult:
        func = self._resolve(rule.check_function, self._gate_funcs)
        try:
            return func(intent, rule.parameters, sandbox_root)
        except Exception as exc:
            return GateResult(False, rule.id, f"Gate error: {exc}")

    def _run_score(self, dim: ScoringDimension, intent: RefinedIntent) -> float:
        func = self._resolve(dim.score_function, self._score_funcs)
        try:
            return func(intent)
        except Exception:
            return 0.5

    @staticmethod
    def _resolve(ref: str, cache: dict[str, Callable]) -> Callable:
        if ref in cache:
            return cache[ref]
        module_path, func_name = ref.split(":")
        full_module = f"hivemind.{module_path}"
        module = importlib.import_module(full_module)
        func = getattr(module, func_name)
        cache[ref] = func
        return func


# ── Built-in Hard Gate Functions ─────────────────────────────────

def check_destructive_cmd(intent: RefinedIntent, params: dict, sandbox_root: str) -> GateResult:
    cmd = intent.parameters.get("command", "")
    if not isinstance(cmd, str): return GateResult(True, "check_destructive_cmd", "no command")
    lower = cmd.lower()
    for banned in params.get("banned", []):
        if banned.lower() in lower:
            return GateResult(False, "check_destructive_cmd", f"Destructive command blocked: '{banned}'", cmd[:200])
    return GateResult(True, "check_destructive_cmd", "clean")


def check_sensitive_paths(intent: RefinedIntent, params: dict, sandbox_root: str) -> GateResult:
    path = intent.parameters.get("path", "")
    if not isinstance(path, str) or not path: return GateResult(True, "check_sensitive_paths", "no path")
    expanded = os.path.expanduser(path)
    for blocked in params.get("blocked", []):
        blocked_exp = os.path.expanduser(blocked)
        if expanded.startswith(blocked_exp) or expanded == blocked_exp:
            return GateResult(False, "check_sensitive_paths", f"Blocked path '{blocked}'", path[:200])
    return GateResult(True, "check_sensitive_paths", "clean")


def check_outside_sandbox(intent: RefinedIntent, params: dict, sandbox_root: str) -> GateResult:
    if intent.tool_name not in ("write_file", "delete_file"):
        return GateResult(True, "check_outside_sandbox", "not a file write/delete")
    path = intent.parameters.get("path", "")
    if not isinstance(path, str) or not path: return GateResult(True, "check_outside_sandbox", "no path")
    sandbox = os.path.realpath(os.path.expanduser(sandbox_root))
    full = os.path.realpath(os.path.join(sandbox, path))
    if not full.startswith(sandbox + os.sep) and full != sandbox:
        return GateResult(False, "check_outside_sandbox",
                          f"Path '{path}' resolves outside sandbox '{sandbox}'", path[:200])
    return GateResult(True, "check_outside_sandbox", "within sandbox")


def check_file_size(intent: RefinedIntent, params: dict, sandbox_root: str) -> GateResult:
    if intent.tool_name != "write_file": return GateResult(True, "check_file_size", "not a file write")
    content = intent.parameters.get("content", "")
    if isinstance(content, str):
        size_mb = len(content.encode("utf-8")) / (1024 * 1024)
        max_mb = params.get("max_file_size_mb", 10)
        if size_mb > max_mb:
            return GateResult(False, "check_file_size", f"File size {size_mb:.1f}MB exceeds max {max_mb}MB")
    return GateResult(True, "check_file_size", "size ok")


# ── Built-in Soft Scoring Functions ──────────────────────────────

def score_read_only(intent: RefinedIntent) -> float:
    scores = {"read": 1.0, "query": 0.8, "write": 0.5, "execute": 0.3, "delete": 0.1}
    return scores.get(intent.action_type, 0.5)


def score_path_safety(intent: RefinedIntent) -> float:
    path = intent.parameters.get("path", "")
    if not isinstance(path, str) or not path: return 0.7
    safe = ("/tmp", "/home", "/Users", "./", "~/", "sandbox")
    if any(path.startswith(s) for s in safe): return 0.9
    risky = ("/etc", "/usr", "/bin", "/boot", "/root", "/proc", "/sys")
    if any(path.startswith(r) for r in risky): return 0.1
    return 0.5


def score_command_simplicity(intent: RefinedIntent) -> float:
    if intent.tool_name != "run_command": return 0.8
    cmd = intent.parameters.get("command", "")
    if not isinstance(cmd, str): return 0.5
    first = cmd.strip().split()[0] if cmd.strip() else ""
    if first in {"ls", "cat", "echo", "pwd", "date", "which", "whoami"}: return 1.0
    if first in {"python", "python3", "node", "npm", "git", "grep", "find", "wc", "head", "tail", "sort", "uniq"}: return 0.7
    if first in {"curl", "wget", "ping"}: return 0.4
    return 0.3


def score_scope_locality(intent: RefinedIntent) -> float:
    if intent.tool_name.startswith("http_"): return 0.3
    if intent.tool_name == "run_command": return 0.5
    return 0.9


def score_precedent(intent: RefinedIntent) -> float:
    return 0.6  # neutral — no precedent data in Phase 0
