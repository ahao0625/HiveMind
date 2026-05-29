"""HiveMind MCP Server — External Commander Framework.

Architecture: Gateway → Commander → Executor → Verification → Memory
Principle: AI has suggestion rights only; the framework holds execution rights.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP, Context
from mcp.server.session import ServerSession

from hivemind.config import HiveMindConfig
from hivemind.context import AppContext
from hivemind.observability import setup_logger, MetricsCollector
from hivemind.gateway import AuthGuard, InjectionDetector, TokenBucketRateLimiter, AuditLogger
from hivemind.commander import RuleEngine, Arbiter, TaskRouter, StateManager, TaskLifecycle
from hivemind.commander.intent_refiner import IntentRefiner
from hivemind.executors import FileOpsExecutor, ShellOpsExecutor, HttpOpsExecutor
from hivemind.verification import VerificationPipeline, SyntaxVerifier, SecurityVerifier, ResultVerifier
from hivemind.memory import WorkingMemory, ShortTermMemory, LongTermMemory

# ── Lifespan ─────────────────────────────────────────────────────

@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize all HiveMind subsystems at startup, clean up at shutdown."""
    config = HiveMindConfig.load()
    if not config.commander.constitution.hard_gates:
        config.commander.constitution = HiveMindConfig.default_constitution()

    logger = setup_logger()
    metrics = MetricsCollector()

    # Gateway
    auth = AuthGuard(config.gateway.auth)
    injection = InjectionDetector(config.gateway.injection)
    rate_limiter = TokenBucketRateLimiter(config.gateway.rate_limit)
    audit = AuditLogger()

    # Commander
    rule_engine = RuleEngine(config.commander.constitution)
    arbiter = Arbiter(rule_engine)
    router = TaskRouter()
    state_manager = StateManager()

    # Memory
    working_mem = WorkingMemory(config.memory.working.max_bytes)
    short_term_mem = ShortTermMemory(config.memory.short_term.max_items, config.memory.short_term.default_ttl_seconds)
    long_term_mem = LongTermMemory(config.memory.long_term.persistence_path)

    # Lifecycle (central coordinator)
    lifecycle = TaskLifecycle(
        config, auth, injection, rate_limiter, audit, metrics,
        rule_engine, arbiter, router, state_manager, long_term_mem,
    )

    # Executors
    file_exec = FileOpsExecutor(config.executors.file_ops)
    shell_exec = ShellOpsExecutor(config.executors.shell_ops)
    http_exec = HttpOpsExecutor(config.executors.http_ops)
    for tn in ("read_file", "write_file", "delete_file", "list_files"):
        lifecycle.register_executor(tn, file_exec)
    lifecycle.register_executor("run_command", shell_exec)
    for tn in ("http_get", "http_post", "http_put", "http_delete"):
        lifecycle.register_executor(tn, http_exec)

    # Verification
    verifiers = []
    if "syntax" in config.verification.enabled_checks: verifiers.append(SyntaxVerifier())
    if "security" in config.verification.enabled_checks: verifiers.append(SecurityVerifier())
    if "result" in config.verification.enabled_checks: verifiers.append(ResultVerifier())
    verification = VerificationPipeline(verifiers, config.verification.fail_fast)

    ctx = AppContext(config=config, logger=logger, gateway=auth, commander=lifecycle,
                     executors={"file": file_exec, "shell": shell_exec, "http": http_exec},
                     verifier=verification,
                     memory={"working": working_mem, "short_term": short_term_mem, "long_term": long_term_mem},
                     metrics=metrics)
    logger.info("hivemind_started version=%s", config.server.version)
    try:
        yield ctx
    finally:
        logger.info("hivemind_shutdown")


# ── FastMCP Server ───────────────────────────────────────────────

mcp = FastMCP(
    "HiveMind",
    lifespan=app_lifespan,
)

def _ctx(app: Context[ServerSession, AppContext]) -> AppContext:
    return app.request_context.lifespan_context


# ── File Tools ───────────────────────────────────────────────────

@mcp.tool()
async def read_file(path: str, ctx: Context[ServerSession, AppContext] = None) -> str:
    """Read a file from the sandbox."""
    app = _ctx(ctx)
    r = await app.commander.execute("read_file", {"path": path})
    if r.blocked: return f"[BLOCKED] {r.reason}"
    if not r.success: return f"[ERROR] {r.reason}"
    return r.data.output

@mcp.tool()
async def write_file(path: str, content: str, ctx: Context[ServerSession, AppContext] = None) -> str:
    """Write content to a file in the sandbox."""
    app = _ctx(ctx)
    r = await app.commander.execute("write_file", {"path": path, "content": content})
    if r.blocked: return f"[BLOCKED] {r.reason}"
    if not r.success: return f"[ERROR] {r.reason}"
    intent = IntentRefiner().refine("write_file", {"path": path, "content": content})
    ver = await app.verifier.verify(intent, r.data)
    if not ver.all_passed:
        issues = [i for vr in ver.results for i in vr.issues]
        return f"[VERIFICATION FAILED] {', '.join(issues)}"
    return f"[OK] {r.data.output}"

@mcp.tool()
async def delete_file(path: str, ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    r = await app.commander.execute("delete_file", {"path": path})
    if r.blocked: return f"[BLOCKED] {r.reason}"
    if not r.success: return f"[ERROR] {r.reason}"
    return f"[OK] {r.data.output}"

@mcp.tool()
async def list_files(path: str = ".", ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    r = await app.commander.execute("list_files", {"path": path})
    if r.blocked: return f"[BLOCKED] {r.reason}"
    if not r.success: return f"[ERROR] {r.reason}"
    return r.data.output

# ── Shell Tool ───────────────────────────────────────────────────

@mcp.tool()
async def run_command(command: str, cwd: str | None = None, ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    params: dict[str, Any] = {"command": command}
    if cwd: params["cwd"] = cwd
    r = await app.commander.execute("run_command", params)
    if r.blocked: return f"[BLOCKED] {r.reason}"
    if not r.success: return f"[ERROR] {r.reason}"
    intent = IntentRefiner().refine("run_command", params)
    ver = await app.verifier.verify(intent, r.data)
    out = r.data.output or r.data.stdout or "(no output)"
    if not ver.all_passed:
        issues = [i for vr in ver.results for i in vr.issues]
        return f"[WARN] {out}\n[VERIFICATION] {', '.join(issues)}"
    return out

# ── HTTP Tools ───────────────────────────────────────────────────

@mcp.tool()
async def http_get(url: str, ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    r = await app.commander.execute("http_get", {"url": url})
    return f"[BLOCKED] {r.reason}" if r.blocked else (f"[ERROR] {r.reason}" if not r.success else r.data.output)

@mcp.tool()
async def http_post(url: str, body: str = "", content_type: str = "application/json",
                    ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    r = await app.commander.execute("http_post", {"url": url, "body": body, "content_type": content_type})
    return f"[BLOCKED] {r.reason}" if r.blocked else (f"[ERROR] {r.reason}" if not r.success else r.data.output)

@mcp.tool()
async def http_put(url: str, body: str = "", content_type: str = "application/json",
                   ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    r = await app.commander.execute("http_put", {"url": url, "body": body, "content_type": content_type})
    return f"[BLOCKED] {r.reason}" if r.blocked else (f"[ERROR] {r.reason}" if not r.success else r.data.output)

@mcp.tool()
async def http_delete(url: str, ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    r = await app.commander.execute("http_delete", {"url": url})
    return f"[BLOCKED] {r.reason}" if r.blocked else (f"[ERROR] {r.reason}" if not r.success else r.data.output)

# ── Memory Tools ─────────────────────────────────────────────────

@mcp.tool()
async def store_memory(key: str, value: str, ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    await app.memory["long_term"].store(key, value)
    return f"[OK] Stored '{key}' in long-term memory."

@mcp.tool()
async def recall_memory(query: str, limit: int = 10, ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    results = await app.memory["long_term"].search(query, limit)
    if not results: results = await app.memory["short_term"].search(query, limit)
    if not results: return "No matching memory entries found."
    lines = [f"- **{r.key}** (accessed {r.access_count}x): {r.value[:120].replace(chr(10), ' ')}..." for r in results]
    return "\n".join(lines)

# ── Observability Tools ──────────────────────────────────────────

@mcp.tool()
async def get_constitution(ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    c = app.config.commander.constitution
    gates = "\n".join(f"- [{g.id}] {g.name}: {g.description}" for g in c.hard_gates)
    dims = "\n".join(f"- [{d.id}] {d.name} (w={d.weight}): {d.description}" for d in c.scoring_dimensions)
    return f"## Constitution\nThresholds: approval={c.approval_threshold} human={c.human_approval_threshold}\n\n### Hard Gates\n{gates}\n\n### Soft Scoring\n{dims}"

@mcp.tool()
async def get_audit_trail(limit: int = 50, ctx: Context[ServerSession, AppContext] = None) -> str:
    app = _ctx(ctx)
    events = await app.gateway.recent(limit) if hasattr(app.gateway, 'recent') else []
    if not events: return "No audit events recorded yet."
    return "\n".join(
        f"{'✓' if e.arbiter_decision == 'approved' else '✗'} [{e.timestamp[:19]}] {e.tool_name} | "
        f"gw={e.gateway_result} arb={e.arbiter_decision} exec={e.executor_result} vfy={e.verification_result}"
        for e in events
    )

@mcp.tool()
async def get_metrics(ctx: Context[ServerSession, AppContext] = None) -> str:
    return json.dumps(await _ctx(ctx).metrics.snapshot(), indent=2)

# ── Resources ────────────────────────────────────────────────────

@mcp.resource("hivemind://constitution")
async def resource_constitution() -> str:
    c = HiveMindConfig.default_constitution()
    return json.dumps({
        "hard_gates": [{"id": g.id, "name": g.name, "priority": g.priority} for g in c.hard_gates],
        "scoring_dimensions": [{"id": d.id, "name": d.name, "weight": d.weight} for d in c.scoring_dimensions],
        "approval_threshold": c.approval_threshold, "human_approval_threshold": c.human_approval_threshold,
    }, indent=2)

@mcp.resource("hivemind://status")
async def resource_status() -> str:
    return json.dumps({"server": "HiveMind", "version": "0.1.0", "status": "healthy"}, indent=2)

# ── Prompts ──────────────────────────────────────────────────────

@mcp.prompt()
async def plan_task(goal: str, constraints: str = "") -> str:
    c = f"\n\nConstraints:\n{constraints}" if constraints else ""
    return f"You are in the HiveMind framework. AI suggests, framework decides.\n\n## Goal\n{goal}{c}\n\nBreak down into steps. Prefer read operations (read_file, list_files) over writes. Always have a fallback."

@mcp.prompt()
async def review_result(action: str, result_summary: str) -> str:
    return f"Review: {action}\nResult: {result_summary}\n\nConsider: goal achieved? side effects? store learnings (store_memory)?"

@mcp.prompt()
async def troubleshoot(error_summary: str, context: str = "") -> str:
    c = f"\nContext: {context}" if context else ""
    return f"Troubleshoot: {error_summary}{c}\n\nIdentify root cause. If blocked by safety rule, explain why. Suggest safer alternative."

# ── Entry Point ──────────────────────────────────────────────────

def main():
    mcp.run()

if __name__ == "__main__":
    main()
