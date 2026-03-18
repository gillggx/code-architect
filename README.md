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
- **40-iteration limit** — per phase, so large multi-phase tasks are not cut off

### A2A API
- **Architecture query** — `POST /api/a2a/query` — other agents can ask architecture questions
- **Code generation** — `POST /api/a2a/generate`
- **Validation** — `POST /api/a2a/validate`
- **Impact analysis** — `POST /api/a2a/impact`

---

## Ports

| Service | Port |
|---------|------|
| Backend (FastAPI) | **8001** |
| Frontend (Vite/React) | **3001** |

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
│   ├── api/           # FastAPI routes, agent runner, tools, SOUL loader
│   │   └── tools/     # file_tools, shell_tools (with allowlist)
│   ├── analysis/      # LLM file analyzer (chunked), large project handler
│   ├── llm/           # LLM client, model router, chat engine (git context)
│   ├── memory/        # 3-tier memory (hot cache, markdown, vectors)
│   ├── patterns/      # Design pattern detector
│   ├── projects/      # Project manager
│   └── rag/           # Hybrid BM25 + vector search
├── web/               # React + TypeScript frontend
│   └── src/
│       ├── components/ # FileTree, AgentActivityFeed, ChatBar, PlanCard, EscalationCard, MemoryPanel
│       └── store/      # Zustand app state
├── start.sh           # One-command start
└── .env               # API keys and model selection
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

Other agents (e.g. agent-platform architect agents) can query this service:

```bash
curl -X POST http://localhost:8001/api/a2a/query \
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

The edit agent also accepts `chat_history` for context:

```json
{
  "task": "Add error handling to the login flow",
  "project_id": "my-project",
  "mode": "interactive",
  "chat_history": [
    {"role": "user", "content": "The login flow crashes on invalid tokens"},
    {"role": "assistant", "content": "I can see the issue in auth/jwt.py..."}
  ]
}
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | — | Required for cloud LLMs |
| `DEFAULT_LLM_MODEL` | `anthropic/claude-haiku-4-5` | Model for analysis, chat, and edit agent |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter endpoint |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama fallback |
| `AGENT_SHELL_UNRESTRICTED` | `false` | Bypass shell command allowlist (dev only) |
