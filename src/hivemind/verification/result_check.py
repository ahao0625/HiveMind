"""Verification — result integrity check."""

from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.executors.base import ExecutorResult
from hivemind.verification.base import Verifier, VerifyResult


class ResultVerifier(Verifier):
    async def verify(self, intent: RefinedIntent, result: ExecutorResult) -> VerifyResult:
        issues: list[str] = []
        if not result.success: issues.append(f"Executor failed: {result.error}")
        if intent.tool_name == "run_command":
            exit_code = result.metadata.get("exit_code")
            if exit_code is not None and exit_code != 0:
                issues.append(f"Exit code {exit_code}")
        if issues: return VerifyResult(passed=False, verifier_name="result", issues=issues, score=0.0)
        return VerifyResult(passed=True, verifier_name="result", score=1.0)
