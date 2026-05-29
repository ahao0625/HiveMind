"""In-memory metrics collector for HiveMind observability."""

from __future__ import annotations

import asyncio
from collections import defaultdict


class MetricsCollector:
    """Thread-safe in-memory metrics store (Phase 0 fallback for Prometheus)."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)

        # Pre-register standard metrics
        self._counters["hivemind_requests_total"] = 0.0
        self._counters["hivemind_gate_blocks_total"] = 0.0
        self._counters["hivemind_verification_failures_total"] = 0.0
        self._counters["hivemind_executions_total"] = 0.0
        self._counters["hivemind_system1_hits_total"] = 0.0
        self._counters["hivemind_system2_hits_total"] = 0.0
        self._gauges["hivemind_active_tasks"] = 0.0

    async def increment(self, name: str, value: float = 1.0) -> None:
        async with self._lock:
            self._counters[name] += value

    async def gauge(self, name: str, value: float) -> None:
        async with self._lock:
            self._gauges[name] = value

    async def histogram(self, name: str, value: float) -> None:
        async with self._lock:
            self._histograms[name].append(value)
            if len(self._histograms[name]) > 1000:
                self._histograms[name] = self._histograms[name][-1000:]

    async def snapshot(self) -> dict:
        """Return a snapshot of all current metric values."""
        async with self._lock:
            hist_snap = {}
            for k, v in self._histograms.items():
                if v:
                    sv = sorted(v)
                    hist_snap[k] = {
                        "count": len(v),
                        "min": min(v),
                        "max": max(v),
                        "avg": sum(v) / len(v),
                        "p50": sv[len(v) // 2],
                        "p95": sv[int(len(v) * 0.95)],
                        "p99": sv[int(len(v) * 0.99)],
                    }
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": hist_snap,
            }
