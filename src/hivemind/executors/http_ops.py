"""Executor — HTTP request execution with domain allow-list.

v2.0: Added SSRF protection (internal IP blocking) and redirect guard.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from urllib.parse import urlparse

import httpx

from hivemind.config import HttpOpsConfig
from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.executors.base import Executor, ExecutorResult

# v2.0: internal/private IP ranges blocked for SSRF prevention
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_internal_ip(hostname: str) -> bool:
    """Check if a hostname resolves to an internal/private IP address."""
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # Not an IP literal, try DNS resolution
        try:
            addr = ipaddress.ip_address(socket.gethostbyname(hostname))
        except (socket.gaierror, ValueError):
            return False
    return any(addr in net for net in BLOCKED_IP_RANGES)


class HttpOpsExecutor(Executor):
    """Makes HTTP requests through an allow-listed domain filter.

    v2.0: SSRF protection blocks internal IPs, redirects are manually followed
    and each target is validated.
    """

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
        if not url:
            return ExecutorResult(success=False, error="url is required")

        hostname = urlparse(url).hostname
        if not hostname or hostname not in self._allowed_domains:
            return ExecutorResult(success=False, error=f"Domain '{hostname}' not allowed: {sorted(self._allowed_domains)}")

        # v2.0: SSRF check
        if _is_internal_ip(hostname):
            return ExecutorResult(success=False, error=f"Internal IP blocked (SSRF): {hostname}")

        method_map = {"http_get": "GET", "http_post": "POST", "http_put": "PUT", "http_delete": "DELETE"}
        method = method_map.get(intent.tool_name, "GET")
        if method not in self._allowed_methods:
            return ExecutorResult(success=False, error=f"Method '{method}' not allowed")

        body = intent.parameters.get("body")
        content_type = intent.parameters.get("content_type", "application/json")

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as client:
                kwargs = {"url": url}
                if method in ("POST", "PUT") and body:
                    kwargs["content"] = body
                    kwargs["headers"] = {"Content-Type": content_type}
                response = await client.request(method, **kwargs)

                # v2.0: manual redirect guard — validate each hop
                if response.status_code in (301, 302, 303, 307, 308):
                    redirect_url = response.headers.get("Location", "")
                    if not redirect_url:
                        return ExecutorResult(success=False, error="Redirect without Location header")
                    redirect_host = urlparse(redirect_url).hostname
                    if not redirect_host or redirect_host not in self._allowed_domains:
                        return ExecutorResult(
                            success=False,
                            error=f"Redirect to disallowed domain: {redirect_host}",
                        )
                    if _is_internal_ip(redirect_host):
                        return ExecutorResult(
                            success=False,
                            error=f"Redirect to internal IP blocked (SSRF): {redirect_host}",
                        )

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
