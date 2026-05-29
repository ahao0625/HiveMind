"""Executor — HTTP request execution with domain allow-list."""

from __future__ import annotations

import time
from urllib.parse import urlparse

import httpx

from hivemind.config import HttpOpsConfig
from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.executors.base import Executor, ExecutorResult


class HttpOpsExecutor(Executor):
    """Makes HTTP requests through an allow-listed domain filter."""

    def __init__(self, config: HttpOpsConfig) -> None:
        self._allowed_domains = set(config.allowed_domains)
        self._allowed_methods = set(config.allowed_methods)
        self._timeout = config.timeout_seconds
        self._max_size = config.max_response_size_mb * 1024 * 1024

    def can_handle(self, tool_name: str) -> bool:
        return tool_name in ("http_get", "http_post", "http_put", "http_delete")

    async def execute(self, intent: RefinedIntent) -> ExecutorResult:
        t0 = time.monotonic()
        url = intent.parameters.get("url", "")
        if not url: return ExecutorResult(success=False, error="url is required")

        hostname = urlparse(url).hostname
        if not hostname or hostname not in self._allowed_domains:
            return ExecutorResult(success=False, error=f"Domain '{hostname}' not allowed: {sorted(self._allowed_domains)}")

        method_map = {"http_get": "GET", "http_post": "POST", "http_put": "PUT", "http_delete": "DELETE"}
        method = method_map.get(intent.tool_name, "GET")
        if method not in self._allowed_methods:
            return ExecutorResult(success=False, error=f"Method '{method}' not allowed")

        body = intent.parameters.get("body")
        content_type = intent.parameters.get("content_type", "application/json")

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                kwargs = {"url": url}
                if method in ("POST", "PUT") and body:
                    kwargs["content"] = body
                    kwargs["headers"] = {"Content-Type": content_type}
                response = await client.request(method, **kwargs)
                return ExecutorResult(
                    success=200 <= response.status_code < 300,
                    output=response.text[:int(self._max_size)],
                    duration_ms=(time.monotonic() - t0) * 1000,
                    metadata={"status_code": response.status_code, "url": url, "method": method},
                )
        except httpx.TimeoutException:
            return ExecutorResult(success=False, error=f"Request timed out after {self._timeout}s")
        except Exception as exc:
            return ExecutorResult(success=False, error=str(exc))
