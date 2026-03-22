# Code Architect Agent — Master PRD v2.0

**Date:** 2026-03-21
**Status:** Active
**Stack:** Python 3.13 / FastAPI / React 18 / TypeScript / CodeMirror 6 / Zustand / OpenRouter / Custom LLM
**Supersedes:** master_prd_v1.0.md

---

## 1. Product Overview

Code Architect Agent is an AI-powered codebase analysis, exploration, and editing platform. It gives any developer (or agent) a pre-loaded architectural memory of a codebase, then surfaces that memory through a layered GUI and a structured A2A API.

### What it does today (v2.0)

1. **Analyzes** — scans a project directory, reads important files with an LLM, builds a structured memory (purpose, patterns, key components) per file
2. **Remembers** — persists the memory to disk; subsequent sessions load instantly, no re-analysis needed
3. **Explains** — chat over the whole project (RAG-backed) or select any code snippet → get a contextual explanation inline
4. **Edits** — full CodeMirror 6 editor embedded in the browser; files read from and written back to disk
5. **Exposes** — A2A API so other agents can query architecture, assess feasibility, and generate/validate code changes

### Design principle

The agent's reasoning is always visible. Every LLM read, every pattern detected, every memory module — streamed in real time to the GUI. The Memory panel shows what the system knows about any file the moment you open it.

---

## 2. Architecture

### 2.1 Backend (`src/architect/`)

```
api/
  main.py          FastAPI app — all endpoints (analysis, file I/O, chat, A2A, project load)
  schemas.py       Pydantic models (ChatRequest with system_override, FileRequest, etc.)
  agent_runner.py  Agentic loop — tool dispatch + SSE streaming
  diff.py          Unified diff generator for code edit agent

analysis/
  llm_analyzer.py  LLM analysis pipeline; incremental with error-content detection

llm/
  client.py        LLM client — priority: OpenRouter → Custom LLM → Ollama
  chat_engine.py   RAG context retrieval + prompt assembly + LLM streaming
  model_router.py  Query complexity classifier → model selection

memory/
  tier1.py         In-memory artifact store
  persistence.py   Tier1 ↔ Tier2 Markdown sync
  rag_integration.py  RAG ↔ memory bridge
  vector_index.py  Vector embeddings
  incremental_analysis.py  File snapshot + diff; detects prior LLM errors → forces re-analysis

patterns/
  catalog.py       17 built-in design pattern definitions
  detector.py      Regex/AST pattern detector

rag/
  chunker.py, embeddings.py, vector_store.py, hybrid_search.py, retriever.py

parsers/
  python_analyzer.py, cpp_analyzer.py, other_analyzers.py
  registry.py      Language → parser dispatch (8 languages + HTML)

api/tools/          Agent tool implementations (Phase A complete)
  file_tools.py    read_file, write_file, edit_file, list_files
  search_tools.py  search_code (grep), search_memory
  git_tools.py     git_status, git_diff
  shell_tools.py   run_command (allowlist-constrained)
  memory_tools.py  search_memory

mcp/server.py      MCP Protocol server for IDE integration
projects/manager.py  Multi-project context manager (max 5 concurrent)
```

### 2.2 Frontend (`web/src/`)

```
App.tsx                         3-panel shell
store/app.ts                    Zustand store — all state including:
                                  centerTab: 'activity' | 'chat' | 'file'
                                  openedFile: { path, projectId } | null
                                  editMode: boolean

components/
  TopBar.tsx                    Header: project path, Analyze button, dark mode, edit mode toggle
  FileTree.tsx                  Left panel: file tree with analysis status; click-to-open in edit mode
  AgentActivityFeed.tsx         Center panel: 3-tab (Activity / Chat / File Editor)
  FileEditor.tsx                CodeMirror 6 editor: syntax highlight, save, explain selection
  MemoryPanel.tsx               Right panel: contextual (file-focused) or global module list
  ChatBar.tsx                   Fixed bottom: project chat with SSE streaming
  ProjectManagerPanel.tsx       Project cards: analyze new, open existing, delete
```

### 2.3 Panels & Tabs

```
┌──────────────────────────────────────────────────────────────────────────┐
│ TopBar: Logo | Project path | [Analyze] | [Edit mode ☑] | [◐ Dark mode]  │
├──────────────────┬─────────────────────────────┬────────────────────────┤
│ 📁 Files  (260)  │  🤖 Activity │ 💬 Chat │ ✎ auth.py  │  🧠 Memory     │
│                  │─────────────────────────────│                        │
│ src/             │ (Activity tab)               │ (file-context mode)    │
│ ├ auth/ ✅      │  📂 Scanned 142 files        │ auth.py                │
│ ├ api/  ✅      │  🤖 Reading auth.py...        │ /src/architect/auth.py │
│ └ models/ 🔄    │  ✅ jwt.py: JWT middleware    │                        │
│                  │                              │ 📌 Purpose             │
│ Analyzed: 8/12   │ (File Editor tab)            │ JWT token validation   │
│                  │  ┌──────────────────────┐    │ middleware using HS256  │
│ [✎ Open in Edit] │  │ /*                   │    │                        │
│                  │  │  * Memory: auth.py   │    │ 🏷 Patterns            │
│                  │  │  * Purpose: JWT...   │    │ Middleware  Singleton   │
│                  │  │  */                  │    │                        │
│                  │  │  import jwt          │    │ 🔑 Key Components      │
│                  │  │  ...                 │    │ • verify_token()       │
│                  │  │  [selected code ████]│    │ • JWTMiddleware        │
│                  │  │                      │    │                        │
│                  │  │ [💬 Explain] [Save]  │    │ [↕ 全部] [Clear]      │
│                  │  └──────────────────────┘    │                        │
├──────────────────┴─────────────────────────────┴────────────────────────┤
│ 💬 Ask anything about the codebase…                             [Send]   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Feature Specifications

### 3.1 Codebase Analysis

- **Trigger:** POST `/api/analyze { project_path }`
- **Pipeline:** scan → AST parse → prioritize (max 40 files) → LLM per file → patterns → done
- **Priority selection:** entry points → config files → import-rich files → remaining by size
- **Incremental re-analysis:** snapshot per file (mtime + size); if prior run produced LLM errors → force full re-analysis of failed files
- **Events** streamed via WebSocket `/ws/analyze/{job_id}`: `scan`, `ast`, `llm_start`, `llm_done`, `memory`, `pattern`, `skip`, `done`, `error`
- **Skip rules:** `node_modules`, `.git`, `__pycache__`, `venv`, `dist`, `build`, `*.min.js`, `*.lock`

### 3.2 Project Memory

**Tier 1 — In-memory (runtime)**
- Dict-based store for patterns, edge cases, artifacts
- Keyword search with confidence scoring

**Tier 2 — Persistent (disk)**
- `architect_memory/{project_id}/` — Markdown files per module + PATTERNS.md + INDEX.md
- `modules.json` — serialized MemoryModule list (used for incremental analysis and project reload)
- `project_path.txt` — absolute path of the analyzed project root

**RAG Layer**
- MarkdownChunker → 500-token chunks
- Embeddings: OpenAI `text-embedding-3-small` or TF-IDF+SVD fallback (256-dim)
- HybridSearch: BM25 (α=0.4) + vector (α=0.6) + reranking

### 3.3 Open Project (Load Without Re-analysis)

- **Trigger:** "🗂 開啟" button on a project card in ProjectManagerPanel
- **Flow:** `GET /api/projects/{project_id}/load` → reads `modules.json` + `project_path.txt` → restores frontend state (memoryModules, fileTree, selectedProject) without running the LLM pipeline
- **Edit mode option:** checkbox "開啟時進入 Edit 模式" auto-enables file editing on load
- **Use case:** inspect or edit a project analyzed in a previous session with zero waiting

### 3.4 File Editor (CodeMirror 6)

- **Activation:** click any file in FileTree while Edit mode is on → center panel switches to "✎ filename" tab
- **Memory annotation:** block comment injected at top from in-memory module data (zero latency — no fetch needed)
- **Async load:** `GET /api/file?path=…&project_id=…` — resolves relative paths against project root; rejects binary files
- **Save:** `POST /api/file { path, content, project_id }` — path security check (must be under project root)
- **Syntax highlighting:** JS/JSX/TS/TSX, Python, JSON, CSS/SCSS, HTML, Markdown; falls back gracefully
- **Selection tracking:** `EditorView.updateListener` → tracks selected text
- **Dirty state:** "● unsaved" indicator; Save button disabled when clean

### 3.5 Explain Selection

- **Trigger:** select any code in the editor → "💬 Explain" button becomes active
- **Context building:**
  - Surrounding lines (±80 lines around selection) from full file content
  - Memory module for the file (purpose, patterns, key components)
  - Selected snippet
- **Prompt:** system override injected via `ChatRequest.system_override` — bypasses standard RAG chat, uses custom context directly
- **Output:** streaming ExplainPanel below the editor; closeable; re-triggerable
- **Language:** LLM instructed to respond in the same language as the user

### 3.6 Contextual Memory Panel

- **File-context mode:** active when `centerTab === 'file'` and `openedFile` is set
- **Matching:** `findModuleForFile()` — matches by exact path, suffix, or filename
- **FileMemoryDetail:** expanded view with Purpose (section label + formatted block), Patterns (badges), Key Components (bulleted list)
- **Error state:** modules with LLM-error purposes show "⚠ 分析失敗（需重新分析）" instead of raw error text
- **Toggle:** "↕ 全部" / "← filename" — switch between file-focused and global list

### 3.7 Project Chat

- **Endpoint:** `POST /api/chat { message, project_id, session_id, system_override? }` → SSE streaming
- **RAG:** top-8 context chunks from project memory; model routing based on query complexity
- **Session history:** in-session only, not persisted
- **system_override:** if set, bypasses RAG and uses the provided system prompt directly (used by Explain Selection)

### 3.8 A2A API

**Current (implemented):**
- `POST /api/a2a/query` — architecture/feasibility/pattern/general queries; returns `{ answer, confidence, sources, patterns_relevant, feasibility_score }`
- `GET /api/a2a/schema` — MCP-compatible schema for IDE integration

**Planned (Phase B — Code Edit Agent):**
- `POST /api/a2a/generate` — generate code changes (`dry_run` | `apply` | `interactive` modes)
- `POST /api/a2a/validate` — validate code against project patterns
- `POST /api/a2a/impact` — impact analysis before modifying a module
- `POST /api/agent/approve` — resume interactive session

---

## 4. LLM Configuration

**Priority order (auto-detected from env):**
1. **OpenRouter** — if `OPENROUTER_API_KEY` is set
2. **Custom LLM** — if `CUSTOM_LLM_BASE_URL` is set and no OpenRouter key (OpenAI-compatible endpoint, no model mapping)
3. **Ollama** — local fallback

```bash
# .env
OPENROUTER_API_KEY=sk-or-...
DEFAULT_LLM_MODEL=anthropic/claude-opus-4-5
ANALYSIS_LLM_MODEL=google/gemini-2.0-flash-lite-001   # cheaper model for per-file analysis

# Corporate on-prem LLM (mutually exclusive with OpenRouter)
CUSTOM_LLM_BASE_URL=https://llm.company.internal/v1
CUSTOM_LLM_API_KEY=your-internal-key
# Model name is passed through as-is — no mapping
```

---

## 5. API Endpoints (v2.0 Complete)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/stats` | API statistics |
| POST | `/api/analyze` | Start LLM analysis → returns job_id |
| GET | `/api/jobs/{job_id}` | Analysis job status |
| WS | `/ws/analyze/{job_id}` | Real-time AgentEvent stream |
| POST | `/api/chat` | Chat with LLM (SSE streaming); supports system_override |
| GET | `/api/file` | Read file content (resolves relative paths) |
| POST | `/api/file` | Write file content (security: must be under project root) |
| GET | `/api/projects` | List analyzed projects |
| GET | `/api/projects/{id}/load` | Load project memory without re-analysis |
| POST | `/api/search` | Semantic search over memory |
| POST | `/api/validate` | Validate code snippet |
| POST | `/api/suggest` | Pattern suggestions |
| POST | `/api/a2a/query` | Agent-to-agent structured query |
| GET | `/api/a2a/schema` | MCP-compatible schema |
| POST | `/api/a2a/generate` | Generate/apply code changes *(Phase B)* |
| POST | `/api/a2a/validate` | Validate code against patterns *(Phase B)* |
| POST | `/api/a2a/impact` | Impact analysis *(Phase B)* |
| POST | `/api/agent/approve` | Resume interactive session *(Phase B)* |

---

## 6. Running the Project

```bash
# One-command start
./start.sh

# Manual start (loads .env correctly)
set -a; source .env; set +a
uvicorn src.architect.api.main:app --port 8765 &
cd web && npm run dev

# Frontend: http://localhost:3000
# Backend:  http://localhost:8765
# API docs: http://localhost:8765/docs
```

---

## 7. Capability Comparison: Code Architect Agent vs Claude Code

This section compares what this project offers versus Claude Code (the CLI tool powering this conversation).

### 7.1 Feature Matrix

| Capability | Code Architect Agent | Claude Code (CLI) |
|------------|---------------------|-------------------|
| **Codebase analysis** | Batch LLM analysis, all files up-front, structured memory | On-demand — reads files as needed per query |
| **Memory persistence** | ✅ `modules.json` persists between sessions | ✅ `CLAUDE.md` + file-based memory system |
| **Architecture explanation** | ✅ RAG-backed, grounded in pre-analyzed modules | ✅ Reads code on demand; good at synthesis |
| **Code explanation** | ✅ Explain Selection with file + project context | ✅ Full codebase context, multi-file reasoning |
| **Code editing** | ✅ Browser-based CodeMirror editor (manual) | ✅ Direct file Edit/Write tools (programmatic) |
| **Code generation** | ⚠ Phase B (in PRD, not fully shipped) | ✅ Full: creates files, edits, runs tests |
| **Multi-file refactors** | ⚠ Phase B | ✅ Native — can touch any number of files |
| **Test execution** | ⚠ Phase B (run_command allowlist) | ✅ Bash tool — runs pytest, npm test, etc. |
| **Git operations** | ⚠ Phase B (git_status, git_diff only) | ✅ Full git: commit, push, PR creation |
| **Terminal / shell** | ⚠ Phase B (allowlist-constrained) | ✅ Full Bash tool |
| **Web search / fetch** | ❌ Not implemented | ✅ WebSearch + WebFetch tools |
| **A2A / programmatic API** | ✅ REST API (`/api/a2a/query`) | ❌ CLI only; no REST API |
| **MCP integration** | ✅ `/api/a2a/schema` for Cursor/Cline | ✅ MCP client (can use external servers) |
| **Real-time visualization** | ✅ Streaming event feed, all agent actions visible | ❌ CLI output only |
| **Multi-project management** | ✅ Project manager UI, switch between projects | ❌ Single working directory per session |
| **Design pattern detection** | ✅ 17 built-in patterns, AST + LLM | ❌ Not a built-in feature |
| **Corporate LLM support** | ✅ CUSTOM_LLM_BASE_URL (any OpenAI-compatible) | ✅ Via ANTHROPIC_BASE_URL or API config |
| **Offline / local LLM** | ✅ Ollama fallback | ❌ Anthropic API required |
| **Browser GUI** | ✅ React SPA | ❌ Terminal only |
| **Contextual memory in editor** | ✅ Memory panel updates to show current file's module | N/A |
| **Parallel tool calls** | ❌ Sequential analysis | ✅ Native parallel tool use |
| **Hooks / automation** | ❌ Not implemented | ✅ Pre/post tool hooks via settings.json |
| **Agent SDK / subagents** | ❌ Single-agent | ✅ Agent tool for spawning specialized subagents |

### 7.2 Where Code Architect Leads

1. **Pre-loaded structured memory** — by the time you ask a question, the LLM already knows the full architecture. Claude Code reads files reactively; Code Architect reads proactively and stores structured summaries.
2. **A2A REST API** — other agents can query this system programmatically. Claude Code has no API surface.
3. **Real-time transparency** — every LLM operation streams to the GUI. You see exactly what the agent knows and how it reached its conclusions.
4. **Multi-project workspace** — analyze and switch between multiple projects without losing context.
5. **Design pattern catalog** — structured detection of 17 patterns with evidence; something Claude Code doesn't do natively.
6. **Browser-first** — accessible from any machine on the network, not just the terminal user.

### 7.3 Where Claude Code Leads

1. **Execution capability** — Claude Code can run tests, commit code, push to GitHub, create PRs, run arbitrary shell commands. Code Architect is still read-mostly (Phase B will close this gap).
2. **Multi-file code generation** — Claude Code can generate and apply complex multi-file changes in a single turn. Code Architect's edit agent is planned but incomplete.
3. **Reactivity** — Claude Code's on-demand reading adapts to whatever the conversation needs. The pre-analysis approach means Code Architect's knowledge is as fresh as its last analysis run.
4. **Web access** — Claude Code can fetch URLs, search the web. Code Architect is entirely offline.
5. **Subagent system** — Claude Code can spawn specialized agents (Explore, Plan, etc.) in parallel. Code Architect is a single-agent system.
6. **IDE integration depth** — Claude Code has a VSCode extension, keybindings, hooks. Code Architect has MCP schema only.

---

## 8. Improvement Roadmap

Prioritized by impact vs effort.

### 8.1 High Impact, Achievable Now

**[P0] Complete Phase B — Code Edit Agent**
The PRD is written (`code_edit_agent_prd_v1.0.md`). The backend tool layer exists (`api/tools/`, `agent_runner.py`, `diff.py`). What remains:
- Wire `POST /api/a2a/generate` end-to-end
- Build the diff card UI in AgentActivityFeed (Apply / Edit / Skip)
- Add `POST /api/a2a/validate` and `POST /api/a2a/impact`
This closes the biggest gap with Claude Code.

**[P0] Incremental Analysis UX**
Currently "re-analyze" re-runs the full pipeline. The error-content fix forces re-analysis of failed files, but there's no way to analyze *only new files* added since last run. Add a "Refresh" mode: scan for files not in modules.json → analyze only those → merge.

**[P1] Streaming Chat Memory**
Chat session history is in-memory only. Adding optional persistence (per project, per session) enables multi-session conversations and debugging ("why did you say X?").

**[P1] Analysis Freshness Indicator**
Show when the last analysis was run. If any tracked file has a newer mtime than the snapshot, show a "⚠ N files changed since analysis" warning with a one-click re-analyze.

**[P1] Parallel File Analysis**
Current pipeline analyzes files sequentially. Running 4–8 LLM calls concurrently would cut analysis time 4–8×. Requires rate-limit awareness (OpenRouter per-minute limits).

### 8.2 Medium Impact

**[P2] Chat History Persistence**
Export/import conversation history per project. Useful for handoff — "here's what I learned about this codebase."

**[P2] Explanation Quality: Use Structured Memory**
The Explain Selection feature builds context from raw file content. It should also pull the memory module for *imported modules* — if the selected code calls `auth.verify_token()`, include auth.py's memory too.

**[P2] Git-Aware Analysis**
After Phase B lands, add git integration: `git diff HEAD` → analyze only changed files → update affected modules in memory. Makes the memory stay fresh after every commit without a full re-analysis.

**[P2] Pattern-Based Code Templates**
When generating code (Phase B), pull the detected patterns for the target file as constraints. "This file uses Repository pattern — generated code must follow it." Currently pattern detection feeds the explanation; it should also constrain generation.

**[P2] Export Memory as Context**
"Copy project memory as markdown" or "export as CLAUDE.md" — lets you inject Code Architect's structured analysis into any other tool (Claude Code, Cursor, etc.) as a one-shot context boost.

### 8.3 Larger Features

**[P3] Web Search Integration**
Add a WebFetch tool to the agentic loop. Useful for "how does this pattern work?" or "what does this npm package do?" without leaving the tool.

**[P3] Multi-Agent Analysis**
Spawn parallel analysis agents — one per subsystem (auth/, api/, models/) — merge results. Would enable accurate analysis of 200+ file projects within reasonable time.

**[P3] Test Generation**
Given a memory module, generate a test file that exercises the key components. The memory already knows the function signatures and patterns; test generation is a natural next step.

**[P3] Dependency Graph Visualization**
The memory stores `dependencies` per module. Render an interactive dependency graph (D3 or Cytoscape) — click a node to open the file, hover to see the memory summary. This would be the killer visualization feature.

**[P3] VSCode Extension**
Package the A2A API as a VSCode extension — right-click on any file → "Explain with Code Architect", or inline ghost-text suggestions using the pre-loaded memory. This is where the real developer experience unlock happens.

---

## 9. File Structure (v2.0)

```
code-architect-agent-platform/
├── src/architect/
│   ├── analysis/
│   │   ├── llm_analyzer.py         Analysis pipeline + incremental + error detection
│   │   └── large_project_handler.py
│   ├── api/
│   │   ├── main.py                 All endpoints incl. /api/file, /api/projects/{id}/load
│   │   ├── schemas.py              ChatRequest.system_override, FileRequest, etc.
│   │   ├── agent_runner.py         Agentic loop (Phase B)
│   │   ├── diff.py                 Unified diff generator (Phase B)
│   │   └── tools/                  file/search/git/shell/memory tools (Phase B)
│   ├── llm/
│   │   ├── client.py               OpenRouter → Custom LLM → Ollama priority chain
│   │   ├── chat_engine.py          RAG + prompt assembly + streaming
│   │   └── model_router.py         Complexity-based model selection
│   ├── memory/
│   │   ├── tier1.py, persistence.py, rag_integration.py
│   │   ├── vector_index.py
│   │   └── incremental_analysis.py
│   ├── patterns/                   17 pattern catalog + detector
│   ├── rag/                        Hybrid search + embeddings
│   ├── parsers/                    8 languages + HTML
│   ├── mcp/server.py               MCP schema
│   └── projects/manager.py
├── web/src/
│   ├── App.tsx
│   ├── store/app.ts                centerTab, openedFile, editMode
│   └── components/
│       ├── TopBar.tsx
│       ├── FileTree.tsx            Click-to-open in edit mode
│       ├── AgentActivityFeed.tsx   3-tab: Activity / Chat / File Editor
│       ├── FileEditor.tsx          CodeMirror 6 + Explain Selection
│       ├── MemoryPanel.tsx         Contextual (file) + global (list) modes
│       ├── ChatBar.tsx
│       └── ProjectManagerPanel.tsx Open + analyze projects
├── architect_memory/               Persisted project memories
│   └── {project_id}/
│       ├── modules.json
│       ├── project_path.txt
│       └── *.md
├── .env                            API keys + LLM config
├── start.sh                        One-command launcher (port 8765)
├── master_prd_v1.0.md
├── master_prd_v2.0.md              This document
└── code_edit_agent_prd_v1.0.md    Phase B detailed spec
```

---

## 10. Known Limitations

| Issue | Status |
|-------|--------|
| Max 40 files analyzed per project | By design; large_project_handler.py samples for 500+ file projects |
| Chat history not persisted | In-session only; P1 improvement item |
| Binary files rejected from editor | By design (security + usability) |
| Shell commands allowlist-constrained | Phase B; for safety |
| Project must be on server's local disk | By design; no remote FS support |
| Port 8765 (not 8000) | Changed from 8011 due to conflict with ontology-simulator |
| Analysis knowledge gets stale after code changes | Freshness indicator + Git-aware re-analysis are P1/P2 items |
