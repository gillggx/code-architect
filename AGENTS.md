# Code Architect Agent — Agent Integration Guide

Machine-readable reference for AI agents integrating with this service via A2A or REST API.

---

## Service Identity

| Field | Value |
|-------|-------|
| Name | Code Architect Agent |
| Purpose | LLM-powered codebase analysis, RAG-based Q&A, and agentic code editing |
| Backend | FastAPI · Python 3.13+ |
| Base URL (default) | `http://localhost:8001` |
| Frontend | `http://localhost:3001` |
| API Docs | `http://localhost:8001/docs` |
| MCP Schema | `GET /api/a2a/schema` |

---

## A2A Endpoints (Primary Integration Points)

### `POST /api/a2a/query`
Query the codebase memory. Use this to answer architecture questions grounded in real code analysis.

**Request**
```json
{
  "question": "How does authentication work?",
  "project_id": "my-project-a1b2c3d4",
  "query_type": "architecture",
  "context": {}
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `question` | string | ✅ | Natural language question |
| `project_id` | string | ❌ | Project to query (searches all if omitted) |
| `query_type` | string | ❌ | `architecture` \| `feasibility` \| `pattern` \| `general` |
| `context` | object | ❌ | Extra context from calling agent |

**Response**
```json
{
  "answer": "Authentication uses JWT tokens validated in src/auth/middleware.py...",
  "confidence": 0.87,
  "sources": [{"file": "src/auth/middleware.py", "relevance": 0.9}],
  "patterns_relevant": ["Middleware Pattern", "JWT"],
  "feasibility_score": null,
  "model_used": "anthropic/claude-haiku-4-5",
  "query_type": "architecture"
}
```

---

### `POST /api/a2a/generate`
Execute agentic code edits. Agent plans, writes, and applies file changes.

**Request**
```json
{
  "task": "Add input validation to the login endpoint",
  "project_id": "my-project-a1b2c3d4",
  "mode": "interactive",
  "context": "optional extra context",
  "chat_history": [
    {"role": "user", "content": "The login crashes on empty passwords"},
    {"role": "assistant", "content": "I see the issue in auth/login.py"}
  ],
  "shell_unrestricted": false,
  "auto_approve": false
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task` | string | — | What to build or change |
| `project_id` | string | — | Project context ID |
| `mode` | string | `dry_run` | `dry_run` \| `apply` \| `interactive` |
| `chat_history` | array | `[]` | Recent `[{role, content}]` for context |
| `shell_unrestricted` | bool | `false` | Bypass shell allowlist |
| `auto_approve` | bool | `false` | Skip file-change approval prompts |

**Response** — SSE stream of events:
```
data: {"type": "session", "session_id": "uuid"}
data: {"type": "message", "content": "Generating execution plan..."}
data: {"type": "plan", "content": "{...plan JSON...}"}
data: {"type": "tool_call", "tool": "write_file", "args": {"path": "...", "content": "..."}}
data: {"type": "tool_output", "result": "Written 1234 bytes to src/auth/login.py"}
data: {"type": "approval_required", "tool": "edit_file", "args": {...}, "diff": "--- a/...\n+++ b/..."}
data: {"type": "done", "content": "Task complete.", "changes": [...]}
```

**Event types:**

| Type | Meaning |
|------|---------|
| `session` | Session ID for approval callbacks |
| `message` | Agent status message |
| `plan` | JSON execution plan (Plan A / Plan B) |
| `tool_call` | Agent is about to invoke a tool |
| `tool_output` | Tool execution result |
| `approval_required` | Waiting for human approval (interactive mode) |
| `escalation` | Tool failed; escalating to human |
| `done` | Task complete; `changes[]` contains all file modifications |
| `error` | Fatal error |

---

### `POST /api/a2a/validate`
Validate proposed file changes against project patterns.

**Request**
```json
{
  "project_id": "my-project-a1b2c3d4",
  "changes": [
    {"file": "src/auth/login.py", "action": "edit", "content": "...", "diff": "...", "applied": false}
  ]
}
```

**Response**
```json
{
  "valid": true,
  "confidence": 0.91,
  "issues": [],
  "warnings": ["Missing type annotations on new function"],
  "patterns_matched": ["Repository Pattern"],
  "patterns_missing": []
}
```

---

### `POST /api/a2a/impact`
Analyze the blast radius of a proposed change.

**Request**
```json
{
  "project_id": "my-project-a1b2c3d4",
  "files": ["src/auth/middleware.py"],
  "change_description": "Switching from JWT to session cookies"
}
```

**Response**
```json
{
  "affected_files": [
    {"file": "src/auth/login.py", "reason": "imports middleware", "risk": "high"}
  ],
  "risk": "high",
  "confidence": 0.83,
  "recommendation": "Update all importers and add regression tests before deploying."
}
```

---

## Approval Callbacks (Interactive Mode)

When `mode: "interactive"` and agent needs file-change approval:

### `POST /api/agent/approve`
```json
{"session_id": "uuid", "action": "apply"}
```
`action`: `apply` | `skip` | `stop` | `edit`

### `POST /api/agent/approve-plan`
```json
{"session_id": "uuid", "action": "approve", "chosen_plan": "A"}
```
`action`: `approve` | `reject` | `stop`
`chosen_plan`: `"A"` | `"B"`

### `POST /api/agent/escalate`
```json
{"session_id": "uuid", "action": "alternative", "instruction": "Try a different approach"}
```
`action`: `alternative` | `manual_fix` | `stop`

---

## Other Useful Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check + uptime |
| `POST` | `/api/analyze` | Start LLM analysis (returns `job_id`, stream via WebSocket) |
| `GET` | `/ws/analyze/{job_id}` | WebSocket stream of analysis events |
| `POST` | `/api/chat` | RAG-powered chat (SSE stream) |
| `GET` | `/api/projects` | List all analyzed projects |
| `DELETE` | `/api/projects/{project_id}` | Remove project memory |
| `GET` | `/api/memory/{project_id}` | Load persisted modules + patterns |
| `GET` | `/api/scan?path=...` | File count without analysis |
| `GET` | `/api/a2a/schema` | MCP-compatible schema |

---

## Agent Tools (available inside edit sessions)

| Tool | Description | Key Args |
|------|-------------|----------|
| `read_file` | Read a file (sandboxed to project root) | `path` |
| `write_file` | Create or overwrite a file | `path`, `content` |
| `edit_file` | Exact string replacement | `path`, `old_str`, `new_str` |
| `list_files` | Glob file listing | `glob_pattern` |
| `search_code` | Regex search across project | `pattern`, `file_glob` |
| `git_status` | `git status --short` | — |
| `git_diff` | `git diff` | `path` (optional) |
| `run_command` | Shell command (allowlisted by default) | `cmd`, `timeout` |

**Shell allowlist** (when `shell_unrestricted: false`):
pytest, npm test/install/ci, pip install, pnpm/yarn/bun install, cargo test/build, go test/mod/get/build, ruff, mypy, eslint, tsc, pyright, git init/status/diff/log, find, ls, cat, head, tail, wc, grep, mkdir, uv, poetry, python -m venv

---

## Data Schemas

### AgentEvent (WebSocket / SSE)
```json
{
  "id": "uuid",
  "type": "scan | ast | llm_start | llm_done | memory | pattern | skip | done | error | tool_call | tool_output | approval_required | message | plan | escalation | session",
  "message": "human-readable description",
  "file": "relative/path.py",
  "summary": "one-line module summary",
  "data": {}
}
```

### MemoryModule
```json
{
  "name": "AuthMiddleware",
  "path": "src/auth/middleware.py",
  "purpose": "Validates JWT tokens on every request",
  "patterns": ["Middleware Pattern", "Chain of Responsibility"],
  "key_components": ["verify_token()", "AuthMiddleware class"]
}
```

### FileChange
```json
{
  "file": "src/auth/login.py",
  "action": "edit",
  "content": "..full file content..",
  "diff": "--- a/src/auth/login.py\n+++ b/src/auth/login.py\n...",
  "applied": true
}
```

### ExecutionPlan
```json
{
  "variant": "A",
  "steps": [
    {"index": 1, "description": "Add validator function", "files_affected": ["src/auth/validators.py"]}
  ],
  "confidence": 0.85,
  "rationale": "Minimal change, low risk",
  "risk_level": "low"
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | Required for cloud LLMs |
| `DEFAULT_LLM_MODEL` | `anthropic/claude-haiku-4-5` | Model for all LLM operations |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter endpoint |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama fallback |
| `AGENT_SHELL_UNRESTRICTED` | `false` | Global shell allowlist bypass |

---

## Project Memory Storage

Analyzed projects are stored in `./architect_memory/{project_id}/`:
- `modules.json` — array of `MemoryModule` objects
- `SNAPSHOTS.json` — file hashes for incremental re-analysis
- `project_path.txt` — absolute path to original project

`project_id` is derived as `{folder_name}-{md5(abs_path)[:12]}` — stable across runs.

---

## SOUL.md (Per-Project Agent Personality)

Place `SOUL.md` at the root of any analyzed project to inject constraints into the edit agent system prompt:

```markdown
# Agent Soul
## Personality
You are a careful, security-focused architect.
## Constraints
- Never delete files without explicit confirmation
- Always prefer backward-compatible changes
```
