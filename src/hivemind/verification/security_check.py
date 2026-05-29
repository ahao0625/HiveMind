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
        content_to_scan: str = ""

        if intent.tool_name == "write_file":
            # Scan the content being written
            content_to_scan = intent.parameters.get("content", "")
        elif intent.tool_name in ("read_file", "http_get", "http_post", "http_put", "http_delete"):
            # v2.0: scan output from read_file and http_* responses
            content_to_scan = getattr(result, 'output', '') or ''
        elif intent.tool_name == "run_command":
            # Scan stdout and stderr
            stdout = getattr(result, 'stdout', '') or ''
            stderr = getattr(result, 'stderr', '') or ''
            content_to_scan = stdout + stderr

        for name, pattern in self.SECRET_PATTERNS:
            if pattern.search(content_to_scan):
                issues.append(f"Potential {name} in output")

        if issues:
            return VerifyResult(passed=False, verifier_name="security", issues=issues, score=0.0)
        return VerifyResult(passed=True, verifier_name="security", score=1.0)
