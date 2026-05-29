"""HiveMind centralized configuration — Pydantic models for constitution-as-code."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


# ── Gateway ──────────────────────────────────────────────────────

class AuthConfig(BaseModel):
    enabled: bool = True
    api_keys: list[str] = Field(default_factory=lambda: ["hivemind-dev-key"])


class RateLimitConfig(BaseModel):
    enabled: bool = True
    tokens_per_second: float = 10.0
    burst_size: int = 20


class InjectionConfig(BaseModel):
    enabled: bool = True
    banned_commands: list[str] = Field(default_factory=lambda: [
        "rm -rf /", "dd if=", "mkfs", ":(){ :|:& };:", "chmod 777",
    ])
    blocked_paths: list[str] = Field(default_factory=lambda: [
        "/etc/passwd", "/etc/shadow", "/etc/hosts", "/etc/sudoers",
        "~/.ssh", "~/.aws", "~/.gnupg", "/proc", "/sys",
    ])
    sql_patterns: list[str] = Field(default_factory=lambda: [
        r"(?i)\bDROP\s+TABLE\b", r"(?i)\bDROP\s+DATABASE\b",
        r"(?i)\bALTER\s+TABLE\b.*\bDROP\b", r"(?i)\bTRUNCATE\b",
    ])


class GatewayConfig(BaseModel):
    auth: AuthConfig = Field(default_factory=AuthConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    injection: InjectionConfig = Field(default_factory=InjectionConfig)


# ── Commander ────────────────────────────────────────────────────

class HardGateRule(BaseModel):
    id: str
    name: str
    description: str
    check_function: str  # e.g. "rule_engine:check_destructive_rm"
    priority: int = 100
    parameters: dict = Field(default_factory=dict)


class ScoringDimension(BaseModel):
    id: str
    name: str
    weight: float  # 0.0–1.0
    score_function: str  # e.g. "rule_engine:score_read_only"
    description: str = ""


class Constitution(BaseModel):
    """The rule constitution — persisted to JSON, version-controlled."""
    hard_gates: list[HardGateRule] = Field(default_factory=list)
    scoring_dimensions: list[ScoringDimension] = Field(default_factory=list)
    approval_threshold: float = 0.40
    human_approval_threshold: float = 0.60


class CommanderConfig(BaseModel):
    constitution: Constitution = Field(default_factory=Constitution)
    default_routing: Literal["system1", "system2"] = "system2"
    max_retries: int = 3


# ── Executors ────────────────────────────────────────────────────

class FileOpsConfig(BaseModel):
    root_dir: str = Field(default_factory=lambda: os.path.join(os.environ.get("TMPDIR", "/tmp"), "hivemind-sandbox"))
    max_file_size_mb: float = 10.0
    allowed_extensions: list[str] = Field(default_factory=lambda: [
        ".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
        ".toml", ".csv", ".html", ".css", ".xml", ".sh", ".env",
    ])


class ShellOpsConfig(BaseModel):
    allowed_binaries: list[str] = Field(default_factory=lambda: [
        "ls", "cat", "grep", "find", "wc", "head", "tail", "sort",
        "uniq", "echo", "date", "which", "python", "python3", "node",
        "git", "curl", "wget", "mkdir", "cp", "mv", "touch", "df", "du",
    ])
    timeout_seconds: float = 30.0
    deny_network: bool = False


class HttpOpsConfig(BaseModel):
    allowed_domains: list[str] = Field(default_factory=lambda: [
        "api.github.com", "httpbin.org", "jsonplaceholder.typicode.com",
        "pokeapi.co",
    ])
    allowed_methods: list[str] = Field(default_factory=lambda: [
        "GET", "POST", "PUT", "DELETE",
    ])
    timeout_seconds: float = 15.0
    max_response_size_mb: float = 5.0


class ExecutorConfig(BaseModel):
    file_ops: FileOpsConfig = Field(default_factory=FileOpsConfig)
    shell_ops: ShellOpsConfig = Field(default_factory=ShellOpsConfig)
    http_ops: HttpOpsConfig = Field(default_factory=HttpOpsConfig)


# ── Verification ─────────────────────────────────────────────────

class VerificationConfig(BaseModel):
    enabled_checks: list[str] = Field(default_factory=lambda: [
        "syntax", "security", "result",
    ])
    fail_fast: bool = True


# ── Memory ───────────────────────────────────────────────────────

class ShortTermMemoryConfig(BaseModel):
    max_items: int = 1000
    default_ttl_seconds: int = 300


class LongTermMemoryConfig(BaseModel):
    persistence_path: str = "~/.hivemind/long_term_memory.json"
    auto_save_seconds: int = 10


class WorkingMemoryConfig(BaseModel):
    max_bytes: int = 10 * 1024 * 1024  # 10 MB


class MemoryConfig(BaseModel):
    short_term: ShortTermMemoryConfig = Field(default_factory=ShortTermMemoryConfig)
    long_term: LongTermMemoryConfig = Field(default_factory=LongTermMemoryConfig)
    working: WorkingMemoryConfig = Field(default_factory=WorkingMemoryConfig)


# ── Server ───────────────────────────────────────────────────────

class ServerConfig(BaseModel):
    name: str = "HiveMind"
    version: str = "0.1.0"


# ── Root Config ──────────────────────────────────────────────────

class HiveMindConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    commander: CommanderConfig = Field(default_factory=CommanderConfig)
    executors: ExecutorConfig = Field(default_factory=ExecutorConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)

    @classmethod
    def load(cls, path: str | None = None) -> HiveMindConfig:
        """Load config from JSON file, falling back to sensible defaults."""
        if path and os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            return cls(**data)
        for candidate in [
            os.path.expanduser("~/.hivemind/config.json"),
            "config.json",
        ]:
            if os.path.exists(candidate):
                with open(candidate) as f:
                    data = json.load(f)
                return cls(**data)
        return cls()

    @classmethod
    def default_constitution(cls) -> Constitution:
        """Return the built-in constitution rules (hard gates + scoring)."""
        return Constitution(
            hard_gates=[
                HardGateRule(
                    id="no-destructive-commands",
                    name="Block Destructive Commands",
                    description="Vetoes rm -rf, dd, mkfs, fork bombs, etc.",
                    check_function="commander.rule_engine:check_destructive_cmd",
                    priority=1,
                    parameters={
                        "banned": [
                            "rm -rf /", "rm -rf /*", "rm -rf ~",
                            "dd if=", "mkfs", ":(){ :|:& };:",
                            "chmod 777 /", "chmod -R 777 /",
                        ],
                    },
                ),
                HardGateRule(
                    id="no-sensitive-paths",
                    name="Block Sensitive File Access",
                    description="Vetoes reads/writes to system-sensitive paths.",
                    check_function="commander.rule_engine:check_sensitive_paths",
                    priority=2,
                    parameters={
                        "blocked": [
                            "/etc/passwd", "/etc/shadow", "/etc/hosts",
                            "/etc/sudoers", "~/.ssh", "~/.aws", "~/.gnupg",
                            "/proc", "/sys", "/dev",
                        ],
                    },
                ),
                HardGateRule(
                    id="no-outside-sandbox",
                    name="Block Outside Sandbox Writes",
                    description="Prevents file writes outside the configured sandbox root.",
                    check_function="commander.rule_engine:check_outside_sandbox",
                    priority=3,
                ),
                HardGateRule(
                    id="no-excessive-size",
                    name="Block Excessive File Size",
                    description="Vetoes file writes exceeding max_file_size_mb.",
                    check_function="commander.rule_engine:check_file_size",
                    priority=10,
                ),
            ],
            scoring_dimensions=[
                ScoringDimension(
                    id="read-only-preference",
                    name="Read-Only Preference",
                    weight=0.30,
                    score_function="commander.rule_engine:score_read_only",
                    description="Read operations score higher than writes/deletes.",
                ),
                ScoringDimension(
                    id="path-safety",
                    name="Path Safety",
                    weight=0.25,
                    score_function="commander.rule_engine:score_path_safety",
                    description="Paths within project/sandbox directories score higher.",
                ),
                ScoringDimension(
                    id="command-simplicity",
                    name="Command Simplicity",
                    weight=0.20,
                    score_function="commander.rule_engine:score_command_simplicity",
                    description="Simple, common commands score higher.",
                ),
                ScoringDimension(
                    id="scope-locality",
                    name="Scope Locality",
                    weight=0.15,
                    score_function="commander.rule_engine:score_scope_locality",
                    description="Local file/process scope scores higher than network.",
                ),
                ScoringDimension(
                    id="precedent-match",
                    name="Precedent Match",
                    weight=0.10,
                    score_function="commander.rule_engine:score_precedent",
                    description="Previously approved operations score higher.",
                ),
            ],
            approval_threshold=0.40,
            human_approval_threshold=0.60,
        )
