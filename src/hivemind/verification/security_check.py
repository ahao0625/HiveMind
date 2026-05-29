"""Verification — security rules check (secrets, tokens in output)."""

import re
from hivemind.commander.intent_refiner import RefinedIntent
from hivemind.executors.base import ExecutorResult
from hivemind.verification.base import Verifier, VerifyResult


class SecurityVerifier(Verifier):
    SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
        ("AWS Key", re.compile(r'AKIA[0-9A-Z]{16}')),
        ("API Key", re.compile(r'(?i)(api[_-]?key|apikey|secret)\s*[:=]\s*[\'"]?[\w-]{20,}[\'"]?')),
        ("Private Key", re.compile(r'-----BEGIN (RSA|EC|DSA|OPENSSH) PRIVATE KEY-----')),
        ("JWT", re.compile(r'eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}')),
    ]

    async def verify(self, intent: RefinedIntent, result: ExecutorResult) -> VerifyResult:
        issues: list[str] = []
        if intent.tool_name == "write_file":
            content = intent.parameters.get("content", "")
            for name, pattern in self.SECRET_PATTERNS:
                if pattern.search(content): issues.append(f"Potential {name} in file content")
        if intent.tool_name == "run_command":
            for name, pattern in self.SECRET_PATTERNS:
                if pattern.search(result.stdout) or pattern.search(result.stderr):
                    issues.append(f"Potential {name} in command output")
        if issues: return VerifyResult(passed=False, verifier_name="security", issues=issues, score=0.0)
        return VerifyResult(passed=True, verifier_name="security", score=1.0)
