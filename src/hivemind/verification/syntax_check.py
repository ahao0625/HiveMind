"""Verification — syntax/format validation."""

import json
from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.executors.base import ExecutorResult
from hivemind.verification.base import Verifier, VerifyResult


class SyntaxVerifier(Verifier):
    async def verify(self, intent: RefinedIntent, result: ExecutorResult) -> VerifyResult:
        if intent.tool_name != "write_file": return VerifyResult(passed=True, verifier_name="syntax", score=1.0)
        path = intent.parameters.get("path", "")
        content = intent.parameters.get("content", "")
        if path.endswith(".json"):
            try:
                json.loads(content)
            except json.JSONDecodeError as e:
                return VerifyResult(passed=False, verifier_name="syntax", issues=[f"Invalid JSON: {e}"], score=0.0)
        if path.endswith((".yaml", ".yml")) and "\t" in content:
            return VerifyResult(passed=False, verifier_name="syntax", issues=["YAML contains tab characters"], score=0.0)
        return VerifyResult(passed=True, verifier_name="syntax", score=1.0)
