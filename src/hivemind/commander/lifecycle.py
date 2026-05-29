"""Commander — task lifecycle orchestrator.

Central coordinator: Gateway → Intent → Rule Engine → Arbiter → Executor → Verification → Memory → Audit
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from hivemind.config import HiveMindConfig
from hivemind.commander.intent_refiner import IntentRefiner
from hivemind.commander.rule_engine import RuleEngine
from hivemind.commander.arbiter import Arbiter, Decision
from hivemind.commander.task_router import TaskRouter
from hivemind.commander.state_manager import StateManager, TaskState
from hivemind.gateway.auth import AuthGuard
from hivemind.gateway.injection import InjectionDetector
from hivemind.gateway.rate_limiter import TokenBucketRateLimiter
from hivemind.gateway.audit import AuditLogger, AuditEvent
from hivemind.observability.metrics import MetricsCollector


class ToolResult:
    """Result returned to the AI after lifecycle completes."""
    def __init__(self, success: bool, data: Any = None, blocked: bool = False,
                 reason: str = "", decision: Decision | None = None) -> None:
        self.success = success
        self.data = data
        self.blocked = blocked
        self.reason = reason
        self.decision = decision


class TaskLifecycle:
    """Orchestrates the full tool-call lifecycle."""

    def __init__(self, config: HiveMindConfig, auth: AuthGuard, injection: InjectionDetector,
                 rate_limiter: TokenBucketRateLimiter, audit: AuditLogger, metrics: MetricsCollector,
                 rule_engine: RuleEngine, arbiter: Arbiter, router: TaskRouter,
                 state_manager: StateManager, memory_system: Any) -> None:
        self._config = config
        self._auth = auth
        self._injection = injection
        self._rate_limiter = rate_limiter
        self._audit = audit
        self._metrics = metrics
        self._intent_refiner = IntentRefiner()
        self._rule_engine = rule_engine
        self._arbiter = arbiter
        self._router = router
        self._state_manager = state_manager
        self._memory = memory_system
        self._executors: dict[str, Any] = {}

    def register_executor(self, tool_name: str, executor: Any) -> None:
        self._executors[tool_name] = executor

    async def execute(self, tool_name: str, params: dict, identity: str = "anonymous",
                      api_key: str | None = None) -> ToolResult:
        t_start = time.monotonic()
        task = await self._state_manager.create_task(tool_name, params)
        await self._metrics.increment("hivemind_requests_total")
        await self._metrics.gauge("hivemind_active_tasks", await self._state_manager.active_count())

        # ── 1. GATEWAY ──
        auth_result = self._auth.authenticate(api_key)
        if not auth_result.authenticated:
            await self._record_audit(identity, tool_name, params, "blocked", "blocked", "skipped", "skipped",
                                     f"Auth: {auth_result.reason}")
            return ToolResult(False, blocked=True, reason=f"Auth: {auth_result.reason}")

        if not await self._rate_limiter.consume(identity):
            await self._record_audit(identity, tool_name, params, "blocked", "blocked", "skipped", "skipped",
                                     "Rate limit exceeded")
            return ToolResult(False, blocked=True, reason="Rate limit exceeded")

        injection_results = self._injection.check_all(tool_name, params)
        blocked_inj = [r for r in injection_results if not r.passed]
        if blocked_inj:
            await self._metrics.increment("hivemind_gate_blocks_total")
            await self._record_audit(identity, tool_name, params, "blocked", "blocked", "skipped", "skipped",
                                     f"Injection: {blocked_inj[0].reason}")
            return ToolResult(False, blocked=True, reason=f"Injection detected: {blocked_inj[0].reason}")

        await self._state_manager.transition(task.task_id, TaskState.PLANNING)

        # ── 2. INTENT ──
        intent = self._intent_refiner.refine(tool_name, params)

        # ── 3. RULE ENGINE ──
        sandbox = self._config.executors.file_ops.root_dir
        rule_result = self._rule_engine.evaluate(intent, sandbox)

        # ── 4. ARBITER ──
        decision = self._arbiter.decide(rule_result, intent)
        if not decision.approved:
            if decision.requires_human_approval:
                await self._state_manager.transition(task.task_id, TaskState.AWAITING_APPROVAL)
                return ToolResult(False, blocked=True, reason=f"Human approval required: {decision.reasoning}", decision=decision)
            await self._state_manager.transition(task.task_id, TaskState.BLOCKED)
            await self._metrics.increment("hivemind_gate_blocks_total")
            await self._record_audit(identity, tool_name, params, "passed", "blocked", "skipped", "skipped",
                                     f"Arbiter: {decision.reasoning}")
            return ToolResult(False, blocked=True, reason=decision.reasoning)

        # ── 5. SYSTEM 1 FAST PATH ──
        if decision.execution_mode == "system1":
            cached = await self._router.try_system1(intent, decision)
            if cached is not None:
                await self._metrics.increment("hivemind_system1_hits_total")
                await self._state_manager.transition(task.task_id, TaskState.COMPLETED)
                return ToolResult(True, data=cached)

        await self._state_manager.transition(task.task_id, TaskState.EXECUTING)
        await self._metrics.increment("hivemind_system2_hits_total")

        # ── 6. EXECUTE ──
        executor = self._executors.get(tool_name)
        if executor is None:
            await self._state_manager.transition(task.task_id, TaskState.FAILED, error=f"No executor for '{tool_name}'")
            return ToolResult(False, blocked=True, reason=f"No executor: {tool_name}")

        try:
            exec_result = await executor.execute(intent)
        except Exception as exc:
            await self._state_manager.transition(task.task_id, TaskState.FAILED, error=str(exc))
            await self._record_audit(identity, tool_name, params, "passed", "approved", "failure", "skipped", str(exc))
            return ToolResult(False, blocked=True, reason=f"Execution error: {exc}")

        if not exec_result.success:
            err = getattr(exec_result, 'error', 'unknown')
            await self._state_manager.transition(task.task_id, TaskState.FAILED, error=err)
            await self._record_audit(identity, tool_name, params, "passed", "approved", "failure", "skipped", err)
            return ToolResult(False, blocked=True, reason=f"Execution failed: {err}")

        await self._metrics.increment("hivemind_executions_total")

        # ── 7. VERIFICATION (System 2) ──
        await self._state_manager.transition(task.task_id, TaskState.VERIFYING)

        # ── 8. CACHE ──
        await self._router.cache_result(intent, exec_result)

        # ── 9. AUDIT ──
        duration_ms = (time.monotonic() - t_start) * 1000
        await self._record_audit(identity, tool_name, params, "passed", "approved", "success", "passed",
                                 f"OK {duration_ms:.0f}ms score={rule_result.overall_score:.2f}",
                                 duration_ms=duration_ms)
        await self._state_manager.transition(task.task_id, TaskState.COMPLETED)
        await self._metrics.histogram("hivemind_execution_duration_seconds", duration_ms / 1000)
        return ToolResult(True, data=exec_result)

    async def _record_audit(self, identity: str, tool_name: str, params: dict,
                            gateway: str, arbiter: str, executor: str, verification: str,
                            summary: str, duration_ms: float = 0.0) -> None:
        await self._audit.record(AuditEvent(
            identity=identity, tool_name=tool_name, params_hash=self._hash_params(params),
            gateway_result=gateway, arbiter_decision=arbiter, executor_result=executor,
            verification_result=verification, duration_ms=duration_ms, summary=summary))

    @staticmethod
    def _hash_params(params: dict) -> str:
        return hashlib.sha256(str(sorted(params.items())).encode()).hexdigest()[:16]
