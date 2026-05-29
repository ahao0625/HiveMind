"""Tests for HiveMind Gateway — auth, injection (v2.0), rate limiting."""

import pytest
from hivemind.config import AuthConfig, RateLimitConfig, InjectionConfig
from hivemind.gateway.auth import AuthGuard
from hivemind.gateway.injection import InjectionDetector
from hivemind.gateway.rate_limiter import TokenBucketRateLimiter


class TestAuthGuard:
    def test_valid_key_accepted(self):
        g = AuthGuard(AuthConfig(api_keys=["test-key-123"]))
        assert g.authenticate("test-key-123").authenticated is True

    def test_invalid_key_rejected(self):
        g = AuthGuard(AuthConfig(api_keys=["test-key-123"]))
        assert g.authenticate("wrong-key").authenticated is False

    def test_missing_key_rejected(self):
        g = AuthGuard(AuthConfig(api_keys=["test-key-123"]))
        assert g.authenticate(None).authenticated is False

    def test_disabled_auth_passes(self):
        g = AuthGuard(AuthConfig(enabled=False))
        assert g.authenticate(None).authenticated is True


class TestInjectionDetector:
    @pytest.fixture
    def det(self):
        return InjectionDetector(InjectionConfig())

    def test_detects_command_injection(self, det):
        r = det.check_all("run_command", {"command": "cat /etc/passwd; rm -rf /"})
        assert r.blocked is True

    def test_detects_path_traversal(self, det):
        r = det.check_all("read_file", {"path": "../../../etc/passwd"})
        assert r.blocked is True

    def test_detects_sql_injection(self, det):
        r = det.check_all("run_command", {"command": "SELECT * FROM users; DROP TABLE users;"})
        assert r.blocked is True

    def test_allows_safe_input(self, det):
        r = det.check_all("read_file", {"path": "test.txt"})
        assert r.passed is True

    def test_disabled_detector_passes(self):
        det = InjectionDetector(InjectionConfig(enabled=False))
        r = det.check_all("run_command", {"command": "rm -rf /"})
        assert r.passed is True

    # v2.0: structural guard tests
    def test_structural_guard_blocks_illegal_chars(self, det):
        r = det.check_structural("read_file", {"path": "bad;rm -rf /"})
        assert r.passed is False

    def test_structural_guard_passes_clean(self, det):
        r = det.check_structural("read_file", {"path": "test.txt"})
        assert r.passed is True

    # v2.0: semantic classifier tests
    def test_semantic_blocks_high_confidence(self, det):
        r = det.check_semantic("run_command", {"command": "cat /etc/shadow"})
        assert r.has_blocks is True

    def test_semantic_passes_clean(self, det):
        r = det.check_semantic("run_command", {"command": "ls -la"})
        assert not r.has_blocks


class TestRateLimiter:
    @pytest.fixture
    def rl(self):
        return TokenBucketRateLimiter(RateLimitConfig(tokens_per_second=10, burst_size=5))

    @pytest.mark.asyncio
    async def test_allows_within_burst(self, rl):
        for _ in range(5):
            assert await rl.consume("u1") is True

    @pytest.mark.asyncio
    async def test_blocks_beyond_burst(self, rl):
        for _ in range(5):
            await rl.consume("u1")
        assert await rl.consume("u1") is False

    @pytest.mark.asyncio
    async def test_separate_buckets(self, rl):
        for _ in range(5):
            await rl.consume("u1")
        assert await rl.consume("u2") is True

    @pytest.mark.asyncio
    async def test_disabled_limiter_passes(self):
        rl = TokenBucketRateLimiter(RateLimitConfig(enabled=False))
        for _ in range(100):
            assert await rl.consume("u1") is True
