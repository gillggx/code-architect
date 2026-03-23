# Code Architect Agent

An AI-powered codebase analysis and agentic coding tool. Point it at any project directory — it reads your code with an LLM, builds a structured memory of the architecture, lets you chat about it in real time, and can execute code changes with planning and escalation safeguards.

**Stack:** Python 3.13+ / FastAPI / React 18 / TypeScript / OpenRouter

---

## Features

### Analysis
- **File scanning** — AST-level structure extraction (no LLM cost)
- **LLM-powered reading** — builds structured memory of modules, patterns, dependencies
- **Incremental re-analysis** — only changed/new files are re-processed (MD5 + mtime snapshots)
- **Chunked analysis** — large files are read in chunks with rolling memory accumulation; no timeout from oversized files
- **Incremental persistence** — modules.json and SNAPSHOTS.json saved after every file so interrupted analyses are never lost
- **Memory consistency check** — auto-detects snapshot/module mismatch and triggers full re-analysis
- **Real-time activity feed** — every file read and summary written shown live

### Chat
- **RAG-powered Q&A** — answers grounded in architecture memory via hybrid BM25 + vector search
- **3-tier memory** — hot cache → Markdown summaries → vector embeddings
- **Persistent memory display** — past analysis results loaded into Memory panel on project select
- **Git context injection** — recent commits and uncommitted changes injected into chat so agent knows what was recently worked on
- **Analysis-in-progress awareness** — chat agent warns when memory is incomplete during active analysis

### Agentic Mode (Edit)
- **SOUL.md** — per-project personality and constraints injected into agent system prompt
- **Plan A / Plan B** — LLM generates execution plans with confidence scores; `response_format: json_object` ensures reliable JSON output across weak models
- **Automatic task chunking** — large plans (>12 steps) split into phases automatically; each phase carries summary context from the previous
- **Chat history injection** — recent chat conversation sent with edit tasks so agent understands context
- **Escalation Loop** — tool failure → auto-switch to Plan B → human escalation with custom instruction
- **Built-in tools** — read/write/edit files, git status/diff, shell commands, code search
- **Shell allowlist** — test runners, linters, git, find, ls, cat, grep; bypass with `AGENT_SHELL_UNRESTRICTED=true`
- **50-iteration hard cap** — per phase, with stall detection: identical (tool, args) calls 3× in a row inject a forced-progress warning
- **no-op guard** — `edit_file` rejects calls where `old_str == new_str` before touching disk
- **Impact Preview** — before executing any edit task, calls `/api/a2a/impact` and shows predicted file changes with confidence bars; user confirms or cancels
- **Git Checkpoint** — on first mutating tool call, creates `architect/task-{id}` branch; pre-task dirty tree saved as named stash; one-click Rollback in the UI restores original state
- **Semantic Context Window** — recent files in the conversation are hydrated with their symbols and `imported_by` graph into a dynamic `## Active Context` block; conversation summaries injected when messages exceed 20
- **Architecture Linter** — enforces `.architect-rules.yml` rules (forbidden/required imports per file glob) after every write; violations block continuation with auto-suggested memory alternatives
- **Sticky Context** — after each successful edit, the module's `edit_hints` field is updated with a timestamped summary so future agent calls see what changed
- **Task Briefing** — at the start of every task the agent emits a structured plan card listing all steps, confidence, and risk level; Activity Feed shows an animated "currently on step N" bar

### Memory Panel
- **Symbol navigation** — each module shows its functions/classes/variables; click any symbol to jump to that line in the file viewer
- **Used by N badge** — modules show how many other modules import them; N≥5 highlighted as a hot spot
- **File context mode** — when a file is open in the editor, Memory Panel automatically focuses on that file's memory record with full symbols, edit hints, and patterns; toggle back to full list

### A2A API
- **Architecture query** — `POST /api/a2a/query` — other agents can ask architecture questions
- **Code generation** — `POST /api/a2a/generate` — SSE stream of agent events
- **Validation** — `POST /api/a2a/validate`
- **Impact analysis** — `POST /api/a2a/impact` — predicts which files a change will affect
- **Scaffold** — `POST /api/a2a/scaffold` — create a new project from template with optional auto-analysis
- **Codegen** — `POST /api/a2a/codegen` — generate Pydantic/FastAPI/agent components and write to disk
- **Rollback** — `POST /api/agent/rollback-session-v2` — restores workspace to pre-task state
- **Empty-memory guard** — `POST /api/a2a/generate` returns `HTTP 428` with remediation steps if project has no architecture memory; set `force_generate: true` to bypass

---

## Ports

| Service | Port |
|---------|------|
| Backend (FastAPI) | **8765** |
| Frontend (Vite/React) | **3011** |

Designed to run alongside [agent-platform](https://github.com/gillggx/agent-platform) (ports 8080/2999) on the same machine without conflicts.

---

## Quick Start

### Prerequisites

- Python 3.13+
- Node.js 18+
- An [OpenRouter](https://openrouter.ai) API key (or Ollama running locally)

### 1. Configure

```bash
git clone https://github.com/gillggx/code-architect.git
cd code-architect
cp .env.example .env   # then set OPENROUTER_API_KEY
```

`.env` minimal config:

```env
OPENROUTER_API_KEY=sk-or-...
DEFAULT_LLM_MODEL=anthropic/claude-haiku-4-5

# Optional: bypass shell command allowlist (dev only)
# AGENT_SHELL_UNRESTRICTED=true
```

### 2. Start

```bash
./start.sh
```

Opens:
- Frontend: http://localhost:3001
- API docs: http://localhost:8001/docs

---

## Project Structure

```
code-architect/
├── src/architect/
│   ├── api/
│   │   ├── agent_runner.py   # Agentic loop — planning, tool execution, git checkpoint, linter
│   │   ├── arch_linter.py    # Architecture rules engine (.architect-rules.yml)
│   │   ├── diff.py           # Unified diff helpers
│   │   ├── main.py           # FastAPI routes
│   │   ├── schemas.py        # Pydantic request/response models
│   │   └── tools/            # file_tools, shell_tools (allowlist), search_tools, git_tools
│   ├── analysis/             # LLM file analyzer (chunked), large project handler
│   ├── codegen/              # Code generation helpers
│   ├── llm/                  # LLM client, model router, chat engine (git context)
│   ├── memory/               # 3-tier memory (hot cache, markdown, vectors)
│   ├── patterns/             # Design pattern detector
│   ├── projects/             # Project manager
│   └── rag/                  # Hybrid BM25 + vector search
├── web/src/
│   ├── components/
│   │   ├── AgentActivityFeed.tsx  # Activity/Chat/File/Graph tabs + briefing card + step bar
│   │   ├── ChatBar.tsx            # Chat/Edit mode input + Impact Preview modal
│   │   ├── MemoryPanel.tsx        # Module list + symbol navigation + used-by badge
│   │   ├── PlanCard.tsx           # Plan A/B approval card
│   │   ├── EscalationCard.tsx     # Tool failure escalation UI
│   │   ├── TopBar.tsx             # Project selector + rollback button + freshness indicator
│   │   └── FileEditor.tsx         # In-panel file viewer (click-to-line)
│   └── store/app.ts               # Zustand state (projects, memory, chat, agent session)
├── master_prd_sprint3_sprint4.md  # Sprint 3-4 feature spec
├── start.sh                       # One-command start
└── .env                           # API keys and model selection
```

---

## .architect-rules.yml

Place an `.architect-rules.yml` at the root of your analyzed project to enforce import rules. The agent checks every file it edits and blocks violations before they land.

```yaml
rules:
  - id: no-direct-db
    description: "Services must not import database models directly"
    match_files: "src/services/**/*.py"
    forbidden_imports:
      - "src/models/*"
      - "src/db/*"
    fix_hint: "Import via a repository layer instead"

  - id: require-logging
    description: "All API handlers must import the logger"
    match_files: "src/api/**/*.py"
    required_imports:
      - "logging"
```

When a violation is detected, the agent also searches project memory for a suitable alternative module (e.g. a `*service*` or `*facade*` file that wraps the forbidden resource) and suggests it alongside the violation message.

---

## SOUL.md

Place a `SOUL.md` at the root of any analyzed project to define agent personality and constraints:

```markdown
# Agent Soul

## Personality
You are a careful, security-focused architect.

## Constraints
- Never delete files without confirmation
- Always prefer backward-compatible changes
- Write tests for every new function
```

---

## A2A Integration

Base URL: `http://127.0.0.1:8765`

### Scenario A — Query an existing project

```bash
curl -X POST http://localhost:8765/api/a2a/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How does authentication work?", "project_id": "my-project", "query_type": "architecture"}'
```

Response:
```json
{
  "answer": "...",
  "confidence": 0.87,
  "sources": ["src/auth/middleware.py", "src/auth/jwt.py"],
  "patterns_relevant": ["middleware", "JWT"],
  "model_used": "anthropic/claude-haiku-4-5"
}
```

### Scenario B — Edit an existing project

The edit agent accepts `chat_history` for context and requires memory to exist first:

```json
{
  "task": "Add error handling to the login flow",
  "project_id": "my-project",
  "mode": "apply",
  "chat_history": [
    {"role": "user", "content": "The login flow crashes on invalid tokens"},
    {"role": "assistant", "content": "I can see the issue in auth/jwt.py..."}
  ]
}
```

If the project has no architecture memory, `POST /api/a2a/generate` returns **HTTP 428** with remediation steps:

```json
{
  "error": "project_memory_empty",
  "message": "Project has no architecture memory...",
  "remediation": {
    "step_1": { "description": "Trigger analysis", "method": "POST", "path": "/api/analyze" },
    "step_2": { "description": "Poll for completion", "method": "GET", "path": "/api/projects/{id}/freshness" },
    "step_3": { "description": "Retry generate", "method": "POST", "path": "/api/a2a/generate" }
  },
  "tip": "Set force_generate=true to bypass if task has explicit implementation details."
}
```

### Scenario C — Create a new project from scratch

```bash
# 1. Scaffold the project
curl -X POST http://localhost:8765/api/a2a/scaffold \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "/path/to/my-service",
    "template": "fastapi-full",
    "project_name": "my-service",
    "options": {"git_init": true, "auto_analyze": true}
  }'

# 2. Wait for analysis (poll freshness)
curl http://localhost:8765/api/projects/{project_id}/freshness

# 3. Generate code (now memory exists)
curl -X POST http://localhost:8765/api/a2a/generate \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Implement POST /items with validation and persistence",
    "project_id": "{project_id}",
    "mode": "apply"
  }'
```

Available templates: `fastapi-minimal`, `fastapi-full`, `python-lib`, `agent`

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | Required for cloud LLMs |
| `DEFAULT_LLM_MODEL` | `google/gemini-2.5-flash-lite` | Model for chat and edit agent |
| `ANALYSIS_LLM_MODEL` | `google/gemini-2.0-flash-lite-001` | Model for bulk file analysis (cheaper) |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter endpoint |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama fallback (used only if no API key) |
| `AGENT_SHELL_UNRESTRICTED` | `false` | Bypass shell command allowlist (dev only) |
