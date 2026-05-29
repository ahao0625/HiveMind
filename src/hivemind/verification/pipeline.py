"""Verification — pipeline orchestrator."""

from pydantic import BaseModel, Field
from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.executors.base import ExecutorResult
from hivemind.verification.base import Verifier, VerifyResult


class PipelineResult(BaseModel):
    all_passed: bool
    results: list[VerifyResult] = Field(default_factory=list)
    combined_score: float = 1.0


class VerificationPipeline:
    def __init__(self, verifiers: list[Verifier], fail_fast: bool = True) -> None:
        self._verifiers = verifiers
        self._fail_fast = fail_fast

    async def verify(self, intent: RefinedIntent, result: ExecutorResult) -> PipelineResult:
        all_results: list[VerifyResult] = []
        for verifier in self._verifiers:
            vr = await verifier.verify(intent, result)
            all_results.append(vr)
            if not vr.passed and self._fail_fast: break
        all_passed = all(r.passed for r in all_results)
        avg = sum(r.score for r in all_results) / len(all_results) if all_results else 1.0
        return PipelineResult(all_passed=all_passed, results=all_results, combined_score=round(avg, 4))
