"""Gateway — token-bucket rate limiter."""

from __future__ import annotations

import asyncio
import time

from hivemind.config import RateLimitConfig


class TokenBucketRateLimiter:
    """In-memory token-bucket algorithm, per-identity.

    Buckets refill at ``rate`` tokens/second, capped at ``burst``.
    """

    def __init__(self, config: RateLimitConfig) -> None:
        self._enabled = config.enabled
        self._rate = config.tokens_per_second
        self._burst = config.burst_size
        self._lock = asyncio.Lock()
        self._buckets: dict[str, tuple[float, float]] = {}  # identity -> (tokens, last_refill)

    async def consume(self, identity: str, tokens: float = 1.0) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        if not self._enabled:
            return True
        async with self._lock:
            now = time.monotonic()
            current, last = self._buckets.get(identity, (self._burst, now))
            elapsed = now - last
            current = min(self._burst, current + elapsed * self._rate)
            if current >= tokens:
                self._buckets[identity] = (current - tokens, now)
                return True
            self._buckets[identity] = (current, now)
            return False
