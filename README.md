# Code Architect Agent

An AI-powered codebase analysis tool. Point it at any project directory and it reads your code with an LLM, builds a structured memory of the architecture, and lets you chat about it in real time.

**Stack:** Python 3.13+ / FastAPI / React 18 / TypeScript / OpenRouter (Claude Opus)

---

## What it does

1. **Scans** the project file structure (AST-level, no LLM cost)
2. **Reads** important files with an LLM, building a structured memory of modules, patterns, and dependencies
3. **Shows** the agent's work in real time — every file it reads, every summary it writes
4. **Lets you chat** about the architecture — answers grounded in memory via RAG
5. **Incremental re-analysis** — on re-run, only changed/new files are re-processed
6. **A2A API** — other agents can query architecture and feasibility via REST

---

## Screenshot

```
┌─────────────────────────────────────────────────────────────┐
│ 🏗 Code Architect  workspace/MyProject          [Analyze] 🌙 │
├────────────────┬───────────────────────────┬────────────────┤
│ 📁 FILES (39)  │ 🤖 AGENT ACTIVITY         │ 🧠 MEMORY      │
│                │                           │                │
│ ✅ main.py     │ 03:24:09 ✅ DONE          │ MODULES: 8     │
│ ✅ api/auth.py │   auth.py: JWT middleware │                │
│ 🔄 models/     │   using HS256...          │ [auth]         │
│ ⏳ utils/      │ 03:24:16 🤖 READING       │ JWT auth,      │
│                │   Reading models/user.py  │ rate limiting  │
│ 12/40 (30%)  ██│ 03:24:25 ✅ DONE          │                │
│ ░░░░░░░░░░░░░░ │   user.py: User model ... │ PATTERNS: 5    │
├────────────────┴───────────────────────────┴────────────────┤
│ 💬 Ask anything about the codebase...              [Send]    │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Prerequisites

- Python 3.13+
- Node.js 18+
- An [OpenRouter](https://openrouter.ai) API key (or Ollama running locally as fallback)

### 1. Clone & configure

```bash
git clone https://github.com/gillggx/code-architect.git
cd code-architect

# Add your OpenRouter API key
echo "OPENROUTER_API_KEY=sk-or-v1-..." >> .env
```

### 2. Start everything

```bash
./start.sh
```

This kills any old processes on ports 8000/3000, installs dependencies, and starts both servers.

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **API docs:** http://localhost:8000/docs

### 3. Analyze a project

1. Click **Analyze** in the top bar
2. Click **📁 Choose Folder** — a native macOS Finder dialog opens (or paste a path directly)
3. The pre-scan shows how many files will be analyzed
4. Click **Start Analysis**

Watch the agent read your code in real time across three panels.

---

## Usage Guide

### Panels

| Panel | What it shows |
|-------|---------------|
| **📁 Files (left)** | Every file with status: ⏳ pending · 🔄 analyzing · ✅ done · ➖ skipped. Click any file to read the LLM summary inline. Progress bar at bottom. |
| **🤖 Agent Activity (center)** | Chronological stream of everything the agent does. Click **more** on any `✅ DONE` event to expand the full summary. |
| **🧠 Memory (right)** | Accumulated knowledge — modules with purpose/patterns, global detected patterns list. |
| **💬 Chat (bottom)** | Always visible. Click the 💬 icon to open the conversation overlay. Chat is disabled while analysis is running. |

### Chat

After analysis completes, ask anything about the project:

```
"What design patterns does this codebase use?"
"Explain the authentication flow"
"Is it feasible to add WebSocket support?"
"What are the main entry points?"
```

Answers are grounded in the memory built during analysis (RAG retrieval).

### Incremental re-analysis

On subsequent runs of the **same project**, only files that have changed since the last analysis are sent to the LLM. Unchanged files are skipped instantly, saving time and API cost.

---

## Environment Variables

Create a `.env` file in the project root:

```bash
# Required: OpenRouter API key
OPENROUTER_API_KEY=sk-or-v1-...

# Optional: override default model (default: anthropic/claude-opus-4-6)
DEFAULT_LLM_MODEL=anthropic/claude-opus-4-6

# Optional: OpenRouter base URL
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# Optional: Ollama fallback (used when no API key is set)
OLLAMA_BASE_URL=http://localhost:11434
```

### Supported Models (via OpenRouter)

| Model ID | Notes |
|----------|-------|
| `anthropic/claude-opus-4-6` | Default — best quality |
| `anthropic/claude-sonnet-4-6` | Faster, cheaper |
| `qwen/qwen3-235b-a22b` | Large open model |
| `openai/gpt-4o` | GPT alternative |

---

## Architecture

### Backend (`src/architect/`)

```
api/
  main.py              FastAPI app — all endpoints
  schemas.py           Pydantic request/response models

analysis/
  llm_analyzer.py      LLM-powered file analysis pipeline (core)
  large_project_handler.py  Sampling for 500+ file projects

llm/
  client.py            OpenRouter (primary) / Ollama (fallback)
  chat_engine.py       RAG context retrieval + prompt assembly + streaming
  model_router.py      Query complexity classifier → model selection

memory/
  tier1.py             In-memory artifact store
  persistence.py       Tier1 ↔ Tier2 Markdown sync
  incremental_analysis.py  File snapshot + diff for re-analysis
  rag_integration.py   RAG ↔ memory bridge
  vector_index.py      Vector embeddings for memory artifacts

patterns/
  catalog.py           17 built-in design pattern definitions
  detector.py          Regex/AST pattern detector (no LLM)

rag/
  chunker.py           Header-aware Markdown chunker (500 token max)
  embeddings.py        OpenAI text-embedding-3-small / TF-IDF+SVD fallback
  vector_store.py      Numpy cosine similarity store
  hybrid_search.py     BM25 (0.4) + vector (0.6) hybrid search
  retriever.py         High-level index/query API

parsers/
  python_analyzer.py, cpp_analyzer.py, other_analyzers.py
  registry.py          Language → parser dispatch (8 languages)
```

### Frontend (`web/src/`)

```
App.tsx                3-panel shell
store/app.ts           Zustand store (all state)

components/
  TopBar.tsx           Header: project path, Analyze button, dark mode
  FileTree.tsx         Left panel: file list with status + progress bar
  AgentActivityFeed.tsx Center panel: real-time event stream
  MemoryPanel.tsx      Right panel: modules + detected patterns
  ChatBar.tsx          Fixed bottom: SSE streaming chat
```

### Data Flow

```
User clicks Analyze
  → POST /api/analyze { project_path }
  → Returns { job_id, project_id }
  → Frontend connects WebSocket /ws/analyze/{job_id}
  → Backend runs LLMAnalyzer as asyncio task:
      1. Load snapshot from architect_memory/{project_id}/SNAPSHOTS.json
      2. Detect changed/new files (skip unchanged)
      3. Scan directory → emit "scan" events
      4. Prioritize files (max 40)
      5. For each file:
         a. Emit "llm_start"
         b. LLMClient.complete() → structured JSON summary
         c. Emit "llm_done" with summary
      6. Emit "memory" → save snapshot → "done"
  → Frontend receives events, updates all 3 panels live

User types in ChatBar
  → POST /api/chat { message, project_id, session_id }
  → SSE stream: ChatEngine pulls RAG context → builds prompt → streams reply
  → Frontend renders tokens as they arrive
```

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/analyze` | Start analysis → `{ job_id, project_id }` |
| `GET` | `/api/jobs/{job_id}` | Job status |
| `WS` | `/ws/analyze/{job_id}` | Real-time AgentEvent stream |
| `POST` | `/api/chat` | Chat with LLM (SSE streaming) |
| `POST` | `/api/search` | Semantic search over memory |
| `GET` | `/api/projects` | List analyzed projects |
| `GET` | `/api/browse?path=X` | Directory listing (web folder browser) |
| `GET` | `/api/scan?path=X` | File count pre-analysis |
| `GET` | `/api/native-pick` | Open native macOS Finder folder picker |
| `POST` | `/api/a2a/query` | Agent-to-agent structured query |
| `GET` | `/api/a2a/schema` | MCP-compatible tool schema |

### WebSocket Event Types

| Type | Icon | Meaning |
|------|------|---------|
| `scan` | 📂 | Directory scanned, N files found |
| `ast` | 🔍 | AST parsed |
| `llm_start` | 🤖 | LLM starting to read a file |
| `llm_done` | ✅ | LLM finished, summary ready |
| `memory` | 💾 | Summary saved to memory |
| `skip` | ➖ | File skipped (unchanged or low priority) |
| `done` | 🎉 | Analysis complete |
| `error` | ❌ | Something went wrong |

---

## A2A (Agent-to-Agent) API

Other agents can query architecture and feasibility without going through the UI:

```bash
curl -X POST http://localhost:8000/api/a2a/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Is it feasible to add real-time sync?",
    "project_id": "my-project",
    "query_type": "feasibility"
  }'
```

```json
{
  "answer": "Yes, feasible. The project already uses WebSocket infrastructure...",
  "confidence": 0.82,
  "sources": ["api/websocket.py", "models/events.py"],
  "patterns_relevant": ["Observer", "WebSocket"],
  "feasibility_score": 0.75,
  "model_used": "anthropic/claude-opus-4-6",
  "query_type": "feasibility"
}
```

**Query types:** `architecture` · `feasibility` · `pattern` · `general`

**MCP schema** (for IDE integration with Cursor / Claude Code / Cline):
```bash
GET http://localhost:8000/api/a2a/schema
```

---

## Memory Storage

Analysis results are persisted to `architect_memory/{project_id}/`:

```
architect_memory/my-project/
├── PROJECT.md        Project metadata
├── PATTERNS.md       Detected design patterns
├── EDGE_CASES.md     Known issues / observations
├── INDEX.md          Module index
├── SNAPSHOTS.json    File fingerprints for incremental re-analysis
└── modules/
    ├── auth.md
    ├── api.md
    └── ...
```

These are human-readable Markdown files — you can read and edit them directly.

---

## Language Support

AST parsing: **Python**, **C++**, **Java**, **JavaScript**, **TypeScript**, **Go**, **Rust**, **SQL**, **HTML**

---

## Docker

```bash
docker-compose up
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000

---

## Development

```bash
# Backend only
cd src && uvicorn architect.api.main:app --reload --port 8000

# Frontend only
cd web && npm run dev

# Run tests
python3 -m pytest tests/ -v
```

---

## Project Structure

```
code-architect/
├── src/architect/         Python backend package
│   ├── analysis/          LLM analysis pipeline
│   ├── api/               FastAPI endpoints
│   ├── llm/               LLM client + chat engine
│   ├── memory/            3-tier memory + incremental analysis
│   ├── patterns/          Design pattern catalog + detector
│   ├── rag/               Hybrid search + embeddings
│   └── parsers/           8-language AST parsers
├── web/                   React 18 frontend
│   └── src/
│       ├── components/    TopBar, FileTree, AgentActivityFeed,
│       │                  MemoryPanel, ChatBar
│       └── store/app.ts   Zustand global state
├── tests/                 pytest suite
├── architect_memory/      Per-project memory (git-ignored)
├── .env                   API keys (git-ignored)
├── start.sh               One-command launcher
├── docker-compose.yml     Docker orchestration
└── master_prd_v1.0.md     Full product spec
```
