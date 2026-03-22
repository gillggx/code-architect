# Code Architect Agent — Master PRD v3.0

**日期：** 2026-03-21
**狀態：** Sprint 1 & 2 已交付 ✅ / Sprint 3 待開發
**基於：** master_prd_v2.0.md
**本版範圍：** 五項改善項目的技術規格

---

## 改善項目總覽

| # | 優先級 | 項目 | 狀態 | 後端工作量 | 前端工作量 |
|---|--------|------|------|-----------|-----------|
| 4 | P1 | 平行分析（加速 4–8×） | ✅ 已交付 | asyncio.gather + Semaphore + retry | 無 |
| 3 | P1 | 分析新鮮度指示器 | ✅ 已交付 | 1 個 endpoint（純 stat） | TopBar 徽章、30 秒輪詢 |
| 2 | P0 | Refresh 模式（增量刷新） | ✅ 已交付 | refresh_project()、1 個 endpoint | TopBar 按鈕 |
| 5 | P3 | Dependency Graph 視覺化 | ✅ 已交付 | 1 個 endpoint（資料轉換） | DependencyGraph.tsx、第 4 個 tab |
| 1 | P0 | Code Edit Agent（Phase B 完工） | ⏳ 待開發 | agent_runner 串接、2 個 endpoint | Edit tab、DiffCard、CommandCard |

---

## 項目 4 — [P1] 平行分析 ✅ 已交付

### 實作摘要

- **`src/architect/analysis/llm_analyzer.py`**
  - `ANALYSIS_CONCURRENCY = int(os.getenv("ANALYSIS_CONCURRENCY", "6"))` 環境變數
  - `asyncio.Semaphore(ANALYSIS_CONCURRENCY)` 控制並發數
  - `asyncio.Lock()` 保護 `modules` list 與磁碟寫入（無競爭條件）
  - `asyncio.gather(..., return_exceptions=True)` — 單檔失敗不影響其他檔案
  - 增量快照仍在每個 task 完成後於 Lock 保護下即時寫入（不等 gather 全部完成）

- **`src/architect/llm/client.py`**
  - HTTP 429 偵測：`complete()` 中判斷 result 含 `[LLM Error:` + `429`/`rate_limit`
  - 指數退避：1s → 2s，最多 3 次重試

### 驗收確認項目

- [x] 分析 40 個檔案，總時間明顯縮短（預期 ~4× 加速）
- [x] `ActivityFeed` 事件以不規則順序到達（代表確實並發執行）
- [x] 單檔 LLM error 不中止整體分析，繼續處理其他檔案

---

## 項目 3 — [P1] 分析新鮮度指示器 ✅ 已交付

### 實作摘要

- **`src/architect/api/main.py`**
  - `GET /api/projects/{project_id}/freshness`
  - 回傳：`{ is_fresh, changed_files, new_files, deleted_files, last_analyzed_at, total_tracked }`
  - 純 `os.stat()` mtime/size 比對，不呼叫 LLM，< 100ms

- **`web/src/store/app.ts`**
  - 新增 `FreshnessStatus` 介面與 `freshnessStatus` / `setFreshnessStatus`

- **`web/src/components/TopBar.tsx`**
  - 載入專案後立即呼叫 `checkFreshness()`，每 30 秒輪詢
  - 分析完成後（`done` 事件）延遲 1 秒再重新 check
  - **過時狀態**：黃色可點擊徽章 `⚡ N 變動`（點擊觸發 Refresh）
  - **最新狀態**：低調灰色 `✅ 最新`

### 驗收確認項目

- [x] 選擇已分析的專案，TopBar 顯示正確新鮮度狀態
- [x] 手動修改任一專案檔案 → 30 秒內徽章自動切換為黃色 `⚡ N 變動`
- [x] 分析完成後徽章自動刷新為 `✅ 最新`
- [x] 點擊黃色徽章 → 觸發 Refresh（不是完整分析）

---

## 項目 2 — [P0] Refresh 模式（增量刷新）✅ 已交付

### 實作摘要

- **`src/architect/analysis/llm_analyzer.py`**
  - 新增 `refresh_project(project_path, memory_dir, emit)` 方法
  - 比對策略：新檔 / mtime 變動 / LLM-error 檔 → 重新分析；其餘 → skip
  - 以 `asyncio.gather` 並發執行增量分析（複用平行分析架構）
  - 結果以 `path` 為 key 合併回 modules.json，刪除磁碟已不存在的路徑

- **`src/architect/api/main.py`**
  - `POST /api/analyze/refresh`：若無 SNAPSHOTS.json 自動 fallback 至完整分析

- **`web/src/components/TopBar.tsx`**
  - `[⚡ Refresh]` 按鈕（獨立於 `[Analyze]` 旁）
  - Refresh 完成後（`done` 事件）：重新載入完整 file tree（`/api/projects/{id}/load`）確保 tree 不遺漏未變動檔案
  - Refresh 開始時**不清除** file tree（保留既有顯示）

### 修正紀錄

| Bug | 原因 | 修法 |
|-----|------|------|
| Refresh 後 FileTree 只剩 1 個檔案 | handleRefresh 呼叫 setFileTree([]) 清空，但只有被刷新的檔案才會發 WS 事件 | 移除 setFileTree([])，改在 done 事件後從 /api/projects/{id}/load 重載完整 tree |

### 驗收確認項目

- [x] 執行 Refresh 後 FileTree 顯示完整的所有檔案（非只剩新分析的檔案）
- [x] 僅修改過的檔案會出現 `llm_start` / `llm_done` 事件，未修改的出現 `skip`
- [x] 無 modules.json 時，Refresh 自動執行完整分析
- [x] Refresh 完成後新鮮度徽章刷新為 `✅ 最新`

---

## 項目 5 — [P3] Dependency Graph 視覺化 ✅ 已交付

### 實作摘要

- **`src/architect/api/main.py`**
  - `GET /api/projects/{project_id}/graph`
  - **雙重解析策略**（修正「只顯示外部 package」問題）：
    - `path_lookup`：完整路徑後綴匹配
    - `stem_lookup`：檔案名稱去副檔名匹配（`scenarios.py` → key `scenarios`）
    - `from X import Y` 格式處理：strip 前置字串，取 first_seg
    - 優先 `stem_lookup[first_seg]`，再 fallback `path_lookup` 多副檔名嘗試
  - 外部節點以頂層 package 名稱分組去重
  - Edge 去重後回傳

- **`web/src/components/DependencyGraph.tsx`** — 全新元件
  - Cytoscape.js + cytoscape-dagre
  - **節點互動**：點擊 → FileEditor；hover → tooltip；雙擊 → 高亮相鄰節點 + 淡化其他
  - **Entry point 節點**（main.py 等）：金色邊框
  - **外部依賴節點**：灰色、較小
  - **工具列**：顯示/隱藏外部依賴、Pattern 著色下拉選單、Layout 切換（DAG / Force）、清除高亮、重新整理
  - Dark mode 支援

- **`web/src/components/AgentActivityFeed.tsx`**
  - 新增「🕸 Graph」第 4 個 tab
  - 新增 File Editor tab 的關閉按鈕（✕）

- **`web/src/App.css`**
  - 新增 `.panel-tab-closeable` / `.panel-tab-label` / `.panel-tab-close` 樣式
  - `.panel-tab-close:hover` 呈紅色

### 修正紀錄

| Bug | 原因 | 修法 |
|-----|------|------|
| Graph 只顯示外部 package，看不到模組間關係 | 解析只用 last_seg（`scenarios.ValidationResult` → `ValidationResult.py`，不存在）| 新增 stem_lookup + first_seg 解析，`scenarios.ValidationResult` → stem `scenarios` → 成功匹配 `scenarios.py` |
| File Editor tab 無法關閉 | tab 只是 button，無法內嵌 ✕ 按鈕 | 改為 `<span class="panel-tab-closeable">` 含 label + ✕ button |

### 驗收確認項目

- [ ] Graph tab 顯示內部模組間的邊（不只是外部 package）
- [ ] 點擊節點 → 跳至 File Editor 開啟該檔案
- [ ] 雙擊節點 → 相鄰高亮，其他淡化；再雙擊或點「清除高亮」恢復
- [ ] 切換「顯示外部依賴」開關，外部灰色節點出現 / 消失
- [ ] File Editor tab 的 ✕ 關閉按鈕可正常關閉（回到 Activity tab）

---

## 項目 1 — [P0] Code Edit Agent（Phase B 完工）⏳ 待開發

### 背景與目標

`code_edit_agent_prd_v1.0.md` 的規格已完整，底層工具層（`api/tools/`、`agent_runner.py`、`diff.py`）已存在於磁碟。目標是將整條管線串通：使用者在瀏覽器輸入任務 → agent 生成程式碼 → 逐檔 diff 顯示 → 使用者逐一 Apply / Edit / Skip。

### 架構設計

**後端：已存在的基礎**
- `api/tools/` — file、search、git、shell、memory 工具
- `api/agent_runner.py` — agentic loop 骨架
- `api/diff.py` — unified diff 生成器

**需要串接的部分：**

```
POST /api/a2a/generate
  body: { task, project_id, mode: "dry_run"|"apply"|"interactive" }

  執行流程（Plan-Act 兩階段）：
  1. 載入專案記憶（RAG context）
  2. 組建 system prompt：架構摘要 + 偵測到的 pattern + 任務說明
  3. 【Phase A — Plan】Agent 強制先輸出 plan event（說明要改哪些檔案、原因）
     → SSE 發送 { type: "plan", ... }，前端顯示 PlanCard 等待使用者確認
     → 使用者 Approve plan 後才進入 Phase B
  4. 【Phase B — Act】執行 agentic loop（最多 20 次 tool call）：
       LLM → tool_call → execute → result → LLM → …
  5. 遇到 write_file / edit_file：
     interactive：暫停，SSE 發 approval_required，等待使用者 approve
     apply：直接執行（先備份，見下方「備份機制」）
     dry_run：只回傳 diff，不寫入

POST /api/agent/approve
  body: { session_id, action: "apply"|"skip"|"stop"|"approve_plan", edited_content? }
  → approve_plan：解除 Phase A 等待，進入 Phase B
  → apply / skip / stop：控制 Phase B 個別 write 操作

POST /api/agent/revert
  body: { session_id, file_path }
  → 將 .architect/backup/{file}.{timestamp} 還原覆蓋原始檔案
```

**備份機制（apply 前自動執行）：**
```
.architect/backup/
  └── src/api/main.py.20260321_143052   ← 原始檔案備份
  └── src/llm/client.py.20260321_143052
```
- apply 任何檔案前，先 copy 原始檔到 `.architect/backup/`
- `POST /api/agent/revert` 一鍵還原單一檔案
- backup 目錄加入 `.gitignore`（不污染版控）

**SSE 斷線重連機制：**
- 後端 session 斷線後進入 `paused` 狀態（非 cancel），保留 15 分鐘
- 前端重連時帶 `session_id`，後端重新 attach SSE stream 繼續發送
- `GET /api/agent/session/{session_id}` 回傳當前 session 狀態供前端判斷是否可重連

**前端 — AgentActivityFeed 中央面板：**
- 現有 ChatBar 中新增任務送出入口（或獨立 Edit tab）
- 事件卡片依 SSE 事件逐一渲染：
  - `plan` → **PlanCard**（已實作），等待使用者 [Approve Plan] 才繼續
  - `read_file` / `search_*` → 精簡 log 列（不需核准）
  - `write_file` / `edit_file` → **Diff 卡片**，含 [Apply] [Edit] [Skip] 按鈕；Apply 後 FileTree 對應檔案顯示 `●`
  - `run_command` → **指令卡片**，含 [Run] [Skip] 按鈕
- 全域停止按鈕
- 被修改的檔案在 FileTree 顯示 `●` 標記（store 已有 `modifiedFiles` Set）

### 逐步執行計畫
1. 完善 `agent_runner.py`：工具派送 loop、Plan phase 暫停、SSE 事件發送、寫入暫停 / 恢復（asyncio.Event）、備份邏輯
2. 在 `main.py` 串接 `POST /api/a2a/generate`：session 以 UUID 為 key 存入記憶體（逾時 15 分鐘）
3. 串接 `POST /api/agent/approve`（含 `approve_plan` action）與 `POST /api/agent/revert`
4. 新增 `GET /api/agent/session/{id}` 供前端重連時查詢狀態
5. 前端 ChatBar 送出任務 → 後端以 `mode: interactive` 執行 → ActivityFeed 渲染 PlanCard → Approve → DiffCard
6. `ApprovalCard` 骨架已在 AgentActivityFeed.tsx 中存在，補全 approve_plan 按鈕邏輯

### 邊界情境與風險

| 情境 | 處理策略 |
|------|---------|
| **Session 逾時** | 暫停超過 **15 分鐘**自動取消（改自原 5 分鐘），後端每 30 秒發 SSE ping keepalive |
| **SSE 斷線** | Task 進入 `paused`，保留 15 分鐘；前端重整後可重連繼續，不丟失進度 |
| **apply 後想反悔** | `.architect/backup/` 備份 + `/api/agent/revert` 一鍵還原，無需 git |
| **同時執行** | 同一 `project_id` 限 1 個 session，重複請求回傳 HTTP 409 |
| **路徑逃逸** | 所有寫入路徑必須通過 `project_root` 安全檢查 |
| **LLM 幻覺路徑** | `write_file` 目標在專案外 → skip 並警告，不終止 session |
| **使用者關閉瀏覽器** | Task ref 存入 session dict，15 分鐘後若無重連才 cancel |

---

## 驗收清單（Sprint 1 & 2）

以下為本輪交付的完整驗收項目，依優先級排列：

### 🔴 必驗（核心功能）

| # | 功能 | 操作 | 預期結果 |
|---|------|------|---------|
| R1 | Refresh 後 FileTree 完整 | 修改 1 個檔案後點 [⚡ Refresh] | FileTree 顯示所有檔案（非只 1 個），修改的檔案出現 llm_done 事件 |
| R2 | Graph 模組關係正確 | 分析後切 Graph tab | 存在內部模組之間的連線（不只是外部 package 箭頭） |
| R3 | File Editor 關閉按鈕 | 在 Graph 點擊一個節點開啟 File Editor tab | Tab 右側出現 ✕，點擊後回到 Activity tab |

### 🟡 建議驗（UX 品質）

| # | 功能 | 操作 | 預期結果 |
|---|------|------|---------|
| Y1 | 新鮮度輪詢 | 開啟專案後修改任意檔案，等待 ≤ 30 秒 | TopBar 徽章自動變為黃色 `⚡ N 變動` |
| Y2 | 新鮮度 → Refresh 捷徑 | 點擊黃色 `⚡ N 變動` 徽章 | 等同點 [⚡ Refresh] 按鈕，觸發增量分析 |
| Y3 | Graph 雙擊高亮 | 在 Graph 雙擊某節點 | 該節點與直接相鄰節點高亮，其他節點淡化 |
| Y4 | Graph 點擊跳轉 | 在 Graph 點擊內部模組節點 | 自動切換到 File Editor tab 並載入該檔案 |
| Y5 | 平行分析速度 | 分析含 20+ 個 Python 檔的專案 | ActivityFeed 事件以亂序到達（並發執行的證明）|

---

*Sprint 3 開始前，請確認 Sprint 1 & 2 所有 🔴 必驗項目通過。*
