# Code Architect Agent

An AI-powered codebase analysis and agentic coding tool. Point it at any project directory — it reads your code, builds a structured **Architecture Map**, lets you chat about it with tool-use (the agent reads files on demand), and can execute code changes with planning and escalation safeguards.

**Stack:** Python 3.13+ / FastAPI / React 18 / TypeScript / OpenRouter / lucide-react

---

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                        Analysis Phase                        │
│  Scan files → LLM reads each → builds Architecture Map      │
│  Map: {name, purpose, public_interface, full_path, symbols} │
└────────────────────────┬────────────────────────────────────┘
                         │  (stored in architect_memory/)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                   Chat Phase (Tool-Use)                      │
│  User question → LLM inspects Map → picks relevant files    │
│  → read_file(path) → answer grounded in actual code         │
│                                                             │
│  Simple edit → edit_file() directly in chat                 │
│  Complex edit → escalate_to_edit_agent() → Edit Agent flow  │
└─────────────────────────────────────────────────────────────┘
```

The Architecture Map acts as a **directory** — the LLM checks it first to locate the right 1–3 files, then reads only those. Large projects stay fast and accurate without reading everything blindly.

---

## Features

### Analysis
- **File scanning** — AST-level structure extraction for Python/JS/TS (no LLM cost)
- **LLM-powered reading** — builds a compact navigation map per file: `purpose`, `public_interface`, `dependencies`, `critical_path`, `edit_hints`
- **Symbol extraction** — accurate function/class/method list with line numbers (via AST, not LLM)
- **Incremental re-analysis** — only changed/new files are re-processed (MD5 + mtime snapshots)
- **Chunked analysis** — large files read in chunks with rolling memory; no timeouts from oversized files
- **Incremental persistence** — `modules.json` and `SNAPSHOTS.json` saved after every file; interrupted analyses are never lost
- **Memory consistency check** — auto-detects snapshot/module mismatch and triggers full re-analysis
- **Real-time activity feed** — every file read and summary written shown live

### Chat (Tool-Use Mode)
- **Architecture Map context** — full module map injected into every chat so the LLM knows what exists
- **JIT code retrieval** — LLM calls `read_file(path)` to read actual source before answering; never hallucinates from missing code
- **Search across files** — `search_files(query)` greps the project on demand
- **Inline edits** — `edit_file(path, old_str, new_str)` for simple single-file changes directly in chat
- **Smart escalation** — complex/multi-file tasks automatically hand off to Edit Agent via `escalate_to_edit_agent()`; chat shows the transition inline and switches to Activity tab
- **Audit queries** — "find all hardcoded values", "scan all files" automatically reads up to 8 source files
- **Git context injection** — recent commits and uncommitted changes injected so agent knows what was recently touched
- **Analysis-in-progress awareness** — warns when memory is incomplete during active analysis
- **Conversation history** — last 10 turns kept per session for multi-turn dialogue

### Agentic Mode (Edit)
- **SOUL.md** — per-project personality and constraints injected into agent system prompt
- **Clarity Assessment** — before planning, LLM evaluates whether the task is specific enough; if unclear, shows a **ClarificationCard** with targeted questions; user answers → agent proceeds with full context
- **Plan A / Plan B** — LLM generates execution plans grounded in chat history; reliable JSON output via `response_format: json_object`
- **Automatic task chunking** — large plans (>12 steps) split into phases; each phase carries a summary from the previous
- **Chat history injection** — recent chat conversation forwarded with edit tasks for context continuity
- **Escalation Loop** — tool failure → auto-switch to Plan B → human escalation with custom instruction
- **Built-in tools** — read/write/edit files, git status/diff, shell commands, code search
- **Shell allowlist** — test runners, linters, git, find, ls, cat, grep; bypass with `AGENT_SHELL_UNRESTRICTED=true`
- **50-iteration hard cap** — per phase, with stall detection: same (tool, args) called 3× injects a forced-progress warning
- **no-op guard** — `edit_file` rejects calls where `old_str == new_str` before touching disk
- **Impact Preview** — before executing, calls `/api/a2a/impact` with chat history context and shows predicted file changes referencing actual project modules; user confirms or cancels
- **Git Checkpoint** — on first mutating tool call, creates `architect/task-{id}` branch; pre-task dirty tree saved as named stash; one-click Rollback restores original state
- **Semantic Context Window** — recently touched files hydrated with symbols and `imported_by` graph into a dynamic `## Active Context` block
- **Architecture Linter** — enforces `.architect-rules.yml` after every write; violations block continuation with memory-based alternative suggestions
- **Sticky Context** — after each successful edit, the module's `edit_hints` is updated with a timestamped summary so future calls see what changed
- **Task Briefing** — structured plan card at task start with steps, confidence, and risk level; Activity Feed shows animated "currently on step N" bar

### Memory Panel
- **Symbol navigation** — each module shows functions/classes/variables; click any symbol to jump to that line in the file viewer
- **Used by N badge** — modules show how many other modules import them; N≥5 highlighted as a hot spot
- **File context mode** — when a file is open in the editor, Memory Panel auto-focuses on that file's memory record

### A2A API
- **Architecture query** — `POST /api/a2a/query` — other agents can ask architecture questions; backed by project memory + JIT code reads
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
| Backend (FastAPI) | **8000** |
| Frontend (Vite/React) | **3011** |

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
DEFAULT_LLM_MODEL=anthropic/claude-sonnet-4-5

# Optional: cheaper model for bulk file analysis
ANALYSIS_LLM_MODEL=google/gemini-2.0-flash-lite-001

# Optional: bypass shell command allowlist (dev only)
# AGENT_SHELL_UNRESTRICTED=true
```

### 2. Start

```bash
./start.sh
```

Opens:
- Frontend: http://localhost:3011
- API docs: http://localhost:8000/docs

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
│   │   └── tools/
│   │       ├── chat_tools.py     # Chat tool-use: read_file, search_files, edit_file, escalate
│   │       ├── file_tools.py     # Agent file I/O tools
│   │       ├── shell_tools.py    # Shell execution with allowlist
│   │       ├── search_tools.py   # Code search tools
│   │       └── git_tools.py      # Git status/diff/checkpoint tools
│   ├── analysis/             # LLM file analyzer (chunked), large project handler
│   ├── codegen/              # Code generation helpers
│   ├── llm/
│   │   ├── client.py         # LLM client — OpenRouter/custom/Ollama, streaming + tool-use
│   │   ├── model_router.py   # Query complexity router (selects model per query)
│   │   └── chat_engine.py    # Chat engine — Architecture Map + JIT retrieval + tool loop
│   ├── memory/               # 3-tier memory (hot cache, markdown, vectors)
│   ├── patterns/             # Design pattern detector
│   ├── projects/             # Project manager
│   └── rag/                  # Hybrid BM25 + vector search
├── web/src/
│   ├── components/
│   │   ├── AgentActivityFeed.tsx  # Activity/Chat/File/Graph tabs + briefing card + step bar
│   │   ├── ChatBar.tsx            # Chat/Edit mode + tool-use event rendering + auto-escalation
│   │   ├── MemoryPanel.tsx        # Module list + symbol navigation + used-by badge
│   │   ├── PlanCard.tsx           # Plan A/B approval card
│   │   ├── EscalationCard.tsx     # Tool failure escalation UI
│   │   ├── TopBar.tsx             # Project selector + rollback + freshness indicator
│   │   ├── FileTree.tsx           # File tree with analysis status
│   │   └── FileEditor.tsx         # In-panel file viewer (click-to-line)
│   └── store/app.ts               # Zustand state (projects, memory, chat, agent session)
├── start.sh                       # One-command start
└── .env                           # API keys and model selection
```

---

## Chat Tool-Use SSE Events

When chatting with a project loaded, `/api/chat` streams these event types:

| Event | Description |
|-------|-------------|
| `chunk` | Text chunk of the final answer |
| `tool_thinking` | LLM calling a tool (shown as blockquote in chat bubble) |
| `tool_result` | Tool result consumed by LLM (not displayed to user) |
| `tool_edit` | A file was edited inline during chat |
| `escalate` | Task handed off to Edit Agent (auto-launches agent flow) |
| `done` | Stream complete |
| `error` | Stream error |

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

Base URL: `http://127.0.0.1:8000`

### Query an existing project

```bash
curl -X POST http://localhost:8000/api/a2a/query \
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
  "model_used": "anthropic/claude-sonnet-4-5"
}
```

### Edit an existing project

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

If no architecture memory exists, `POST /api/a2a/generate` returns **HTTP 428**:

```json
{
  "error": "project_memory_empty",
  "remediation": {
    "step_1": { "description": "Trigger analysis", "method": "POST", "path": "/api/analyze" },
    "step_2": { "description": "Poll for completion", "method": "GET", "path": "/api/projects/{id}/freshness" },
    "step_3": { "description": "Retry generate", "method": "POST", "path": "/api/a2a/generate" }
  }
}
```

### Create a new project from scratch

```bash
# 1. Scaffold
curl -X POST http://localhost:8000/api/a2a/scaffold \
  -H "Content-Type: application/json" \
  -d '{
    "project_path": "/path/to/my-service",
    "template": "fastapi-full",
    "project_name": "my-service",
    "options": {"git_init": true, "auto_analyze": true}
  }'

# 2. Wait for analysis
curl http://localhost:8000/api/projects/{project_id}/freshness

# 3. Generate
curl -X POST http://localhost:8000/api/a2a/generate \
  -d '{"task": "Implement POST /items", "project_id": "{project_id}", "mode": "apply"}'
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
| `CUSTOM_LLM_BASE_URL` | — | Corporate/on-prem OpenAI-compatible endpoint |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama fallback (used only if no API key) |
| `AGENT_SHELL_UNRESTRICTED` | `false` | Bypass shell command allowlist (dev only) |
