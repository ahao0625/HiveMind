# HiveMind MCP Server

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-1.12%2B-purple)](https://modelcontextprotocol.io)
[English](README.md) | [中文](README_CN.md)

**External Commander Framework** — AI thinks. The framework decides.

## What Is This?

Every time AI runs a command or touches a file, you're gambling. Stuffing "never do X" into the prompt doesn't help — it forgets, and your tokens go up in smoke.

HiveMind does one thing: **AI thinks. The framework decides.** What's allowed, what's not, and whether the result checks out — all enforced outside the prompt. Operations you approve once shortcut forever after. Doesn't eat your tokens. Gets faster the more you use it.

## What It Can Do

- 🛡️ **Two-layer injection defense** — Structural guard validates each parameter's characters, type, and length; Semantic classifier blocks known attacks (≥95% confidence) and silently downgrades suspicious input (50–95%)
- 📊 **Smart scoring** — Read files pass automatically; writes get checked; deletes require strict approval
- 🔍 **Post-execution verification** — Syntax check, secret leak scan (API keys, JWTs, private keys), result integrity — with automatic rollback on failure
- ⚡ **System 1/2 routing** — Read-only ops take the fast path (<10ms); writes go through full security → execute → verify → record
- 🧠 **Four-tier memory** — Working (per-task), Short-term (TTL), Long-term (JSON), Procedural (env snapshots for "faster with use")
- 🔄 **Rollback on failure** — Pre-write snapshots; verification fails → file restored automatically
- 🌐 **SSRF protection** — Internal IP blocking (RFC1918, loopback, multicast) + redirect guard on every hop
- 📝 **Full audit trail** — Who did what, when, which layer blocked it, what the final score was — all traceable

**In one sentence: Let AI help you, but don't let it run wild.**

---

## Architecture

```
MCP Client (Claude / Cursor / ...)
        │
        ▼
┌─ Gateway ───────────────────────────────────────────────────┐
│  Auth → Structural Guard (per-param slots)                  │
│       → Semantic Classifier (confidence: block/downgrade/log)│
│       → Token Bucket Rate Limiter                           │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌─ Commander ─────────────────────────────────────────────────┐
│  Intent Refinement → Rule Engine → Arbiter → Task Router    │
│                                                             │
│  Hard Gates: one-vote veto   Soft Scoring: weighted sum     │
│  System 1 (cached → verify env → fast path)                 │
│  System 2 (execute → verify pipeline → record → audit)     │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌─ Executor ──────────────────────────────────────────────────┐
│  File (sandbox + pre-mutation snapshots)                    │
│  Shell (binary allowlist)                                   │
│  HTTP (domain allowlist + SSRF + redirect guard)            │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌─ Verification Pipeline ─────────────────────────────────────┐
│  Syntax → Security (secret leak scan) → Result integrity    │
│  ┌─ Fail → rollback (restore from snapshot)                │
│  └─ Pass → cleanup snapshot + record procedural memory     │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌─ Memory (4 tiers) ──────────────────────────────────────────┐
│  Working (task) / Short-term (TTL) / Long-term (JSON)       │
│  Procedural (env snapshots → faster with use)               │
└─────────────────────────────────────────────────────────────┘
```

### Dual-Layer Rule Engine

| Layer | Mechanism | Behavior | Example |
|-------|-----------|----------|---------|
| **Hard Gates** | One-vote veto | Any rule fails → rejected immediately | No `rm -rf /`, no reading `/etc/passwd` |
| **Soft Scoring** | Weighted sum (5 dimensions) | ≥0.40 auto-approve / 0.40–0.70 human review / <0.30 reject | Read scores high, write lower, delete lowest |

### Two-Layer Injection Detection

| Layer | Type | Mechanism | False Positives |
|-------|------|-----------|-----------------|
| **Structural Guard** | Deterministic | Per-parameter slot: character allowlist, type constraint, max length | Zero |
| **Semantic Classifier** | Confidence-based | ≥95% → hard block / 50–95% → silent downgrade / 30–50% → log only | Near-zero |

---

## Quick Start

### Install

```bash
# Recommended: use venv to avoid macOS PEP 668 restrictions
python3 -m venv .venv && source .venv/bin/activate
pip install git+https://github.com/ahao0625/HiveMind.git

# Or clone + dev install
git clone https://github.com/ahao0625/HiveMind.git
cd HiveMind
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

> `structlog` is optional — falls back to stdlib `logging` automatically.

### Run

```bash
hivemind
```

### Verify

```bash
PYTHONPATH=src python3 tests/verify.py
# Expected: Results: 79/79 passed, 0 failed
```

```bash
pytest tests/ -v
```

---

## MCP Client Config

### Option 1: After pip install (recommended)

```json
{
  "mcpServers": {
    "hivemind": {
      "command": "hivemind",
      "env": {
        "HIVEMIND_API_KEYS": "your-api-key"
      }
    }
  }
}
```

### Option 2: Dev mode

```json
{
  "mcpServers": {
    "hivemind": {
      "command": "python3",
      "args": ["-m", "hivemind.server"],
      "env": {
        "PYTHONPATH": "/path/to/HiveMind/src",
        "HIVEMIND_API_KEYS": "your-api-key"
      },
      "cwd": "/path/to/HiveMind"
    }
  }
}
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `HIVEMIND_API_KEYS` | Comma-separated API keys; empty = no auth | `""` |
| `JSON_LOG` | Set to `1` for JSON-formatted logs (production) | off |
| `HIVEMIND_CONSTITUTION_PATH` | Custom rule set config file path | `~/.hivemind/constitution.json` |

### Constitution File (constitution.json)

Set `HIVEMIND_CONSTITUTION_PATH` to point to a custom rule set:

```json
{
  "hard_gates": [
    {
      "id": "no_destructive_commands",
      "name": "No Destructive Commands",
      "description": "Blocks rm -rf, format, etc.",
      "priority": 100,
      "check_function": "hivemind.commander.rule_engine:check_no_destructive_commands"
    }
  ],
  "scoring_dimensions": [
    {
      "id": "safety",
      "name": "Safety",
      "description": "How safe is this operation?",
      "weight": 0.40,
      "score_function": "hivemind.commander.rule_engine:score_safety"
    }
  ],
  "approval_threshold": 0.40,
  "human_approval_threshold": 0.70
}
```

> `check_function` / `score_function` are loaded dynamically via `importlib`, so you can extend without modifying source code.

---

## API Reference

### Tools

#### File Operations

| Tool | Parameters | Returns |
|------|-----------|---------|
| `read_file` | `path: str` | File contents |
| `write_file` | `path: str`, `content: str` | `[OK]` or `[VERIFICATION FAILED]` |
| `delete_file` | `path: str` | `[OK]` |
| `list_files` | `path: str` (default `"."`) | Directory listing |

#### Shell

| Tool | Parameters | Returns |
|------|-----------|---------|
| `run_command` | `command: str`, `cwd: str?` | stdout + verification warnings |

> Shell execution is protected by a binary allowlist — only safe commands can run.

#### HTTP

| Tool | Parameters |
|------|-----------|
| `http_get` | `url: str` |
| `http_post` | `url: str`, `body: str`, `content_type: str` |
| `http_put` | `url: str`, `body: str`, `content_type: str` |
| `http_delete` | `url: str` |

> HTTP requests are protected by domain allowlist, internal IP blocking (SSRF), and redirect guard.

#### Memory

| Tool | Parameters | Description |
|------|-----------|-------------|
| `store_memory` | `key: str`, `value: str` | Save to long-term memory |
| `recall_memory` | `query: str`, `limit: int` | Search memory (short-term + long-term) |

#### Observability

| Tool | Description |
|------|------------|
| `get_constitution` | View the active rule set |
| `get_audit_trail` | View the last 50 audit records |
| `get_metrics` | View counters, gauges, latency histograms |

### Resources

| URI | Content |
|-----|---------|
| `hivemind://constitution` | Current rule set as JSON |
| `hivemind://status` | Server health status |

### Prompts

| Prompt | Purpose |
|--------|---------|
| `plan_task` | Guide AI through task planning |
| `review_result` | Guide AI through result review |
| `troubleshoot` | Guide AI through error diagnosis |

---

## Security Model

Every tool call passes through seven checkpoints:

1. **Authentication** — API Key validation; reject unauthenticated requests
2. **Structural Guard** — Per-parameter slot validation (character allowlist, type constraints, length limits); deterministic, zero false positives
3. **Semantic Classifier** — Confidence-based attack detection: ≥95% hard block, 50–95% silent downgrade (attacker gets no feedback), 30–50% log only
4. **Rate Limiting** — Token bucket per identity; prevent abuse
5. **Intent Refinement** — Auto-assess risk level (low / medium / high / critical)
6. **Rule Engine** — Hard gates (one-vote veto) + Soft scoring (5 weighted dimensions)
7. **Verification Pipeline** — Post-execution: syntax → secret leak scan → result integrity; fail triggers rollback from pre-mutation snapshot

### Executor Safety

| Executor | Protection |
|----------|-----------|
| File Ops | Sandbox root enforcement; pre-write snapshots for rollback; path traversal blocked |
| Shell | Binary allowlist; unknown commands rejected |
| HTTP | Domain allowlist; internal IP blocked (RFC1918, loopback, link-local, multicast, IPv6 private); redirect target validated on every hop |

---

## Project Structure

```
HiveMind/
├── pyproject.toml
├── README.md
├── README_CN.md
├── .env.example
├── .gitignore
├── src/hivemind/
│   ├── __init__.py
│   ├── config.py              # All Pydantic configuration models (v2.0: +6 new classes)
│   ├── context.py             # AppContext — runtime shared state
│   ├── server.py              # FastMCP entry point (15 tools/resources/prompts)
│   ├── gateway/
│   │   ├── auth.py            # API Key authentication
│   │   ├── injection.py       # Two-layer injection detection (v2.0 refactor)
│   │   ├── structural_guard.py # v2.0: per-parameter slot validation
│   │   ├── semantic_classifier.py # v2.0: confidence-based attack classification
│   │   ├── rate_limiter.py    # Token bucket rate limiter
│   │   └── audit.py           # Audit log (ring buffer)
│   ├── commander/
│   │   ├── intent_refiner.py  # Intent refinement + risk classification
│   │   ├── rule_engine.py     # Hard gates + soft scoring engine
│   │   ├── arbiter.py         # Final arbitration
│   │   ├── task_router.py     # System 1 (fast) / System 2 (full) routing
│   │   ├── state_manager.py   # Task FSM (v2.0: rollback + escalation states)
│   │   └── lifecycle.py       # Central orchestrator (v2.0: verifier + procedural memory wired)
│   ├── executors/
│   │   ├── base.py            # Abstract base class
│   │   ├── file_ops.py        # Sandboxed file ops (v2.0: pre-mutation snapshots)
│   │   ├── shell_ops.py       # Allowlist-based shell execution
│   │   └── http_ops.py        # Domain-allowlist HTTP (v2.0: SSRF + redirect guard)
│   ├── verification/
│   │   ├── base.py            # Abstract base class
│   │   ├── pipeline.py        # Pipeline orchestrator (supports fail_fast)
│   │   ├── syntax_check.py    # JSON/YAML syntax validation
│   │   ├── security_check.py  # Secret leak scanner (v2.0: +read_file +http_* output scan)
│   │   └── result_check.py    # Exit code / integrity check
│   ├── memory/
│   │   ├── working.py         # Working memory (v2.0: max_bytes eviction)
│   │   ├── short_term.py      # Short-term memory (TTL cache)
│   │   ├── long_term.py       # Long-term memory (v2.0: atomic write)
│   │   ├── procedural.py      # v2.0: procedural memory (env snapshots → faster with use)
│   │   ├── consistency.py     # v2.0: cross-tier consistency manager
│   │   └── facade.py          # v2.0: MemorySystem unified facade
│   └── observability/
│       ├── logger.py          # structlog / stdlib dual-mode
│       └── metrics.py         # Counters, gauges, histograms
└── tests/
    ├── verify.py              # Standalone verification (79 checks)
    ├── test_rule_engine.py
    ├── test_gateway.py        # v2.0: +structural guard +semantic classifier tests
    ├── test_verification.py   # v2.0: +read_file +http_* output scanning tests
    ├── test_procedural_memory.py   # v2.0
    ├── test_memory_system.py       # v2.0
    └── test_lifecycle_v2.py        # v2.0
```

---

## Design Principles

- **Immutability** — All Pydantic models are `frozen=True`; create, never mutate
- **Constitution as Code** — Rules via JSON config, loaded dynamically with `importlib`; extend without touching source
- **Full Audit Trail** — Gateway → Arbiter → Executor → Verification, every step traceable
- **System 1/2 Routing** — Cache hits + low risk take the fast path; writes + high risk go through full verification → rollback on failure
- **Defense in Depth** — Dual-layer injection (structural + semantic), SSRF protection, secret scanning, pre-mutation snapshots
- **Atomic Persistence** — All file writes use `tempfile.mkstemp` + `os.replace` to prevent corruption on crash
- **越用越快 (Faster with Use)** — Procedural memory records execution results with environment snapshots; reuses cached results only when the environment hasn't changed

---

## FAQ

### What is the API Key for? I already have a Claude API key.

`HIVEMIND_API_KEYS` is not a third-party service key — it's **HiveMind's own door lock**.

Your Claude API key identifies you to Anthropic. HiveMind's key identifies the MCP client to HiveMind. Two different keys for two different doors.

You can leave it empty to skip authentication entirely. Setting it just adds an extra layer so unknown MCP clients can't connect and operate on your files.

### Why was my command blocked?

Three possible layers:

- **Structural Guard** — A parameter contained illegal characters, was too long, or had the wrong type. For example, a path containing `;` or a 300-character filename.
- **Hard Gate** — Unconditional rejection. For example, `rm -rf /`, reading `/etc/passwd`, path traversal with `../` are always blocked.
- **Soft Scoring** — Risk-weighted. Writes and deletes score lower than reads. Below threshold, human approval is required.

If a safe operation is being falsely blocked, run `get_constitution` to see the active rules, then customize your `constitution.json`.

### What happens when verification fails?

The operation is rolled back — files are restored from pre-mutation snapshots (`.hivemind-bak`). The task is marked as failed. No partial or corrupted state is left behind.

### "ImportError: cannot import name ..."

Almost always a `PYTHONPATH` issue. Make sure you're in the project root:

```bash
PYTHONPATH=src python3 -m hivemind.server
#                          ↑ must be run from HiveMind root directory
```

Or skip `PYTHONPATH` entirely by installing with pip:

```bash
pip install git+https://github.com/ahao0625/HiveMind.git
hivemind
```

### Can't install structlog?

structlog is optional. Without it, HiveMind falls back to Python's standard `logging` module. All features work identically — you just get plain-text logs instead of colored structured output.

### FileOpsExecutor: PermissionError

The default sandbox directory is `$TMPDIR/hivemind-sandbox`. On some systems (e.g. macOS sandbox), writing to `/tmp` is restricted. Override it:

```bash
export HIVEMIND_SANDBOX_ROOT="$HOME/.hivemind/sandbox"
```

### How do I add custom security rules?

Create `~/.hivemind/constitution.json` and add your own hard gates or scoring dimensions:

```json
{
  "hard_gates": [
    {
      "id": "custom_rule",
      "name": "My Custom Rule",
      "description": "Prevents modifying .env files",
      "priority": 50,
      "check_function": "my_module.rules:check_env_file"
    }
  ]
}
```

The format for `check_function` is `module.path:function_name`. HiveMind loads it dynamically via `importlib`. Function signature:

```python
def check_env_file(intent: RefinedIntent) -> GateResult:
    ...
```

### How do I see what happened?

Use the `get_audit_trail` tool to view the last 50 audit records. Each entry includes: timestamp, caller identity, tool name, gateway result, arbiter decision, execution result, and verification result.

---

## License

MIT
