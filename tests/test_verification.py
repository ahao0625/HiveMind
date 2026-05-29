"""Tests for HiveMind Verification Pipeline."""

import pytest
from hivemind.commander.intent_refiner import IntentRefiner
from hivemind.executors.base import ExecutorResult
from hivemind.verification.syntax_check import SyntaxVerifier
from hivemind.verification.security_check import SecurityVerifier
from hivemind.verification.result_check import ResultVerifier
from hivemind.verification.pipeline import VerificationPipeline


@pytest.fixture
def refiner(): return IntentRefiner()


class TestSyntaxVerifier:
    @pytest.mark.asyncio
    async def test_valid_json_passes(self, refiner):
        v = SyntaxVerifier()
        intent = refiner.refine("write_file", {"path": "c.json", "content": '{"k":"v"}'})
        r = await v.verify(intent, ExecutorResult(success=True, output="ok"))
        assert r.passed is True

    @pytest.mark.asyncio
    async def test_invalid_json_fails(self, refiner):
        v = SyntaxVerifier()
        intent = refiner.refine("write_file", {"path": "c.json", "content": '{invalid}'})
        r = await v.verify(intent, ExecutorResult(success=True, output="ok"))
        assert r.passed is False

    @pytest.mark.asyncio
    async def test_non_json_skips(self, refiner):
        v = SyntaxVerifier()
        intent = refiner.refine("write_file", {"path": "README.md", "content": "# Hello"})
        r = await v.verify(intent, ExecutorResult(success=True, output="ok"))
        assert r.passed is True


class TestSecurityVerifier:
    @pytest.mark.asyncio
    async def test_detects_api_key(self, refiner):
        v = SecurityVerifier()
        intent = refiner.refine("write_file", {"path": "x.txt", "content": 'api_key="sk-abcdefghijklmnopqrstuvwxyz"'})
        r = await v.verify(intent, ExecutorResult(success=True, output="ok"))
        assert r.passed is False

    @pytest.mark.asyncio
    async def test_clean_content_passes(self, refiner):
        v = SecurityVerifier()
        intent = refiner.refine("write_file", {"path": "x.txt", "content": "hello"})
        r = await v.verify(intent, ExecutorResult(success=True, output="ok"))
        assert r.passed is True


class TestResultVerifier:
    @pytest.mark.asyncio
    async def test_success_passes(self, refiner):
        v = ResultVerifier()
        r = await v.verify(refiner.refine("write_file", {"path": "t.txt"}), ExecutorResult(success=True))
        assert r.passed is True

    @pytest.mark.asyncio
    async def test_failure_detected(self, refiner):
        v = ResultVerifier()
        r = await v.verify(refiner.refine("run_command", {"command": "ls"}), ExecutorResult(success=False, error="err"))
        assert r.passed is False


class TestPipeline:
    @pytest.mark.asyncio
    async def test_all_pass(self, refiner):
        p = VerificationPipeline([SyntaxVerifier(), SecurityVerifier(), ResultVerifier()])
        intent = refiner.refine("write_file", {"path": "d.json", "content": '{"ok":true}'})
        r = await p.verify(intent, ExecutorResult(success=True, output="ok"))
        assert r.all_passed is True

    @pytest.mark.asyncio
    async def test_fail_fast_stops(self, refiner):
        p = VerificationPipeline([SyntaxVerifier(), SecurityVerifier(), ResultVerifier()], fail_fast=True)
        intent = refiner.refine("write_file", {"path": "b.json", "content": '{bad}'})
        r = await p.verify(intent, ExecutorResult(success=True))
        assert r.all_passed is False
        assert len(r.results) == 1
