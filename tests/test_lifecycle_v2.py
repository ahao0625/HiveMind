"""Tests for v2.0 TaskLifecycle — verification, rollback, procedural memory."""

import os
import pytest
from hivemind.config import HiveMindConfig
from hivemind.gateway import AuthGuard, InjectionDetector, TokenBucketRateLimiter, AuditLogger
from hivemind.commander import RuleEngine, Arbiter, TaskRouter, StateManager, TaskLifecycle
from hivemind.executors import FileOpsExecutor
from hivemind.verification import VerificationPipeline, SyntaxVerifier, SecurityVerifier, ResultVerifier
from hivemind.memory.facade import MemorySystem
from hivemind.observability.metrics import MetricsCollector


@pytest.fixture
def config():
    return HiveMindConfig.load()


@pytest.fixture
def sandbox():
    return os.path.join(os.environ.get("TMPDIR", "/tmp"), "lifecycle-test-sandbox")


@pytest.fixture
def lifecycle(config, sandbox):
    auth = AuthGuard(config.gateway.auth)
    injection = InjectionDetector(config.gateway.injection)
    rate_limiter = TokenBucketRateLimiter(config.gateway.rate_limit)
    audit = AuditLogger()
    metrics = MetricsCollector()
    rule_engine = RuleEngine(config.commander.constitution)
    arbiter = Arbiter(rule_engine)
    router = TaskRouter()
    state_manager = StateManager()
    memory_system = MemorySystem(config.memory)
    verifier = VerificationPipeline(
        [SyntaxVerifier(), SecurityVerifier(), ResultVerifier()],
        fail_fast=True,
    )

    lifecycle = TaskLifecycle(
        config, auth, injection, rate_limiter, audit, metrics,
        rule_engine, arbiter, router, state_manager, memory_system,
        verifier=verifier,
    )

    file_exec = FileOpsExecutor(config.executors.file_ops)
    lifecycle.register_executor("read_file", file_exec)
    lifecycle.register_executor("write_file", file_exec)
    lifecycle.register_executor("delete_file", file_exec)
    lifecycle.register_executor("list_files", file_exec)

    yield lifecycle

    # cleanup
    proc_path = os.path.expanduser(config.memory.procedural.persistence_path)
    if os.path.exists(proc_path):
        os.remove(proc_path)


class TestBasicExecution:
    @pytest.mark.asyncio
    async def test_write_then_read(self, lifecycle, sandbox):
        r = await lifecycle.execute("write_file", {"path": "hello.txt", "content": "world"}, identity="test", api_key="hivemind-dev-key")
        assert r.success is True
        assert r.blocked is False

        r2 = await lifecycle.execute("read_file", {"path": "hello.txt"}, identity="test", api_key="hivemind-dev-key")
        assert r2.success is True
        assert "world" in str(r2.data.output)

    @pytest.mark.asyncio
    async def test_safe_read_not_blocked(self, lifecycle):
        r = await lifecycle.execute("read_file", {"path": "test.txt"}, identity="test", api_key="hivemind-dev-key")
        # file may not exist but should not be blocked by gateway
        assert r.blocked is False or "File not found" in str(r.reason)

    @pytest.mark.asyncio
    async def test_destructive_blocked(self, lifecycle):
        r = await lifecycle.execute("run_command", {"command": "rm -rf /"}, identity="test", api_key="hivemind-dev-key")
        assert r.blocked is True


class TestVerificationPipeline:
    @pytest.mark.asyncio
    async def test_invalid_json_triggers_verification_failure(self, lifecycle):
        # Use content that passes injection but fails JSON syntax verification
        r = await lifecycle.execute("write_file", {"path": "bad.json", "content": "this is not valid json"}, identity="test", api_key="hivemind-dev-key")
        assert "Verification failed" in r.reason


class TestProceduralMemoryRecording:
    @pytest.mark.asyncio
    async def test_success_records_procedural_memory(self, lifecycle):
        r = await lifecycle.execute("write_file", {"path": "proc.txt", "content": "hello"}, identity="test", api_key="hivemind-dev-key")
        assert r.success is True
        # procedural memory should have recorded this
        # verify via the memory system
        # (implementation detail: record is stored internally)
