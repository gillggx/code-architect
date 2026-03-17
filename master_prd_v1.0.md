# Code Architect Agent — Master PRD v1.0

**Date:** 2026-03-17
**Status:** Active
**Stack:** Python 3.13 / FastAPI / React 18 / TypeScript / OpenRouter LLM

---

## 1. Product Overview

Code Architect Agent is an AI-powered codebase analysis tool. Point it at any project directory and it:

1. **Scans** the file structure (AST-level, no LLM)
2. **Reads** important files with an LLM, building a structured memory of the codebase
3. **Lets you chat** about the architecture — answers grounded in that memory via RAG
4. **Exposes an A2A API** so other agents can query architecture and feasibility

The GUI is designed to make the agent's reasoning transparent: every file the LLM reads, every summary it writes, every pattern it detects — all visible in real time.

---

## 2. Architecture

### 2.1 Backend (`src/architect/`)

```
api/
  main.py          FastAPI app — all endpoints
  schemas.py       Pydantic request/response models
  auth.py          API key + rate limiting
  errors.py        Structured error types
  websocket.py     WebSocket connection manager

analysis/
  llm_analyzer.py  LLM-powered file analysis pipeline (core)
  large_project_handler.py  Sampling for 500+ file projects

llm/
  client.py        OpenRouter (primary) / Ollama (fallback) — streaming
  chat_engine.py   RAG context retrieval + prompt assembly + LLM call
  model_router.py  Query complexity classifier → model selection

memory/
  tier1.py         In-memory artifact store (patterns, edge cases)
  persistence.py   Tier1 ↔ Tier2 Markdown sync
  rag_integration.py  RAG ↔ memory bridge
  vector_index.py  Vector embeddings for memory artifacts
  incremental_analysis.py  File snapshot + diff for re-analysis

patterns/
  catalog.py       17 built-in design pattern definitions
  detector.py      Regex/AST pattern detector (no LLM)
  validators.py    Evidence validator + robustness checker

rag/
  chunker.py       Header-aware Markdown chunker (500 token max)
  embeddings.py    OpenAI text-embedding-3-small / TF-IDF+SVD fallback
  vector_store.py  Numpy cosine similarity store
  hybrid_search.py BM25 (0.4) + vector (0.6) hybrid search
  retriever.py     High-level index/query API

parsers/
  python_analyzer.py, cpp_analyzer.py, other_analyzers.py
  registry.py      Language → parser dispatch (8 languages)

mcp/
  server.py        MCP Protocol server for IDE integration

projects/
  manager.py       Multi-project context manager (max 5 concurrent)

qa/
  engine.py        Rule-based QA engine (pre-LLM fallback)
```

### 2.2 Frontend (`web/src/`)

```
App.tsx                3-panel shell
store/app.ts           Zustand store (all state)

components/
  TopBar.tsx           Header: title, project path, Analyze button, dark mode
  FileTree.tsx         Left panel: file list with analysis status
  AgentActivityFeed.tsx Center panel: real-time agent event stream
  MemoryPanel.tsx      Right panel: learned modules + detected patterns
  ChatBar.tsx          Fixed bottom: chat input + floating conversation overlay
```

### 2.3 Data Flow

```
User clicks Analyze
  → POST /api/analyze { project_path }
  → Returns { job_id }
  → Frontend connects WS /ws/analyze/{job_id}
  → Backend runs LLMAnalyzer.analyze_project() as asyncio task:
      1. Scan directory → emit "scan" events
      2. Prioritize files (max 40)
      3. For each file:
         a. Emit "llm_start"
         b. LLMClient.complete() → structured summary
         c. Emit "llm_done" with summary
         d. Emit "pattern" for each pattern found
      4. Emit "memory" → "done"
  → Frontend receives events via WS, updates all 3 panels

User types in ChatBar
  → POST /api/chat { message, project_id, session_id }
  → SSE stream: ChatEngine pulls RAG context → builds prompt → streams LLM reply
  → Frontend renders tokens as they arrive in chat overlay

Another agent sends a query
  → POST /api/a2a/query { question, project_id, query_type }
  → Returns structured JSON: { answer, confidence, sources, patterns_relevant, feasibility_score }
```

---

## 3. LLM Analysis Pipeline

**File:** `src/architect/analysis/llm_analyzer.py`

### Priority Selection (max 40 files)
1. Entry points: `main.py`, `app.py`, `index.ts`, `server.ts`, `__init__.py` at root
2. Config files: `*.config.*`, `pyproject.toml`, `package.json`, `Dockerfile`
3. Import-rich files: files with the most import statements (high connectivity)
4. Remaining source files by size

### Skip Rules
`node_modules`, `.git`, `__pycache__`, `venv`, `.venv`, `dist`, `build`, `*.min.js`, `*.lock`

### LLM Prompt (per file)
```
Analyze this {language} file. Return JSON with keys:
  purpose         - 1 sentence describing what this file does
  key_components  - list of important class/function names
  dependencies    - list of imported modules/packages
  patterns        - list of design patterns observed
  notes           - any important architectural observations
File: {relative_path}
{file_content (max 8000 chars)}
```

### Agent Events (WebSocket)
| Type | Icon | Meaning |
|------|------|---------|
| `scan` | 📂 | Directory scanned, N files found |
| `ast` | 🔍 | AST parsed, classes/functions counted |
| `llm_start` | 🤖 | LLM starting to read a file |
| `llm_done` | ✅ | LLM finished, summary ready |
| `memory` | 💾 | Summary saved to memory |
| `pattern` | 🏷 | Design pattern detected |
| `skip` | ➖ | File/dir skipped |
| `done` | 🎉 | Analysis complete with stats |
| `error` | ❌ | Something went wrong |

---

## 4. Chat System

**File:** `src/architect/llm/chat_engine.py`

- RAG retrieves top-8 context chunks from project memory
- System prompt includes: agent identity, project ID, semantic context, detected patterns
- Conversation history kept in-session only (not persisted to memory)
- Memory stores only code analysis results, not chat logs
- Model routing: simple→fast model, complex→powerful model

---

## 5. A2A (Agent-to-Agent) API

**Endpoint:** `POST /api/a2a/query`
**Auth:** None (internal network assumed)

```json
Request:
{
  "question": "Is it feasible to add real-time sync?",
  "project_id": "my-project",
  "query_type": "feasibility"  // architecture | feasibility | pattern | general
}

Response:
{
  "answer": "...",
  "confidence": 0.82,
  "sources": [],
  "patterns_relevant": ["Observer", "WebSocket"],
  "feasibility_score": 0.75,   // only for feasibility queries
  "model_used": "anthropic/claude-opus-4-5",
  "query_type": "feasibility"
}
```

**MCP Schema:** `GET /api/a2a/schema` — returns MCP-compatible tool/resource definitions for IDE integration (Cursor, Claude Code, Cline).

---

## 6. GUI Design

### Layout
```
┌─────────────────────────────────────────────────────────────┐
│ TopBar: Logo | Project path | [Analyze] | [Dark mode]        │
├────────────────┬───────────────────────────┬────────────────┤
│ 📁 Files (260) │ 🤖 Agent Activity (flex)  │ 🧠 Memory (300)│
│                │                           │                │
│ src/           │ 📂 Scanned 142 files       │ Modules: 8     │
│ ├ auth/  ✅   │ 🔍 AST: 38 classes         │ Patterns: 5    │
│ ├ api/   ✅   │ 🤖 Reading auth/jwt.py...  │                │
│ ├ models/ 🔄  │ ✅ jwt.py: JWT middleware   │ [auth]         │
│ └ utils/ ⏳   │    using HS256...          │ JWT auth,      │
│                │ 🤖 Reading models/user.py  │ rate limiting  │
│ Analyzed: 8/12 │ ✅ user.py: User model...  │                │
├────────────────┴───────────────────────────┴────────────────┤
│ 💬 Ask anything about the codebase...              [Send]    │
└─────────────────────────────────────────────────────────────┘
```

### Panel Responsibilities
- **FileTree (left):** Status of every file. Click to see LLM summary inline.
- **AgentActivityFeed (center):** Chronological stream of everything the agent does. Expandable summaries on llm_done events.
- **MemoryPanel (right):** Accumulated knowledge — modules with purpose/patterns, global pattern list.
- **ChatBar (bottom):** Always visible. Chat overlay floats above it.

---

## 7. LLM Configuration

**File:** `.env`

```bash
OPENROUTER_API_KEY=sk-or-...
DEFAULT_LLM_MODEL=anthropic/claude-opus-4-5
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OLLAMA_BASE_URL=http://localhost:11434   # fallback if no API key
```

### Supported Models (via OpenRouter)
| Model ID | Use Case |
|----------|----------|
| `anthropic/claude-opus-4-5` | Default — best quality |
| `anthropic/claude-sonnet-4-5` | Faster, cheaper |
| `qwen/qwen3-235b-a22b` | Large open model |
| `openai/gpt-4o` | GPT alternative |

---

## 8. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/stats` | API statistics |
| POST | `/api/analyze` | Start LLM analysis → returns job_id |
| GET | `/api/jobs/{job_id}` | Analysis job status |
| WS | `/ws/analyze/{job_id}` | Real-time AgentEvent stream |
| POST | `/api/chat` | Chat with LLM (SSE streaming) |
| POST | `/api/search` | Semantic search over memory |
| GET | `/api/projects` | List analyzed projects |
| POST | `/api/validate` | Validate code snippet |
| POST | `/api/suggest` | Pattern suggestions |
| POST | `/api/a2a/query` | Agent-to-agent structured query |
| GET | `/api/a2a/schema` | MCP-compatible schema |

---

## 9. Memory System

### Tier 1 — In-Memory (runtime)
- `MemoryTier1`: dict-based store for patterns, edge cases, artifacts
- Supports keyword search with confidence scoring

### Tier 2 — Persistent (disk)
- Stored in `/architect_memory/{project_id}/`
- Files: `PROJECT.md`, `PATTERNS.md`, `EDGE_CASES.md`, `INDEX.md`, `modules/*.md`
- Written by `MemoryPersistenceManager` after analysis
- Human-readable YAML-frontmatter Markdown

### RAG Layer
- `MarkdownChunker` splits Tier2 files into 500-token chunks
- `EmbeddingManager`: OpenAI `text-embedding-3-small` or TF-IDF+SVD (256-dim) fallback
- `VectorStore`: numpy cosine similarity
- `HybridSearch`: BM25 (α=0.4) + vector (α=0.6) + reranking
- `RAGMemoryIntegration`: unified search interface for ChatEngine

---

## 10. Language Support

AST parsing supported for: Python, C++, Java, JavaScript, TypeScript, Go, Rust, SQL, HTML

---

## 11. Running the Project

```bash
# 1. Set your OpenRouter API key
echo "OPENROUTER_API_KEY=sk-or-..." >> .env

# 2. Start everything
./start.sh

# Frontend: http://localhost:3000
# Backend:  http://localhost:8000
# API docs: http://localhost:8000/docs
```

---

## 12. Project File Structure

```
code-architect/
├── src/architect/          Python backend package
│   ├── analysis/           LLM analysis pipeline
│   ├── api/                FastAPI endpoints
│   ├── llm/                LLM client + chat engine + model router
│   ├── memory/             3-tier memory system
│   ├── mcp/                MCP protocol server
│   ├── models.py           Pydantic data models
│   ├── parsers/            8-language AST parsers
│   ├── patterns/           Design pattern catalog + detector
│   ├── projects/           Multi-project manager
│   ├── qa/                 Rule-based QA (pre-LLM fallback)
│   └── rag/                Hybrid search + embeddings
├── web/                    React 18 frontend
│   └── src/
│       ├── components/     TopBar, FileTree, AgentActivityFeed,
│       │                   MemoryPanel, ChatBar
│       └── store/app.ts    Zustand global state
├── tests/                  pytest test suite (123 tests)
├── .env                    API keys + model config
├── start.sh                One-command launcher
├── docker-compose.yml      Docker orchestration
└── master_prd_v1.0.md      This document
```
