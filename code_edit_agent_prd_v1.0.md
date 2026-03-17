# Code Architect — Code Edit Agent PRD v1.0

**Date:** 2026-03-18
**Status:** Draft
**Builds on:** Code Architect Agent v2 (analysis + chat complete)
**Primary users:** Other agents (A2A) — humans are secondary consumers

---

## 1. What problem this solves

Code Architect v2 can read and explain a codebase. The next step is acting on that understanding — generating and applying changes that **fit the existing architecture**.

The core advantage over existing tools:

| Tool | Architecture context | A2A API | Auto-apply |
|------|----------------------|---------|------------|
| Claude Code (CLI) | Reads on demand (cold start each session) | No | Yes (terminal) |
| Cursor / Copilot | Open files only | No | Yes (IDE) |
| **Code Architect Edit Agent** | **Full memory pre-loaded from analysis** | **Yes** | **Yes** |

The key differentiator: by the time any caller (agent or human) asks for code generation, the system already has a complete architectural model of the project. The LLM knows patterns, module layout, conventions, and dependencies before writing a single line.

---

## 2. Execution Modes

Every endpoint supports three modes. **The caller picks the mode — no difference between agent and human.**

| Mode | Behaviour |
|------|-----------|
| `dry_run` | Return diffs + plan. Nothing written to disk. Caller decides what to do with the result. |
| `apply` | Execute all changes immediately. Return list of files changed. |
| `interactive` | Stream tool-call events via SSE. Pause on writes/commands for explicit approval. Resume via `/api/agent/approve`. |

Human using the web UI defaults to `interactive`.
Agent calling the API defaults to `apply` or `dry_run` depending on how much it trusts the output.
CI/CD pipelines use `dry_run` to get diffs, then apply via git.

There is **no approval gate that only humans can bypass** — the mode controls everything. An agent can run `interactive` if it wants to review each step; a human can run `apply` if they trust the agent.

---

## 3. Core A2A API

### 3.1 Generate code

```
POST /api/a2a/generate
```

```json
Request:
{
  "task": "Add rate-limiting middleware that follows the existing pattern",
  "project_id": "myapp-abc123",
  "mode": "dry_run" | "apply" | "interactive",
  "context": "optional extra instructions or constraints"
}

Response (dry_run / apply):
{
  "changes": [
    {
      "file": "api/middleware/rate_limit.py",
      "action": "create",
      "content": "...",
      "diff": null
    },
    {
      "file": "api/main.py",
      "action": "edit",
      "content": null,
      "diff": "--- a/api/main.py\n+++ b/api/main.py\n..."
    }
  ],
  "plan": ["Step 1: ...", "Step 2: ..."],
  "explanation": "Added RateLimitMiddleware following the existing middleware stack pattern.",
  "patterns_used": ["Middleware", "Factory"],
  "tests_suggested": ["tests/test_rate_limit.py"],
  "applied": true | false,
  "model_used": "anthropic/claude-sonnet-4-5"
}
```

For `interactive` mode, returns an SSE stream (see Section 3.5).

---

### 3.2 Validate code

```
POST /api/a2a/validate
```

Checks whether proposed code changes are consistent with the project's architecture and patterns.

```json
Request:
{
  "project_id": "myapp-abc123",
  "changes": [
    { "file": "api/routes/export.py", "content": "..." }
  ]
}

Response:
{
  "valid": true,
  "confidence": 0.91,
  "issues": [],
  "warnings": [
    "export.py imports 'requests' directly — project uses httpx elsewhere"
  ],
  "patterns_matched": ["Repository", "Middleware"],
  "patterns_missing": []
}
```

Use case: a CodeGen agent generates code → sends it here for a style/architecture check before applying.

---

### 3.3 Impact analysis

```
POST /api/a2a/impact
```

Before modifying a module, ask what else will be affected.

```json
Request:
{
  "project_id": "myapp-abc123",
  "files": ["memory/tier1.py"],
  "change_description": "Rename MemoryTier1.add_pattern() to add()"
}

Response:
{
  "affected_files": [
    { "file": "api/main.py", "reason": "calls add_pattern() directly" },
    { "file": "memory/rag_integration.py", "reason": "imports and uses add_pattern()" }
  ],
  "risk": "medium",
  "confidence": 0.87,
  "recommendation": "Update 2 call sites after renaming."
}
```

---

### 3.4 Architecture query (existing, unchanged)

```
POST /api/a2a/query
```

Already implemented. Returns architecture answers grounded in project memory.

---

### 3.5 Interactive SSE stream (mode: interactive)

When `mode: "interactive"`, `/api/a2a/generate` returns an SSE stream.
The calling agent (or human browser) receives events and can approve/skip each write.

```
SSE events:
{ "type": "plan",      "steps": ["...", "..."] }
{ "type": "tool_call", "tool": "read_file",  "args": {...}, "result": "..." }
{ "type": "tool_call", "tool": "write_file", "args": {...}, "diff": "...",
  "approval_required": true }                 ← stream pauses here
{ "type": "tool_call", "tool": "run_command","args": {...},
  "approval_required": true }
{ "type": "tool_output", "content": "..." }
{ "type": "message",   "content": "..." }
{ "type": "done",      "summary": "...", "changes": [...] }
{ "type": "error",     "message": "..." }
```

Resume after an approval pause:

```
POST /api/agent/approve
{
  "session_id": "...",
  "action": "apply" | "edit" | "skip" | "stop",
  "edited_content": "..."   // optional, only when action=edit
}
```

Human web UI uses this via the diff card UI (Apply / Edit / Skip buttons).
Agent uses this programmatically — it can inspect the diff and decide automatically.

---

## 4. Agent Tools (internal, used by the agentic loop)

| Tool | Description | Requires approval in interactive mode? |
|------|-------------|----------------------------------------|
| `read_file(path)` | Read a file | No |
| `list_files(glob)` | List matching files | No |
| `search_code(pattern)` | Grep across project | No |
| `search_memory(query)` | Query RAG memory | No |
| `git_status()` | Show changed files | No |
| `git_diff(path?)` | Show uncommitted diff | No |
| `write_file(path, content)` | Create/overwrite file | **Yes** (in interactive) |
| `edit_file(path, old, new)` | String replace in file | **Yes** (in interactive) |
| `run_command(cmd)` | Run shell command | **Yes** (in interactive) |

In `apply` or `dry_run` mode, approval events are skipped — writes either happen immediately (apply) or are collected but not executed (dry_run).

---

## 5. Typical A2A Workflows

### Workflow A — Orchestrator generates and applies

```
OrchestratorAgent
  → POST /api/a2a/query       "understand architecture"
  → POST /api/a2a/generate    mode: dry_run  → get diffs
  → POST /api/a2a/validate    verify diffs
  → POST /api/a2a/generate    mode: apply    → write to disk
  → POST /api/a2a/query       "confirm the change landed correctly"
```

### Workflow B — Cautious agent reviews each step

```
CautiousAgent
  → POST /api/a2a/generate    mode: interactive
  → receives SSE stream
  → on approval_required: inspect diff, POST /api/agent/approve { action: "apply" }
  → continues until done
```

### Workflow C — Human using the web UI

```
Human clicks "Edit" tab in browser
  → types task in chat input
  → frontend POSTs /api/a2a/generate  mode: interactive
  → diff cards appear in AgentActivity panel
  → human clicks Apply / Edit / Skip on each card
```

### Workflow D — CI/CD pipeline

```
CI pipeline (on PR)
  → POST /api/a2a/validate   check new files
  → POST /api/a2a/impact     check what the PR affects
  → report results as PR comment
```

---

## 6. Security and Sandboxing

**Write restrictions** — all writes constrained to `project_path`:
- Blocked: `.env`, `*.key`, `*.pem`, `secrets.*`
- Max file size: 500 KB

**Command allowlist** (shell_tools.py):
```python
ALLOWED_COMMANDS = [
    r"^python3? -m pytest",
    r"^npm (test|run (test|lint|build))",
    r"^cargo test",
    r"^go test",
    r"^ruff (check|format)",
    r"^mypy ",
    r"^git (status|diff|log)",
]
```

**Limits** — max 20 tool calls per task, 30s timeout per tool call.

---

## 7. Web UI Changes (human convenience layer)

The web UI is a thin wrapper over the same API agents use. No special human-only features.

- ChatBar gets an **Edit mode** toggle (Chat / Edit)
- In Edit mode, task is sent as `POST /api/a2a/generate mode: interactive`
- Tool call events render as cards in AgentActivity panel
- Write cards show diffs with Apply / Edit / Skip / Stop buttons
- Command cards show the exact command with Run / Skip / Stop buttons
- Modified files show a ● dot in FileTree
- A **Bypass** toggle switches from `interactive` to `apply` — same as agent auto-approve

---

## 8. New Endpoints Summary

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/a2a/generate` | Generate + optionally apply code changes |
| `POST` | `/api/a2a/validate` | Validate code against project patterns |
| `POST` | `/api/a2a/impact` | Impact analysis before modifying a module |
| `POST` | `/api/agent/approve` | Resume interactive session after approval pause |
| `GET`  | `/api/agent/sessions/{id}` | Session state |
| `POST` | `/api/agent/sessions/{id}/stop` | Stop a running session |

---

## 9. Implementation Phases

### Phase A — Backend foundation
1. `api/tools/` — file_tools, search_tools, shell_tools, memory_tools, git_tools
2. `api/agent_runner.py` — agentic loop (tool dispatch + SSE)
3. `api/diff.py` — unified diff generator
4. `POST /api/a2a/generate` (dry_run + apply modes)
5. `POST /api/agent/approve` (interactive mode)
6. Sandbox + command allowlist

### Phase B — Validate + Impact
1. `POST /api/a2a/validate` — pattern matching against memory
2. `POST /api/a2a/impact` — dependency graph traversal

### Phase C — Web UI
1. Edit mode toggle in ChatBar
2. Tool call cards in AgentActivity (diff view, command view)
3. Bypass toggle (interactive → apply)
4. Modified files indicator in FileTree

---

## 10. Out of Scope (v1)

- Auto-commit to git (caller decides when to commit)
- Multi-project tasks (one project_id per generate call)
- Streaming partial diffs (changes are complete before returned in dry_run)
- Remote filesystem (project must be on the server's local disk)
