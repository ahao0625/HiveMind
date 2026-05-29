#!/usr/bin/env python3
"""Standalone verification script for HiveMind MCP Server.

Usage: PYTHONPATH=src python3 tests/verify.py
"""

import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

PASS = 0; FAIL = 0

def check(desc: str, condition: bool):
    global PASS, FAIL
    if condition: PASS += 1; print(f"  ✓ {desc}")
    else: FAIL += 1; print(f"  ✗ {desc}")

# ── 1. Imports ──────────────────────────────────────────────────
print("\n━ 1. Imports ━")
from hivemind.config import HiveMindConfig, Constitution, AuthConfig, RateLimitConfig, FileOpsConfig
check("config", True)
from hivemind.context import AppContext
check("context", True)
from hivemind.observability import setup_logger, MetricsCollector
check("observability", True)
from hivemind.gateway import AuthGuard, InjectionDetector, TokenBucketRateLimiter, AuditLogger
check("gateway", True)
from hivemind.commander.intent_refiner import IntentRefiner
from hivemind.commander.rule_engine import RuleEngine
from hivemind.commander.arbiter import Arbiter
from hivemind.commander.state_manager import StateManager, TaskState
check("commander", True)
from hivemind.executors import FileOpsExecutor, ShellOpsExecutor, HttpOpsExecutor
from hivemind.gateway.structural_guard import StructuralGuard, SlotResult, StructuralResult
from hivemind.gateway.semantic_classifier import SemanticClassifier, SemanticResult, ClassificationResult
check("executors", True)
from hivemind.executors.base import ExecutorResult
from hivemind.verification import SyntaxVerifier, SecurityVerifier, ResultVerifier, VerificationPipeline
check("verification", True)
from hivemind.memory import MemorySystem, ProceduralMemory, EnvSnapshot, GameRecord
from hivemind.memory import WorkingMemory, ShortTermMemory, LongTermMemory
check("memory", True)

# ── 2. Config ───────────────────────────────────────────────────
print("\n━ 2. Config ━")
config = HiveMindConfig.load()
check("config loads", config is not None)
check("server name", config.server.name == "HiveMind")
constitution = HiveMindConfig.default_constitution()
check("4 hard gates", len(constitution.hard_gates) == 4)
check("5 scoring dims", len(constitution.scoring_dimensions) == 5)
check("thresholds", constitution.approval_threshold == 0.40)

# ── 3. Auth ─────────────────────────────────────────────────────
print("\n━ 3. AuthGuard ━")
g = AuthGuard(AuthConfig(api_keys=["sekret"]))
check("valid key", g.authenticate("sekret").authenticated)
check("bad key rejected", not g.authenticate("bad").authenticated)
check("missing key rejected", not g.authenticate(None).authenticated)

# ── 4. Injection ────────────────────────────────────────────────
print("\n━ 4. InjectionDetector ━")
det = InjectionDetector(config.gateway.injection)
check("detects rm -rf", det.check_all("run_command", {"command": "rm -rf /"}).blocked)
check("detects traversal", det.check_all("read_file", {"path": "../../../etc/passwd"}).blocked)
check("allows safe", det.check_all("read_file", {"path": "test.txt"}).passed)

# ── 5. Rate Limiter ─────────────────────────────────────────────
print("\n━ 5. RateLimiter ━")
async def _rl():
    rl = TokenBucketRateLimiter(RateLimitConfig(tokens_per_second=10, burst_size=3))
    for i in range(3): check(f"burst {i+1}", await rl.consume("u1"))
    check("blocked after burst", not await rl.consume("u1"))
    check("separate bucket", await rl.consume("u2"))
asyncio.run(_rl())

# ── 6. Intent Refiner ───────────────────────────────────────────
print("\n━ 6. IntentRefiner ━")
ref = IntentRefiner()
i = ref.refine("read_file", {"path": "t.txt"})
check("read→low", i.risk_level == "low")
i2 = ref.refine("run_command", {"command": "rm -rf /"})
check("destructive→critical", i2.risk_level == "critical")
i3 = ref.refine("delete_file", {"path": "x"})
check("delete→high", i3.risk_level == "high")

# ── 7. Rule Engine ──────────────────────────────────────────────
print("\n━ 7. RuleEngine ━")
engine = RuleEngine(constitution)
r = engine.evaluate(ref.refine("read_file", {"path": "t.txt"}))
check("safe read ok", not r.blocked and r.overall_score > 0.4)
r2 = engine.evaluate(ref.refine("run_command", {"command": "rm -rf /"}))
check("destructive blocked", r2.blocked)
r3 = engine.evaluate(ref.refine("read_file", {"path": "/etc/passwd"}))
check("sensitive path blocked", r3.blocked)
r_r = engine.evaluate(ref.refine("read_file", {"path": "t.txt"}))
r_d = engine.evaluate(ref.refine("delete_file", {"path": "t.txt"}))
check("read > delete score", r_r.overall_score > r_d.overall_score)

# ── 8. Arbiter ──────────────────────────────────────────────────
print("\n━ 8. Arbiter ━")
arb = Arbiter(engine)
d = arb.decide(r, ref.refine("read_file", {"path": "t.txt"}))
check("safe approved", d.approved and not d.requires_human_approval)
d2 = arb.decide(r2, ref.refine("run_command", {"command": "rm -rf /"}))
check("destructive not approved", not d2.approved)

# ── 9. State Manager ────────────────────────────────────────────
print("\n━ 9. StateManager ━")
async def _sm():
    sm = StateManager()
    t = await sm.create_task("test", {"x": 1})
    check("task created", len(t.task_id) > 0 and t.state == TaskState.IDLE)
    await sm.transition(t.task_id, TaskState.PLANNING)
    check("transition ok", (await sm.get_task(t.task_id)).state == TaskState.PLANNING)
    try:
        await sm.transition(t.task_id, TaskState.COMPLETED)
        check("invalid transition caught", False)
    except ValueError:
        check("invalid transition caught", True)
asyncio.run(_sm())

# ── 10. Executor ────────────────────────────────────────────────
print("\n━ 10. FileOpsExecutor ━")
sandbox = os.path.join(os.environ.get("TMPDIR", "/tmp"), "hivemind-sandbox")
fe = FileOpsExecutor(FileOpsConfig(root_dir=sandbox))
async def _fe():
    w = await fe.execute(ref.refine("write_file", {"path": "v.txt", "content": "hello"}))
    check("write ok", w.success)
    r = await fe.execute(ref.refine("read_file", {"path": "v.txt"}))
    check("read ok", r.success and "hello" in r.output)
    d = await fe.execute(ref.refine("delete_file", {"path": "v.txt"}))
    check("delete ok", d.success)
asyncio.run(_fe())

# ── 11. Verification ────────────────────────────────────────────
print("\n━ 11. Verification ━")
async def _vf():
    sv = SyntaxVerifier()
    r = await sv.verify(ref.refine("write_file", {"path": "a.json", "content": '{"ok":1}'}), ExecutorResult(success=True))
    check("valid JSON", r.passed)
    r = await sv.verify(ref.refine("write_file", {"path": "b.json", "content": '{bad}'}), ExecutorResult(success=True))
    check("invalid JSON", not r.passed)
    sc = SecurityVerifier()
    r = await sc.verify(ref.refine("write_file", {"path": "x", "content": 'api_key="sk-longsecrethere1234567"'}), ExecutorResult(success=True))
    check("secret detected", not r.passed)
    r = await sc.verify(ref.refine("write_file", {"path": "x", "content": "hello"}), ExecutorResult(success=True))
    check("clean passes", r.passed)
    pipe = VerificationPipeline([sv, sc, ResultVerifier()], fail_fast=True)
    r = await pipe.verify(ref.refine("write_file", {"path": "d.json", "content": '{"x":1}'}), ExecutorResult(success=True))
    check("pipeline ok", r.all_passed)
    r = await pipe.verify(ref.refine("write_file", {"path": "e.json", "content": '{bad}'}), ExecutorResult(success=True))
    check("pipeline fail_fast", not r.all_passed and len(r.results) == 1)
asyncio.run(_vf())

# ── 12. Memory ─────────────────────────────────────────────────
print("\n━ 12. Memory ━")
async def _mem():
    wm = WorkingMemory(); await wm.put("k", "v")
    check("working mem", await wm.get("k") == "v")
    await wm.clear(); check("working clear", await wm.get("k") is None)
    stm = ShortTermMemory(); await stm.store("k1", "v1")
    check("short-term store", (await stm.retrieve("k1")).value == "v1")
    check("short-term search", len(await stm.search("v1")) == 1)
    mem_path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "hm-test-mem.json")
    ltm = LongTermMemory(mem_path)
    await ltm.store("hi", "world")
    check("long-term store", (await ltm.retrieve("hi")).value == "world")
    await ltm.delete("hi"); check("long-term delete", await ltm.retrieve("hi") is None)
    if os.path.exists(mem_path): os.remove(mem_path)
asyncio.run(_mem())

# ── 13. Procedural Memory (v2.0) ────────────────────────────────
print("\n━ 13. Procedural Memory ━")
from hivemind.memory.procedural import ProceduralMemory, EnvSnapshot, GameRecord
proc_mem_path = os.path.join(os.environ.get("TMPDIR", "/tmp"), "hm-proc-mem.json")
pm = ProceduralMemory(max_records=100, persistence_path=proc_mem_path)
# snapshot_environment
env = ProceduralMemory.snapshot_environment()
check("env snapshot os_name", len(env.os_name) > 0)
check("env snapshot python_version", env.python_version.startswith("3"))
check("env snapshot key_env_vars", "PATH" in env.key_env_vars)
# record a successful execution
rec = pm.record("read_file", ("path", "t.txt"), "file content here", success=True, latency_ms=5.0)
check("record creates key", len(rec.key) > 0)
check("record use_count=1", rec.use_count == 1)
# validate_before_use — should match same env
is_valid, reason = pm.validate_before_use("read_file", ("path", "t.txt"))
check("validate_before_use matches", is_valid)
# validate with unknown params
is_valid2, reason2 = pm.validate_before_use("read_file", ("path", "nonexistent.txt"))
check("validate_before_use unknown", not is_valid2)
# promote
promoted = pm.promote("read_file", ("path", "t.txt"))
check("promote increments use_count", promoted is not None and promoted.use_count == 2)
# demote + get returns None
pm.demote("read_file", ("path", "t.txt"))
check("demote removes record", pm.get("read_file", ("path", "t.txt")) is None)
# get_best_match
pm.record("read_file", ("path", "a.txt"), "aaa", success=True, latency_ms=1.0)
pm.record("read_file", ("path", "b.txt"), "bbb", success=True, latency_ms=1.0)
pm.promote("read_file", ("path", "b.txt"))
best = pm.get_best_match("read_file", ("path", "c.txt"))
check("get_best_match returns highest use_count", best is not None and best.tool_name == "read_file" and best.use_count == 2)
# cleanup
if os.path.exists(proc_mem_path): os.remove(proc_mem_path)

# ── 14. Structural Guard (v2.0) ─────────────────────────────────
print("\n━ 14. Structural Guard ━")
from hivemind.config import ParameterSlotConfig, ToolSlotConfig, InjectionStructuralConfig
slot_def = ParameterSlotConfig(param_name="path", allowed_chars=r"[a-zA-Z0-9._/-]+", max_length=256, type_constraint="str")
tool_slot = ToolSlotConfig(tool_name="read_file", slots=[slot_def])
struct_config = InjectionStructuralConfig(enabled=True, per_tool_slots=[tool_slot])
sg = StructuralGuard(struct_config)
r = sg.validate("read_file", {"path": "test.txt"})
check("structural pass clean", r.passed and len(r.blocked_params) == 0)
r2 = sg.validate("read_file", {"path": "bad;rm -rf /"})
check("structural block shell", not r2.passed and "path" in r2.blocked_params)
r3 = sg.validate("read_file", {"path": "x" * 300})
check("structural block length", not r3.passed)
# disabled guard
disabled_config = InjectionStructuralConfig(enabled=False, per_tool_slots=[tool_slot])
sg_disabled = StructuralGuard(disabled_config)
r4 = sg_disabled.validate("read_file", {"path": "bad;stuff"})
check("structural disabled passes", r4.passed)

# ── 15. Semantic Classifier (v2.0) ──────────────────────────────
print("\n━ 15. Semantic Classifier ━")
sem_config = config.gateway.injection.semantic
sc = SemanticClassifier(sem_config)
sr = sc.classify("run_command", {"command": "cat /etc/passwd"})
check("semantic block sensitive file", sr.has_blocks)
sr2 = sc.classify("run_command", {"command": "ls -la"})
check("semantic pass clean", not sr2.has_blocks and not sr2.has_downgrades)
sr3 = sc.classify("run_command", {"command": "echo hello; echo world"})
check("semantic downgrade semicolon", sr3.has_downgrades and "command" in sr3.downgraded_params)
# downgrade sanitizer (value with shell metachars triggers cleanup)
cleaned = SemanticClassifier.downgrade("test'$(whoami)'.txt")
check("downgrade removes shell chars", "$(whoami)" not in cleaned)

# ── 16. InjectionDetector v2.0 (structural + semantic) ──────────
print("\n━ 16. InjectionDetector v2.0 ━")
inj_v2 = InjectionDetector(config.gateway.injection)
r_v2 = inj_v2.check_all("read_file", {"path": "normal.txt"})
check("v2 passes clean", r_v2.passed and not r_v2.blocked)
r_v2b = inj_v2.check_all("run_command", {"command": "cat /etc/shadow"})
check("v2 block semantic", r_v2b.blocked)
# downgraded params applied
r_v2d = inj_v2.check_all("run_command", {"command": "echo a; echo b"})
check("v2 downgrade params", "command" in r_v2d.downgraded_params)

# ── 17. MemorySystem Facade (v2.0) ──────────────────────────────
print("\n━ 17. MemorySystem Facade ━")
ms = MemorySystem(config.memory)
check("facade __getitem__ long_term", ms["long_term"] is ms.long_term)
check("facade __getitem__ short_term", ms["short_term"] is ms.short_term)
check("facade __getitem__ working", ms["working"] is ms.working)
check("facade __getitem__ procedural", ms["procedural"] is ms.procedural)
# record_procedural delegate
rec2 = ms.record_procedural("list_files", ("path", "/"), "file1\nfile2", success=True, latency_ms=3.0)
check("facade record_procedural", rec2.key.startswith("list_files"))
is_v, _ = ms.validate_procedural("list_files", ("path", "/"))
check("facade validate_procedural", is_v)
# search_all
async def _ms_search():
    await ms.short_term.store("search_test", "hello world value")
    results = await ms.search_all("hello world", limit=5)
    check("facade search_all", len(results) > 0 and any(r["key"] == "search_test" for r in results))
asyncio.run(_ms_search())
# cleanup procedural persistence
proc_path = os.path.expanduser(config.memory.procedural.persistence_path)
if os.path.exists(proc_path): os.remove(proc_path)

# ── Results ─────────────────────────────────────────────────────
total = PASS + FAIL
print(f"\n{'='*50}\nResults: {PASS}/{total} passed, {FAIL} failed\n{'='*50}")
sys.exit(0 if FAIL == 0 else 1)
