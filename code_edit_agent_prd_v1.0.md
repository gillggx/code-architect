# Code Architect — Code Edit Agent PRD v1.0

**Date:** 2026-03-18
**Status:** Draft
**Builds on:** Code Architect Agent v2 (analysis + chat complete)
**Reference product:** Claude Code (Anthropic CLI)

---

## 1. What problem this solves

Code Architect v2 can read and explain a codebase. But understanding is only half the job.
The next step is acting on that understanding — making changes that **fit the existing architecture**.

Current tools in the market:

| Tool | Knows your architecture? | Runs in browser? | Approval UX? |
|------|--------------------------|-------------------|--------------|
| Claude Code (CLI) | Partially (reads files on demand) | No — terminal only | Yes (per tool call) |
| Cursor / Copilot | Partially (open files only) | No — IDE only | Implicit |
| **Code Architect Edit Agent** | **Yes (full memory from analysis)** | **Yes** | **Yes (diff review)** |

The key differentiator: by the time the user asks the agent to write something, it has already read the entire codebase and built a structured memory. The LLM knows the patterns, module layout, and conventions before the first keystroke.

---

## 2. Product Overview

**Code Architect Edit Agent** extends the existing chat panel into a full agentic loop:

1. User types a task in natural language
2. Agent calls **tools** to read files, write code, run tests, and check git status
3. Every **write/execute** action is shown to the user as a diff or command before it runs
4. User can **Approve**, **Edit**, or **Reject** each action
5. Agent loops until the task is done or the user stops it

This is the web-browser equivalent of Claude Code — with the added advantage of pre-loaded architectural memory.

---

## 3. Core Capabilities

### 3.1 Agent Tools (mirrors Claude Code's tool set)

| Tool | Description | Auto-approved? |
|------|-------------|----------------|
| `read_file(path)` | Read a file from the project | Yes |
| `list_files(glob)` | List files matching a pattern | Yes |
| `search_code(pattern, path?)` | Grep across the project | Yes |
| `write_file(path, content)` | Create or overwrite a file | **No — requires diff approval** |
| `edit_file(path, old, new)` | Replace a string in a file | **No — requires diff approval** |
| `run_command(cmd)` | Run a shell command (tests, linters) | **No — requires command approval** |
| `search_memory(query)` | Query the RAG memory built during analysis | Yes |
| `git_status()` | Show changed files | Yes |
| `git_diff(path?)` | Show uncommitted changes | Yes |

Read-only tools run immediately. Any tool that **modifies state** (write, edit, command) is paused and shown to the user first.

### 3.2 Task types

- **New feature** — "Add a rate-limiting middleware that follows the existing pattern"
- **Refactor** — "The auth module is too large, split it into auth/jwt.py and auth/session.py"
- **Bug fix** — "The /api/chat endpoint returns 422 when session_id is missing, fix it"
- **Test generation** — "Write pytest tests for all functions in rag/hybrid_search.py"
- **Documentation** — "Write a docstring for every public function in models.py"
- **Dependency graph** — "Show me which modules import from memory/tier1.py"

### 3.3 Plan Mode (mandatory for complex tasks)

Before executing any writes, the agent shows a **Plan** — a numbered list of actions it intends to take. The user can approve the plan or ask for changes. Only after plan approval does the agent start executing tool calls.

Example plan for "Add rate-limiting middleware":
```
Plan (5 steps):
1. Read api/main.py to understand current middleware stack
2. Read api/auth.py to understand existing rate-limit logic
3. Create api/middleware/rate_limit.py (new file)
4. Edit api/main.py — register new middleware
5. Run: python3 -m pytest tests/unit/test_api.py -v
```

### 3.4 Diff approval UX

Every write/edit is shown as a GitHub-style diff before it's applied:

```diff
api/main.py

@@ -17,6 +17,7 @@ from fastapi import FastAPI, HTTPException, Request

 from ..models import Pattern
+from .middleware.rate_limit import RateLimitMiddleware

@@ -45,6 +46,7 @@ def create_app() -> FastAPI:
     app.add_middleware(CORSMiddleware, ...)
+    app.add_middleware(RateLimitMiddleware, requests_per_minute=60)
     return app

[Apply]  [Edit]  [Skip]
```

Buttons:
- **Apply** — write the change to disk, continue
- **Edit** — open the diff in an inline editor before applying
- **Skip** — skip this step, continue with next
- **Stop** — abort the entire task

### 3.5 Command approval UX

Shell commands show the exact command before running:

```
Run command:
  python3 -m pytest tests/unit/test_api.py -v

[Run]  [Skip]  [Stop]
```

Output streams live in the chat panel.

---

## 4. UX Design

### 4.1 Layout changes

The existing 3-panel layout is preserved. The chat panel is extended:

```
┌─────────────────────────────────────────────────────────────────┐
│ 🏗 Code Architect  workspace/MyProject        [Analyze]  [Edit] │
├────────────────┬───────────────────────────┬────────────────────┤
│ 📁 FILES       │ 🤖 AGENT ACTIVITY         │ 🧠 MEMORY          │
│                │                           │                    │
│ ✅ api/main.py │ Tool: read_file           │ Modules: 12        │
│ 🔄 api/mid...  │   api/main.py             │                    │
│                │                           │ Pattern: Middleware│
│                │ Diff: api/main.py         │                    │
│                │ + from .middleware...     │                    │
│                │ [Apply] [Edit] [Skip]     │                    │
│                │                           │                    │
├────────────────┴───────────────────────────┴────────────────────┤
│  MODE: [Chat ▼]  Ask anything / give a task…         [Send] ▶   │
└─────────────────────────────────────────────────────────────────┘
```

The chat input has a **mode selector**: `Chat` (read-only Q&A) vs `Edit` (agentic loop with tools).

In **Edit mode**, the chat input placeholder changes to:
> "Describe a task: 'Add X', 'Refactor Y', 'Fix the bug where Z'…"

### 4.2 Chat panel states

| State | What's visible |
|-------|---------------|
| Idle / Chat mode | Normal conversation bubbles |
| Edit mode — planning | Agent's plan as a numbered list with [Approve Plan] button |
| Edit mode — executing | Tool call cards (read = compact, write = diff card, command = command card) |
| Edit mode — complete | Summary: "Done. 3 files changed, 1 test added. All tests passing." |
| Edit mode — error | Error message + [Retry] [Stop] |

### 4.3 Modified files indicator

The FileTree panel shows a **●** (dot) on any file the agent has modified in the current session, matching VS Code's indicator. Clicking a modified file shows the full diff.

---

## 5. Technical Architecture

### 5.1 New backend components

```
api/
  agent_runner.py      Agentic loop: parse LLM response → dispatch tool calls
  tools/
    file_tools.py      read_file, list_files, write_file, edit_file
    search_tools.py    search_code (ripgrep wrapper)
    shell_tools.py     run_command (subprocess with timeout + sandboxing)
    memory_tools.py    search_memory (wraps RAGMemoryIntegration)
    git_tools.py       git_status, git_diff
  diff.py              Unified diff generator (Python difflib)
  sandbox.py           Command allowlist + working dir restriction
```

### 5.2 Agentic loop design

The agent loop runs as an SSE stream (same as chat today):

```
POST /api/agent/run
  { task, project_id, session_id, mode: "plan" | "execute" }

SSE events:
  { type: "thinking",  content: "..." }          # agent reasoning (can be hidden)
  { type: "tool_call", tool: "read_file",  args: {...}, result: "..." }
  { type: "tool_call", tool: "write_file", args: {...}, diff: "...",
    approval_required: true }                     # pauses here
  { type: "tool_call", tool: "run_command", args: {...},
    approval_required: true }
  { type: "tool_output", content: "..." }         # stdout/stderr of command
  { type: "plan",      steps: [...] }             # plan proposal
  { type: "message",   content: "..." }           # agent text to user
  { type: "done",      summary: "..." }
  { type: "error",     message: "..." }
```

When `approval_required: true`, the stream **pauses**. The frontend shows the approval UI. The user's response is sent via:

```
POST /api/agent/approve
  { session_id, action: "apply" | "edit" | "skip" | "stop",
    edited_content?: "..." }
```

This resumes the SSE stream.

### 5.3 LLM prompt design

The system prompt for Edit mode includes:

1. **Identity**: "You are an expert software engineer working on {project_name}."
2. **Architecture context**: Top-8 RAG chunks from project memory (same as chat)
3. **Tool definitions**: JSON schema for each available tool (OpenAI function-calling format)
4. **Constraints**:
   - Always make a plan before writing any files
   - One tool call per response turn
   - Explain what you're about to do before doing it
   - Match the existing code style

The model is called in a **tool-use loop** (not streaming text), using OpenRouter's function-calling API. Each iteration:
1. Send messages + tool results so far
2. Model returns: text content + optional tool call
3. If tool call requires approval → pause
4. If tool call is auto-approved → execute, append result, loop
5. If no tool call → final response, stream to user

### 5.4 Sandbox and safety

**Command restrictions** (shell_tools.py allowlist):
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

Any command not matching the allowlist is blocked — the agent is told "command not permitted, try a different approach."

**Write restrictions:**
- All writes are constrained to the project directory (`project_path` from the analysis job)
- Writes to `.env`, `*.key`, `*.pem`, `secrets.*` are blocked
- Max file size: 500 KB per write

**Timeout:** Each tool call has a 30s timeout. The agentic loop has a max of 20 tool calls per task.

---

## 6. New API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/agent/run` | Start agentic task → SSE stream |
| `POST` | `/api/agent/approve` | Approve/edit/skip/stop a pending tool call |
| `GET`  | `/api/agent/sessions/{id}` | Session state (pending approval, history) |
| `POST` | `/api/agent/sessions/{id}/stop` | Stop running session |
| `GET`  | `/api/diff?path=X&session_id=Y` | Full diff for a modified file |

---

## 7. Comparison to Claude Code

| Feature | Claude Code | Code Architect Edit Agent |
|---------|-------------|--------------------------|
| Runs in | Terminal (CLI) | Browser (React UI) |
| Architecture context | Reads files on demand | Pre-loaded from full analysis |
| Approval UX | Per tool call (y/n in terminal) | Visual diff cards with Edit option |
| Plan mode | `/plan` command | Automatic before first write |
| File browser | No | Yes — FileTree panel |
| Chat history | In terminal | In floating overlay |
| Memory / RAG | No | Yes — previous analysis |
| Incremental re-analysis | No | Yes — after each write |
| Command execution | Any bash | Allowlisted only |
| Multi-file view | No | Yes — all modified files tracked |
| A2A API | No | Yes — `/api/agent/run` programmatically |

The core difference in philosophy: Claude Code is a **general-purpose agent** that explores a codebase from scratch each session. Code Architect Edit Agent is a **domain-specific agent** that starts every session with a complete architectural model already loaded.

---

## 8. Implementation Plan

### Phase A — Foundation (backend tools + loop)
1. `file_tools.py` — read_file, list_files, write_file, edit_file
2. `search_tools.py` — search_code (ripgrep)
3. `diff.py` — unified diff generator
4. `agent_runner.py` — agentic loop (SSE + tool dispatch)
5. `POST /api/agent/run` + `POST /api/agent/approve`
6. Sandbox + allowlist for shell commands

### Phase B — Frontend UI
1. Mode selector in ChatBar (Chat / Edit)
2. Tool call cards (read = compact, write = diff card, command = card)
3. Approve / Edit / Skip / Stop buttons on write/command cards
4. Modified files indicator (● dot) in FileTree
5. Full diff view on click

### Phase C — Plan mode + polish
1. Plan proposal rendering (numbered list + [Approve Plan])
2. Session history persistence (so user can review what changed)
3. Auto incremental re-analysis after writes complete
4. `git_tools.py` — git status/diff in tool results

---

## 9. Out of Scope (v1)

- **Auto-commit** — agent does not commit to git; user does that manually
- **Multi-file diff view** — only single-file diff per approval card
- **Collaborative editing** — one user per session
- **Remote project support** — project must be on the local filesystem
- **Streaming writes** — writes are atomic (full file replacement), not line-by-line
