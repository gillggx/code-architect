# Code Architect Agent — Sprint 3 & 4 Spec
**Version:** 1.0 | **Date:** 2026-03-22 | **Status:** Implementation

---

## Sprint 3 — Reliability

### 3.1 Semantic Context Window

#### Context & Objective
Long tasks (10+ tool calls) cause context to balloon, pushing the LLM past its effective reasoning range. Simple token truncation (Cline's approach) drops arbitrary history. We use project memory to do smarter injection: only load symbols for files currently in play, and summarize old conversation turns into a compact Technical State Summary.

#### Architecture & Design

**A. Dynamic Context Hydration**
Before every LLM call in `_agentic_loop`:
1. Inspect recent tool calls to find the "active files" set (files read or written in the last 6 iterations)
2. Look up those files in `project_modules` (by path stem match)
3. For each active file, also load its `imported_by` + first-degree `dependencies` modules
4. Build a compact `## Active Context` block with full symbols + edit_hints for these modules only
5. Replace the generic module list in system prompt with this focused block

**B. Conversation Summarization**
When `len(messages) > SUMMARY_THRESHOLD` (20 messages):
1. Take `messages[1 : len-4]` (preserve system prompt + last 4 turns)
2. Call LLM: "Summarize this technical session as a Technical State Summary: decisions made, files changed, current state, open problems."
3. Replace the old slice with a single `{"role": "system", "content": "## Technical State Summary\n{summary}"}` message

#### Constants
```python
SUMMARY_THRESHOLD = 20   # messages before summarization kicks in
ACTIVE_FILE_LOOKBACK = 6  # recent iterations to scan for active files
MAX_HYDRATED_SYMBOLS = 15 # symbols per hydrated module
```

#### QA Checklist — 3.1
- [ ] **R1** — Agent editing a 500-line file: context does NOT include unrelated module symbols
- [ ] **R2** — After 20 messages: a "Technical State Summary" system message replaces old turns; total messages drop below threshold
- [ ] **R3** — Hydration includes `imported_by` modules (2nd-degree) when editing a file
- [ ] **R4** — Summarization does not drop the system prompt or the last 4 messages
- [ ] **R5** — Summarization is skipped when `len(messages) <= SUMMARY_THRESHOLD`

---

### 3.2 Git-based Checkpoint

#### Context & Objective
Single-file revert exists but users need project-level undo. Git already tracks all changes; use it as the checkpoint engine.

#### Architecture & Design

**Backend**
- On `AgentRunner.__init__`: detect if `project_path` is a git repo (`git rev-parse HEAD`)
- If yes and `mode == "interactive"`: record `_git_base_branch` (current branch) and `_git_task_branch = architect/task-{session_id[:8]}`
- At first mutating tool call (before first apply): `git checkout -b {task_branch}`
- Store branch info in `AgentSession`
- New endpoint `POST /api/agent/rollback-session`:
  - `git checkout {base_branch}`
  - `git branch -D {task_branch}`
  - Returns `{status: "rolled_back", branch: base_branch}`

**Frontend**
- `TopBar`: show `🔄 Rollback` button when `agentSession` is active
- On click: confirm modal → `POST /api/agent/rollback-session` → clear events + session state

**Schema addition**
```python
class RollbackRequest(BaseModel):
    session_id: str
```

#### Edge Cases
- Not a git repo → skip branch creation, disable rollback button
- Dirty working tree (uncommitted changes) → stash before branching, pop after rollback
- Git command fails → log warning, continue without checkpoint

#### QA Checklist — 3.2
- [ ] **G1** — Starting an interactive task creates `architect/task-{id}` branch
- [ ] **G2** — Rollback endpoint returns to base branch and deletes task branch
- [ ] **G3** — Rollback button visible in UI when session is active
- [ ] **G4** — Rollback button hidden / disabled when no active session
- [ ] **G5** — Non-git project: no branch creation, no rollback button, no errors
- [ ] **G6** — After rollback: modified files are restored to pre-task state

---

## Sprint 4 — Differentiation

### 4.1 Impact Preview UI

#### Context & Objective
Pre-analysis memory is the killer feature. Before spending tokens on execution, show the user which files will likely be affected. Uses existing `/api/agent/impact` endpoint.

#### Architecture & Design

**Flow:**
1. User types task in ChatBar and clicks "Run" (interactive mode)
2. Frontend calls `POST /api/agent/impact` with `{project_id, task}`
3. Show `ImpactPreviewModal` with predicted files + confidence
4. User clicks "Confirm & Run" or "Cancel"
5. On confirm: proceed with normal agent start

**ImpactPreviewModal component:**
```tsx
<ImpactPreviewModal>
  <h3>Predicted Impact</h3>
  {files.map(f => (
    <div className="impact-row">
      <span className="impact-confidence-bar" style={{width: f.confidence*100%}} />
      <span>{f.path}</span>
      <span className="impact-badge">{f.reason}</span>
    </div>
  ))}
  <button onClick={onConfirm}>Confirm & Run</button>
  <button onClick={onCancel}>Cancel</button>
</ImpactPreviewModal>
```

#### QA Checklist — 4.1
- [ ] **I1** — Clicking Run shows impact modal before any agent call
- [ ] **I2** — Modal lists files with confidence score
- [ ] **I3** — Cancel closes modal, does not start agent
- [ ] **I4** — Confirm & Run closes modal and starts agent normally
- [ ] **I5** — Impact API failure → show warning toast, still allow proceeding
- [ ] **I6** — Modal shows loading state while impact API is called

---

### 4.2 Architecture Linter

#### Context & Objective
No tool on the market enforces project-specific architectural rules during AI-assisted editing. This turns the agent from a code writer into a tech lead that knows the team's rules.

#### Architecture & Design

**Config file** (`.architect-rules.yml` in project root):
```yaml
version: 1
rules:
  - id: no-db-in-controller
    description: "Controllers must not import DB models directly"
    match_files: "src/controllers/**"
    forbidden_imports:
      - "src/models/**"
      - "src/db/**"

  - id: api-extends-base
    description: "API route files must import BaseResponse"
    match_files: "src/api/routes/**"
    required_imports:
      - "BaseResponse"

  - id: no-cross-domain
    description: "Domain A must not import from Domain B"
    match_files: "src/domain/auth/**"
    forbidden_imports:
      - "src/domain/billing/**"
```

**Backend — `src/architect/api/arch_linter.py`:**
```python
class ArchLinter:
    def load_rules(project_path) -> list[Rule]
    def check_file(path, content, project_path) -> list[Violation]
```

**Integration in `agent_runner.py`:**
After every `write_file` / `edit_file` apply (before emitting `tool_output`):
1. Load rules (cached per session)
2. Run `linter.check_file(path, new_content)`
3. If violations → emit `tool_output` with error message, inject error into messages
4. Agent must fix and retry (same self-correction loop as syntax_lint)

**Violation message format:**
```
ARCHITECTURE VIOLATION [no-db-in-controller]:
  File: src/controllers/user_controller.py
  Rule: Controllers must not import DB models directly
  Found: import from src/models/user (forbidden)
  Fix: Use a service layer. Import UserService instead.
```

#### QA Checklist — 4.2
- [ ] **A1** — No `.architect-rules.yml`: linter is silently skipped
- [ ] **A2** — `forbidden_imports` violation is detected and blocks the write
- [ ] **A3** — `required_imports` violation is detected and blocks the write
- [ ] **A4** — Violation message includes file, rule id, and fix hint
- [ ] **A5** — Agent retries and fixes the violation within MAX_LINT_RETRIES
- [ ] **A6** — Glob patterns in `match_files` correctly scope which files are checked
- [ ] **A7** — Rules file parse error → warning logged, linter skipped (never crash agent)

---

### 4.3 Memory Panel Symbols UI

#### Context & Objective
The Memory Panel lists modules but not their internal symbols. After Sprint 3's analysis upgrade, each module has `symbols[]` with line numbers. Surface this so developers can navigate without reading full files.

#### Architecture & Design

**MemoryPanel changes:**
- Each module row becomes expandable
- Expanded state shows symbols list: `[type icon] name  line N  signature`
- Click on symbol → `setOpenedFile({path, line: symbol.line_start})` + `setCenterTab('file')`

**FileEditor changes:**
- Accept `line` prop in `openedFile` state
- On file load, scroll to / highlight the target line

**Store changes:**
```typescript
openedFile: { path: string; line?: number } | null
```

#### QA Checklist — 4.3
- [ ] **M1** — Module row click expands to show symbols list
- [ ] **M2** — Each symbol shows: type icon (fn/class/interface), name, line number, signature
- [ ] **M3** — Clicking a symbol opens File Editor tab at correct file + line
- [ ] **M4** — Module with no symbols (e.g. YAML config): no expand arrow shown
- [ ] **M5** — Symbols list is scrollable for large modules (>20 symbols)

---

## Cross-Sprint QA

- [ ] **X1** — Re-analyze after Sprint 3 changes: `modules.json` contains `symbols`, `edit_hints`, `imported_by`
- [ ] **X2** — No regression on existing approval flow (write/edit/run_command)
- [ ] **X3** — No regression on chat / RAG functionality
- [ ] **X4** — Frontend builds with zero TypeScript errors (`npx tsc --noEmit`)
- [ ] **X5** — Backend starts cleanly (`uvicorn` no import errors)
