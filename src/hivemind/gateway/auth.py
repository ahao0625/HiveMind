"""Gateway — authentication guard for HiveMind MCP tools."""

from __future__ import annotations

from dataclasses import dataclass

from hivemind.config import AuthConfig


@dataclass
class AuthResult:
    authenticated: bool
    identity: str
    reason: str


class AuthGuard:
    """Validates API keys / tokens against configured allow-list."""

    def __init__(self, config: AuthConfig) -> None:
        self._enabled = config.enabled
        self._valid_keys: set[str] = set(config.api_keys)

    def authenticate(self, api_key: str | None) -> AuthResult:
        if not self._enabled:
            return AuthResult(True, "anonymous", "auth disabled")
        if not api_key:
            return AuthResult(False, "unknown", "missing api_key")
        if api_key in self._valid_keys:
            return AuthResult(True, f"key:{api_key[:8]}...", "valid key")
        return AuthResult(False, "unknown", "invalid api_key")
