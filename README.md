# HiveMind MCP Server

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-1.12%2B-purple)](https://modelcontextprotocol.io)
[English](README.md) | [中文](README_CN.md)

**External Commander Framework** — AI suggests, the framework decides.

## What Is This?

When you ask an AI to "clean up my desktop folder," it might run `rm -rf ~/Desktop/*`. When you ask it to "check this API response," it might accidentally send your secret keys to an external service.

**HiveMind is a security checkpoint between AI and your computer.** Every time an AI tries to touch your files, run a command, or make an HTTP request, HiveMind stops it and asks six questions:

1. Who are you? (API Key authentication)
2. Is there malicious code in your input? (Injection detection)
3. Are you calling too fast? (Rate limiting)
4. What exactly are you trying to do? How risky is it? (Intent refinement)
5. Do the rules allow this? (Hard gates — one vote veto + Soft scoring)
6. Is the result actually safe? (Verification pipeline)

## What It Can Do

- 🛡️ **Auto-block dangerous ops** — `rm -rf /`, reading `/etc/passwd`, path traversal with `../../` — rejected instantly
- 📊 **Smart scoring** — read files pass automatically; writes get checked; deletes require strict approval
- 🔍 **Post-execution verification** — after writing a file, checks for JSON syntax errors, accidental secret leaks
- 📝 **Full audit trail** — who did what, when, what was the result, who blocked it — all traceable
- ⚡ **Fast/slow routing** — read-only ops take the fast path (<10ms); writes go through full security checks
- 🧠 **Three-tier memory** — working memory (per-task), short-term memory (TTL cache), long-term memory (persisted to JSON)

**In one sentence: Let AI help you, but don't let it run wild.**

---

## Architecture

```
MCP Client (Claude / Cursor / ...)
        │
        ▼
┌─ Gateway ──────────────────────────────────────────┐
│  Auth → Injection Detection → Token Bucket Limiter │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─ Commander ────────────────────────────────────────┐
│  Intent Refinement → Rule Engine → Arbiter → Router│
│                                                    │
│  Hard Gates: one-vote veto  Soft: ≥60 pass, <30 no │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─ Executor ─────────────────────────────────────────┐
│  File (sandbox) / Shell (allowlist) / HTTP (allowlist) │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─ Verification Pipeline ────────────────────────────┐
│  Syntax → Security (leak scan) → Result integrity  │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─ Memory ───────────────────────────────────────────┐
│  Working / Short-term (TTL) / Long-term (JSON)      │
└────────────────────────────────────────────────────┘
```

### Dual-Layer Rule Engine

| Layer | Mechanism | Behavior | Example |
|-------|-----------|----------|---------|
| **Hard Gates** | One-vote veto | Any rule fails → rejected immediately | No `rm -rf /`, no reading `/etc/passwd` |
| **Soft Scoring** | Weighted sum | ≥0.60 auto-approve / 0.30–0.59 human review / <0.30 reject | Read scores high, write lower, delete lowest |

---

## Quick Start

### Install

```bash
# Option 1: pip install (recommended)
pip install git+https://github.com/ahao0625/HiveMind.git

# Option 2: clone + dev mode
git clone https://github.com/ahao0625/HiveMind.git
cd HiveMind
pip install -e ".[dev]"
```

> `structlog` is optional — falls back to stdlib `logging` automatically.

### Run

```bash
# After pip install, use the command directly
hivemind

# Or in dev mode
PYTHONPATH=src python3 -m hivemind.server
```

### Verify

```bash
PYTHONPATH=src python3 tests/verify.py
# Expected: Results: 51/51 passed, 0 failed
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

> HTTP requests are protected by a domain allowlist.

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

Every tool call passes through six checkpoints:

1. **Authentication** — API Key validation; reject unauthenticated requests
2. **Injection Detection** — Command injection (`; rm -rf /`), SQL injection, path traversal (`../../etc/passwd`)
3. **Rate Limiting** — Token bucket per identity; prevent abuse
4. **Intent Refinement** — Auto-assess risk level (low / medium / high / critical)
5. **Rule Engine** — Hard gates (one-vote veto) + Soft scoring (weighted sum)
6. **Verification Pipeline** — Post-execution: syntax → secret leak scan → result integrity

### Executor Safety

| Executor | Protection |
|----------|-----------|
| File Ops | Sandbox root enforcement; path traversal blocked |
| Shell | Binary allowlist; unknown commands rejected |
| HTTP | Domain allowlist; internal addresses blocked |

---

## Project Structure

```
HiveMind/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── src/hivemind/
│   ├── __init__.py
│   ├── config.py              # All Pydantic configuration models
│   ├── context.py             # AppContext — runtime shared state
│   ├── server.py              # FastMCP entry point (15 tools/resources/prompts)
│   ├── gateway/
│   │   ├── auth.py            # API Key authentication
│   │   ├── injection.py       # Injection detection (command/SQL/path traversal)
│   │   ├── rate_limiter.py    # Token bucket rate limiter
│   │   └── audit.py           # Audit log (ring buffer)
│   ├── commander/
│   │   ├── intent_refiner.py  # Intent refinement + risk classification
│   │   ├── rule_engine.py     # Hard gates + soft scoring engine
│   │   ├── arbiter.py         # Final arbitration
│   │   ├── task_router.py     # System 1 (fast) / System 2 (full) routing
│   │   ├── state_manager.py   # Task state machine (FSM)
│   │   └── lifecycle.py       # Central orchestrator
│   ├── executors/
│   │   ├── base.py            # Abstract base class
│   │   ├── file_ops.py        # Sandboxed file read/write/delete
│   │   ├── shell_ops.py       # Allowlist-based shell execution
│   │   └── http_ops.py        # Domain-allowlist HTTP client
│   ├── verification/
│   │   ├── base.py            # Abstract base class
│   │   ├── pipeline.py        # Pipeline orchestrator (supports fail_fast)
│   │   ├── syntax_check.py    # JSON/YAML syntax validation
│   │   ├── security_check.py  # API key / private key leak scanner
│   │   └── result_check.py    # Exit code / integrity check
│   ├── memory/
│   │   ├── working.py         # Working memory (per-task isolation)
│   │   ├── short_term.py      # Short-term memory (TTL cache)
│   │   └── long_term.py       # Long-term memory (JSON file persistence)
│   └── observability/
│       ├── logger.py          # structlog / stdlib dual-mode
│       └── metrics.py         # Counters, gauges, histograms
└── tests/
    ├── verify.py              # Standalone verification (51 checks)
    ├── test_rule_engine.py
    ├── test_gateway.py
    └── test_verification.py
```

---

## Design Principles

- **Immutability** — All Pydantic models are `frozen=True`; create, never mutate
- **Constitution as Code** — Rules via JSON config, loaded dynamically with `importlib`; extend without touching source
- **Full Audit Trail** — Gateway → Arbiter → Executor → Verification, every step traceable
- **System 1/2 Routing** — Cache hits + low risk take the fast path; writes + high risk go through full verification

---

## FAQ

### What is the API Key for? I already have a Claude API key.

`HIVEMIND_API_KEYS` is not a third-party service key — it's **HiveMind's own door lock**.

Your Claude API key identifies you to Anthropic. HiveMind's key identifies the MCP client to HiveMind. Two different keys for two different doors.

You can leave it empty to skip authentication entirely. Setting it just adds an extra layer so unknown MCP clients can't connect and operate on your files.

### Why was my command blocked?

Two possible layers:

- **Hard gate** — Unconditional rejection. For example, `rm -rf /`, reading `/etc/passwd`, path traversal with `../` are always blocked.
- **Soft scoring** — Risk-weighted. Writes and deletes score lower than reads. Below threshold, human approval is required.

If a safe operation is being falsely blocked, run `get_constitution` to see the active rules, then customize your `constitution.json`.

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
